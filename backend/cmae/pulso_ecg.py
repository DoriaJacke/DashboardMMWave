"""
TEMPORAL: pulso cardíaco calculado desde el ECG, en el dashboard.

La placa no calcula el pulso con el ECG, y el valor "filtrado" que envía
(filtered_input_uV) hoy llega con una escala rota (≈ raw24 × 3e-18). Mientras
eso no se corrija en el firmware, el pulso se calcula aquí a partir del dato
crudo raw24, que sí llega bien. No se toca la placa ni su firmware.

Método (Pan-Tompkins simplificado, el clásico para detectar latidos):

    raw24 -> pasa-banda 5-15 Hz -> derivada -> cuadrado -> promedio de 150 ms
          -> umbral adaptable -> un latido por cada pico (pico R)

El pulso es 60 000 / mediana de los últimos intervalos entre latidos (R-R).
Solo se informa cuando los intervalos son parecidos entre sí; si son ruido
(electrodos sueltos, movimiento) no se informa nada.

Como el detector usa umbrales relativos, no necesita saber la ganancia del
ADS1220 ni del AD8233: sirve con cualquier escala de raw24.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Tuple

FS_HZ = 586.0               # ritmo medido del ECG de la placa (por BLE, ~582-586 Hz)
VENTANA_INTEGRACION_S = 0.150
REFRACTARIO_MS = 250.0      # no puede haber dos latidos en menos de esto (máx. 240 BPM)
RR_MIN_MS = 300.0           # 200 BPM
RR_MAX_MS = 2000.0          # 30 BPM
APRENDIZAJE_MS = 2000.0     # al empezar, 2 s para conocer el tamaño de los picos
DESCARTE_INICIAL_MS = 300.0  # el arranque de los filtros da un pico falso
SIN_LATIDO_MS = 2500.0      # si no hay latido en este tiempo, el umbral baja a la mitad
HUECO_MS = 600.0            # un salto de tiempo mayor (datos perdidos) reinicia el conteo R-R
RR_GUARDADOS = 8
RR_PARA_CALCULAR = 4
TOLERANCIA_RR = 0.15        # un R-R "coincide" si está a menos del 15 % de la mediana
COINCIDENCIA_MIN = 0.75     # al menos el 75 % de los R-R deben coincidir
SATURACION = 8_300_000      # raw24 pegado al tope del ADC (±8 388 608): entrada al aire


def _biquad(tipo: str, fc: float, fs: float, q: float = 1 / math.sqrt(2)) -> Tuple[float, ...]:
    """Coeficientes (b0, b1, b2, a1, a2) de un filtro de 2.º orden (RBJ)."""
    w = 2 * math.pi * fc / fs
    alfa = math.sin(w) / (2 * q)
    c = math.cos(w)
    if tipo == "pasa_bajos":
        b0, b1, b2 = (1 - c) / 2, 1 - c, (1 - c) / 2
    else:  # pasa_altos
        b0, b1, b2 = (1 + c) / 2, -(1 + c), (1 + c) / 2
    a0 = 1 + alfa
    return b0 / a0, b1 / a0, b2 / a0, (-2 * c) / a0, (1 - alfa) / a0


class _Filtro:
    def __init__(self, coef: Tuple[float, ...]) -> None:
        self.b0, self.b1, self.b2, self.a1, self.a2 = coef
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def __call__(self, x: float) -> float:
        y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


class DetectorPulsoECG:
    def __init__(self, fs_hz: float = FS_HZ) -> None:
        self.fs = fs_hz
        self.reiniciar()

    def reiniciar(self) -> None:
        self._pa = _Filtro(_biquad("pasa_altos", 5.0, self.fs))
        self._pb = _Filtro(_biquad("pasa_bajos", 15.0, self.fs))
        self._prev: Deque[float] = deque([0.0, 0.0], maxlen=2)
        n = max(1, int(round(VENTANA_INTEGRACION_S * self.fs)))
        self._ventana: Deque[float] = deque([0.0] * n, maxlen=n)
        self._suma = 0.0
        self._t0: Optional[float] = None
        self._t_ultimo: Optional[float] = None
        self._max_aprendizaje = 0.0
        self._pico_senal = 0.0       # tamaño típico de un pico R (promedio móvil)
        self._umbral = 0.0
        self._candidato: Optional[Tuple[float, float]] = None   # (valor, t) del pico en curso
        self._t_latido: Optional[float] = None
        self._rr: Deque[float] = deque(maxlen=RR_GUARDADOS)
        self.bpm: Optional[float] = None
        self.valido = False

    def _reiniciar_rr(self) -> None:
        self._t_latido = None
        self._candidato = None
        self._rr.clear()
        self.valido = False

    def agregar(self, t_ms: float, raw24: int) -> Optional[float]:
        """Procesa una muestra. Devuelve el pulso (BPM) si en esta muestra se confirmó un latido válido."""
        if self._t_ultimo is not None and (t_ms - self._t_ultimo > HUECO_MS or t_ms < self._t_ultimo - HUECO_MS):
            self._reiniciar_rr()
        self._t_ultimo = t_ms
        if self._t0 is None:
            self._t0 = t_ms

        if abs(raw24) >= SATURACION:
            # Entrada saturada: la muestra no sirve y lo que venga de antes tampoco.
            self._reiniciar_rr()
            return None

        x = self._pb(self._pa(float(raw24)))
        derivada = x - self._prev[0]
        self._prev.append(x)
        cuadrado = derivada * derivada
        self._suma += cuadrado - self._ventana[0]
        self._ventana.append(cuadrado)
        y = max(self._suma, 0.0) / len(self._ventana)

        edad = t_ms - self._t0
        if edad < DESCARTE_INICIAL_MS:
            return None
        if edad < APRENDIZAJE_MS:
            self._max_aprendizaje = max(self._max_aprendizaje, y)
            return None
        if self._pico_senal == 0.0:
            self._pico_senal = self._max_aprendizaje
            self._umbral = 0.3 * self._pico_senal
            if self._umbral <= 0.0:
                self._t0 = t_ms      # señal plana: se vuelve a aprender
                return None

        # Mucho tiempo sin latidos: el umbral quedó alto (p. ej. tras un artefacto).
        referencia = self._t_latido if self._t_latido is not None else self._t0 + APRENDIZAJE_MS
        if t_ms - referencia > SIN_LATIDO_MS:
            self._pico_senal *= 0.5
            self._umbral = 0.3 * self._pico_senal
            self._t_latido = None
            self._t0 = t_ms - APRENDIZAJE_MS   # para que "referencia" avance
            self._rr.clear()
            self.valido = False

        if y > self._umbral:
            if self._candidato is None or y > self._candidato[0]:
                self._candidato = (y, t_ms)
            return None
        if self._candidato is None:
            return None

        # Terminó un pico por encima del umbral: es un latido (si respeta el refractario).
        valor, t_pico = self._candidato
        self._candidato = None
        if self._t_latido is not None and t_pico - self._t_latido < REFRACTARIO_MS:
            return None
        # Un artefacto enorme no debe subir demasiado la referencia.
        self._pico_senal = 0.875 * self._pico_senal + 0.125 * min(valor, 4.0 * self._pico_senal)
        self._umbral = 0.3 * self._pico_senal

        anterior, self._t_latido = self._t_latido, t_pico
        if anterior is None:
            return None
        rr = t_pico - anterior
        if not (RR_MIN_MS <= rr <= RR_MAX_MS):
            return None
        self._rr.append(rr)
        return self._calcular()

    def _calcular(self) -> Optional[float]:
        if len(self._rr) < RR_PARA_CALCULAR:
            self.valido = False
            return None
        orden: List[float] = sorted(self._rr)
        mitad = len(orden) // 2
        mediana = orden[mitad] if len(orden) % 2 else (orden[mitad - 1] + orden[mitad]) / 2
        coinciden = sum(1 for r in self._rr if abs(r - mediana) <= TOLERANCIA_RR * mediana)
        self.valido = coinciden / len(self._rr) >= COINCIDENCIA_MIN
        if not self.valido:
            return None
        self.bpm = 60000.0 / mediana
        return self.bpm
