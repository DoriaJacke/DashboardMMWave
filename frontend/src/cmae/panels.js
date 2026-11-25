// Gráficos de la placa CMAE que muestra el dashboard del radar.
//
// Mismas definiciones que dashboard-cmae/frontend/src/lib/panels.js (paneles
// "ecg", "pulse" y la fila "Atmosférica" de "pressure"). Las claves son las
// series que envía backend/cmae/servicio.py (SERIES_RADAR).

// Velocidad de cada señal: segundos visibles, redibujos por segundo, grosor de
// línea y cuándo una lectura se considera vieja (igual que en el dashboard CMAE).
export const SPEEDS = {
  fast: { windowS: 10, fps: 15, staleS: 2, lineWidth: 1 },
  medium: { windowS: 60, fps: 10, staleS: 4, lineWidth: 1.5 },
  slow: { windowS: 300, fps: 2, staleS: 15, lineWidth: 1.5 },
};

export const TIME_SCALES = [
  { value: 0.5, label: "Corta", hint: "ECG 5 s · pulso y presión diferencial 30 s · barométrica 2,5 min" },
  { value: 1, label: "Normal", hint: "ECG 10 s · pulso y presión diferencial 1 min · barométrica 5 min" },
  { value: 3, label: "Larga", hint: "ECG 30 s · pulso y presión diferencial 3 min · barométrica 15 min" },
];

export const PANELS = [
  {
    id: "ecg",
    title: "ECG filtrado",
    chip: "ADS1220 · AD8233",
    sensors: ["ads1220"],
    rows: [
      {
        speed: "fast",
        fps: 30, // ancho y rápido: a 15 por segundo se vería a saltos
        unit: "µV",
        digits: 0,
        minSpan: 300,
        hideValue: true,
        series: [{ key: "ecg_filtered_final_uV", label: "ECG", color: "--cm-ecg" }],
      },
    ],
  },
  {
    id: "ppg",
    title: "Pulsómetro",
    chip: "MAX30102 · onda IR",
    sensors: ["max30102"],
    rows: [
      {
        speed: "fast",
        unit: "cuentas",
        digits: 0,
        minSpan: 120,
        hideValue: true,
        series: [{ key: "ppg_ir", label: "IR", color: "--cm-violet" }],
      },
    ],
  },
  {
    id: "pulse",
    title: "Pulsómetro y oxímetro",
    chip: "MAX30102",
    sensors: ["max30102"],
    rows: [
      {
        speed: "medium",
        label: "SpO₂",
        unit: "%",
        digits: 1,
        minSpan: 4,
        series: [{ key: "spo2", label: "SpO₂", color: "--cm-spo2" }],
      },
      {
        speed: "medium",
        label: "Pulso",
        unit: "BPM",
        digits: 0,
        minSpan: 12,
        series: [
          { key: "bpm_float", label: "Oxímetro", color: "--cm-bpm" },
          // TEMPORAL: pulso calculado desde el ECG crudo (backend/cmae/pulso_ecg.py)
          { key: "ecg_bpm", label: "ECG", color: "--cm-ecg" },
        ],
      },
    ],
  },
  {
    id: "pressure",
    title: "Presiones",
    chip: "SDP810 · BME680",
    sensors: ["sdp810", "bme680"],
    rows: [
      {
        // Diferencial: sigue la respiración (frecuencia respiratoria).
        speed: "medium",
        label: "Diferencial",
        unit: "Pa",
        digits: 2,
        minSpan: 1,
        series: [{ key: "differential_pressure_pa", label: "SDP810", color: "--cm-orange" }],
      },
      {
        speed: "slow",
        label: "Barométrica",
        unit: "hPa",
        digits: 2,
        minSpan: 0.6,
        series: [{ key: "pressure_hpa", label: "BME680", color: "--cm-teal" }],
      },
    ],
  },
];

/** Aviso de un panel según las banderas que informa la placa: { text, tone } o null. */
export function panelBadge(id, b) {
  if (!b) return null;
  if (id === "ecg") {
    if (b.electrodos_ok === false) return { text: "Electrodos desconectados", tone: "warn" };
    if (b.ecg_pulso_valido === false) return { text: "Buscando latidos…", tone: "info" };
  }
  if (id === "ppg" && b.dedo === false) return { text: "Sin dedo", tone: "warn" };
  if (id === "pulse") {
    if (b.dedo === false) return { text: "Sin dedo", tone: "warn" };
    if (b.dedo && b.bpm_valido === false && b.spo2_valido === false) return { text: "Calculando…", tone: "info" };
  }
  return null;
}

/**
 * Estado de un panel según la edad de los datos de sus sensores:
 * "ok" (llegan), "stale" (dejaron de llegar), "none" (nunca llegaron), "idle" (sin conexión).
 */
export function panelStatus(panel, estado) {
  if (!estado || !estado.conexion?.activa) return "idle";
  const limit = panel.rows.reduce((s, r) => Math.max(s, SPEEDS[r.speed].staleS), 0);
  let seen = false;
  for (const sensor of panel.sensors) {
    const s = estado.sensores?.[sensor];
    if (!s) continue;
    seen = true;
    if (s.edad_s <= limit) return "ok";
  }
  return seen ? "stale" : "none";
}

/** Color y texto del estado de conexión de la placa. */
export function connectionTone(conexion) {
  const e = conexion?.estado;
  if (e === "Conectada") return { color: "var(--cm-ok)", text: "Conectada" };
  if (e === "Conectando" || e === "Reconectando" || e === "Desconectando") return { color: "var(--cm-warn)", text: e };
  if (e === "Error") return { color: "var(--cm-bad)", text: "Error" };
  return { color: "var(--color-neutral-500)", text: "Desconectada" };
}
