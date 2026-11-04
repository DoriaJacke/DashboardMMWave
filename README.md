# DashboardMMWave

Dashboard preliminar para proyecto de título sobre el uso de radar de onda milimétrica (mmWave) en un estudio piloto de monitoreo de respiración y frecuencia cardíaca.

El sistema adquiere datos de un radar **Seeed MR60BHA1 (60 GHz)** conectado a un **ESP32**, los registra en CSV siguiendo protocolos de medición definidos, y permite visualizarlos y analizarlos desde un dashboard web hecho con **Streamlit**.

Opcionalmente, registra al mismo tiempo el **BPM y el SpO2 de la placa biomédica CMAE** (conectada por Bluetooth), como referencia para validar al radar. Ver [Placa biomédica CMAE (PBM)](#placa-biomédica-cmae-pbm).

---

## Contenido del repositorio

```
DashboardMMWave/
├── dashboard/                 Dashboard Streamlit
│   ├── app.py                 Interfaz (secciones Adquisición y Análisis)
│   ├── acquisition.py         Fuentes de datos, sesión de adquisición y protocolos
│   ├── data_io.py             Lectura de CSV, intervalos de fase y resúmenes
│   ├── plots.py               Gráficos (Plotly, Matplotlib) y filtro Savitzky-Golay
│   ├── cmae_conexion.py       Conexión BLE con la placa CMAE (con reconexión automática)
│   └── cmae_protocolo.py      Protocolo de la placa CMAE: fragmentos BLE, trama AA55, BPM, SpO2 y PPG
├── CodigosBaseMirko/          Scripts originales en que se basa el dashboard
│   ├── MEDICION20SEQRES.py    Protocolo de 20 mediciones con retención respiratoria
│   ├── tomadatosSEPT.py       Captura continua
│   └── HRBRWF.py              Gráficos Waveform BW / HR / BR por medición
├── MedirHRBRVF/
│   └── MedirHRBRVF.ino        Firmware del ESP32
├── datos/                     CSV generados por el dashboard (se crea automáticamente)
└── requirements.txt
```

---

## Hardware y comunicación

- **Radar:** MR60BHA1 conectado al `Serial2` del ESP32 (RX = GPIO16, TX = GPIO17, 115200 baudios).
- **ESP32 → PC:** puerto USB serial a **115200 baudios**. El ESP32 envía una línea de texto por cada dato, con campos separados por comas:

| Línea | Contenido |
|---|---|
| `START` | Inicio de transmisión |
| `HR,<valor>` | Frecuencia cardíaca |
| `BR,<valor>` | Frecuencia respiratoria |
| `DIST,<valor>` | Distancia a la persona |
| `EVENT,<texto>` | Estado de movimiento / presencia |
| `BW,<v1>,<v2>,<v3>,<v4>,<v5>` | 5 muestras de la waveform de respiración |

Las líneas que no siguen este formato (por ejemplo mensajes de inicio del firmware) se ignoran.

> **Nota sobre el firmware:** `MedirHRBRVF.ino` actualmente desactiva la waveform y solo envía `HR` y `BR`. Con ese firmware los gráficos de waveform BW, la distancia y el evento quedan vacíos. Para usarlos, el firmware debe enviar también las líneas `BW`, `DIST` y `EVENT`.

### Unidades de cada parámetro

Todos los valores los calcula internamente el MR60BHA1; el ESP32 solo los reenvía.

| Parámetro | Unidad | Observaciones |
|---|---|---|
| `HR` | latidos por minuto (BPM) | Valor estimado por el sensor, aprox. uno por segundo |
| `BR` | respiraciones por minuto | Valor estimado por el sensor, aprox. uno por segundo |
| `DIST` | centímetros (según protocolo Seeed, **por confirmar**) | El medidor de distancia asume cm; la unidad se puede cambiar en el dashboard |
| `BW` | sin unidad física (amplitud relativa) | Sirve para forma, ritmo y amplitud relativa de la respiración; según el protocolo Seeed serían valores 0–255 centrados cerca de 128 (**por confirmar**) |
| `EVENT` | texto | Estado categórico |
| `timestamp` | hora del PC al recibir la línea | No es la hora de medición del sensor; puede haber un pequeño desfase por el puerto serial y el `delay(200)` del firmware |

---

## Instalación

Requiere Python 3.10 o superior.

```
pip install -r requirements.txt
```

Dependencias: `streamlit`, `pyserial`, `pandas`, `numpy`, `plotly`, `matplotlib`, `scipy` y `bleak` (Bluetooth, para la placa CMAE).

## Ejecución

Desde la raíz del repositorio:

```
streamlit run dashboard/app.py
```

El dashboard se abre en http://localhost:8501.

---

## Sección Adquisición

### 1. Fuente de datos

- **Puerto serial (ESP32):** se listan los puertos detectados (botón *Actualizar* para volver a buscarlos). Si no aparece ninguno, se puede escribir manualmente (por ejemplo `COM4`). Baudrate por defecto: 115200.
- **Simulador (sin hardware):** genera líneas `START`, `HR`, `BR`, `DIST`, `EVENT` y `BW` con el mismo formato del ESP32, para probar el dashboard sin el radar. Durante la fase de retención simula la disminución de la respiración. Sus escalas (por ejemplo BW entre −1 y 1) no representan las del sensor real.

### 2. Protocolos

#### Secuencia con retención (basado en `MEDICION20SEQRES.py`)

Para cada medición se repite el ciclo:

| Fase | Etiqueta en el CSV | `flag_hold` | Duración por defecto |
|---|---|---|---|
| Espera a que la persona se posicione | (no se guarda) | – | hasta presionar el botón |
| Respiración normal | `NORMAL` / `RESPIRACION_NORMAL` | 0 | 20 s |
| Preparación + cuenta regresiva 3‑2‑1 | `PREP` / `PREPARACION` | 0 | 1 s + 3 s |
| Retención voluntaria de la respiración | `HOLD` / `RETENCION` | 1 | 10 s |
| Descanso / recuperación | `RECOVERY` / `RECUPERACION` | 0 | 30 s |
| Fin de medición | fila `END` | 0 | – |
| Pausa entre mediciones | (no se guarda) | – | 3 s |

Todos los parámetros son configurables: número de mediciones (20 por defecto), duraciones, cuenta regresiva, pausa y si se espera confirmación antes de cada medición (equivale al "Presiona ENTER" del script original).

#### Captura continua (basado en `tomadatosSEPT.py`)

Registra todas las líneas recibidas hasta presionar *Detener adquisición*, o durante una duración fija si se indica (0 = indefinida).

### 3. Archivo de salida

Los CSV se guardan en `datos/` con un nombre por defecto que incluye fecha y hora (`MR60BHA1_mediciones_AAAAMMDD_HHMMSS.csv` o `MR60BHA1_experimento_AAAAMMDD_HHMMSS.csv`). El nombre se puede editar; si el archivo ya existe, el dashboard no lo sobrescribe.

### 4. Vista en vivo

Mientras se adquiere:

- Banner con la fase actual (color por fase), número de medición y segundos restantes o cuenta regresiva.
- Botón **"Estoy en posición — comenzar medición N"** cuando el protocolo espera confirmación.
- Barra de avance de mediciones.
- Últimos valores de HR, BR y evento, y número de líneas recibidas / guardadas.
- **Medidor de distancia:** indicador tipo velocímetro con la distancia actual de la persona al radar y tres zonas de color: *muy cerca* (naranjo), *distancia adecuada* (verde) y *muy lejos* (rojo). Al lado, un gráfico con la distancia de los últimos 60 s y la zona adecuada sombreada.
  - Funciona también durante la espera de posicionamiento (antes de presionar "Estoy en posición"), para ubicar a la persona antes de medir.
  - La zona adecuada (40–150 cm por defecto), la escala del medidor (300 cm) y la unidad se configuran en el desplegable *Medidor de distancia: zona adecuada*.
  - Si no llegan datos `DIST` por más de 5 s, el medidor indica *Sin datos recientes*.
- Gráficos en vivo (actualizados cada segundo) con opciones de eje X, ventana (*Medición actual*, *Últimos 60 s*, *Todo*), sombreado de fases y filtro Savitzky-Golay.
- Botón **Detener adquisición**.

Si se recarga la página, el dashboard se reconecta a la adquisición en curso. Al terminar, se muestra un resumen de la última adquisición con sus gráficos.

---

## Formatos de CSV

### Secuencia con retención (formato largo)

Una fila por línea recibida, más filas de marca de fase:

```
timestamp, medicion, fase, condicion, flag_hold, tipo, valor_1, valor_2, valor_3, valor_4, valor_5
```

- `timestamp`: fecha y hora ISO del PC con milisegundos.
- `tipo`: `START`, `PHASE` (inicio de fase), `END` (fin de medición), `HR`, `BR`, `DIST`, `EVENT` o `BW`.
- `valor_1`: valor de `HR`, `BR`, `DIST` o texto de `EVENT`.
- `valor_1` a `valor_5`: las 5 muestras de `BW`.

### Captura continua (formato ancho)

Una fila por línea recibida, con el último valor conocido de cada parámetro:

```
timestamp, datetime, HR, BR, distance, movement, raw
```

- `timestamp`: segundos desde el inicio de la adquisición.
- `datetime`: fecha y hora ISO del PC.
- `raw`: línea original recibida (de aquí se recupera la waveform `BW` en el análisis).

Ambos formatos son los mismos que generan los scripts originales, por lo que los CSV antiguos también se pueden abrir en la sección Análisis.

---

## Placa biomédica CMAE (PBM)

La placa CMAE se usa como referencia para validar la frecuencia cardíaca del radar. Su conexión es **opcional**: si no está conectada al iniciar, la adquisición es solo del radar.

### Conexión

- **Bluetooth (BLE).** El PC debe tener Bluetooth. La placa se busca por su nombre `CMAE-<número>-S3-N16R8`. En la sección *Placa biomédica CMAE (opcional)* se indica el número de dispositivo y se presiona **Conectar placa** (antes de iniciar la adquisición).
- Al conectar, el dashboard le envía `START`; al desconectar, `STOP`. Los datos llegan en fragmentos CMAE-FRAG que se rearman en tramas `AA 55` con verificación CRC16 (mismo protocolo que el receptor original de la placa).
- **Si la conexión se corta** (o la placa deja de enviar datos por 10 s), el radar sigue grabando, aparece un aviso y la placa intenta **reconectarse sola** hasta lograrlo o hasta presionar *Desconectar placa*. Mientras está desconectada, su archivo queda con un hueco.

### Qué se registra

| Dato | Se muestra | Se guarda |
|---|---|---|
| BPM (`bpm_float` del MAX30102, unas 7 lecturas por segundo) | Sí, en vivo y en un gráfico propio | Sí |
| SpO2 (MAX30102) | Sí, en vivo y en un gráfico propio | Sí |
| Onda PPG infrarroja (104 muestras por segundo) | Sí, últimos 10 s | **No** |
| ECG | No | No |

Las lecturas se guardan **solo durante las fases** del protocolo, igual que el radar, y cada una lleva la **hora del PC** al recibirla y la fase vigente. Así las ventanas de tiempo (fases) son las mismas para el radar y la placa.

### Archivo de la placa

Se guarda en `datos/` junto al CSV del radar, con el **mismo ID**: el prefijo `MR60BHA1` se reemplaza por `PBM` (si el nombre no empieza con `MR60BHA1`, se le antepone `PBM_`).

```
MR60BHA1_mediciones_20261104_101500.csv   ← radar
PBM_mediciones_20261104_101500.csv        ← placa CMAE
```

Columnas (el mismo formato para ambos protocolos; en captura continua `fase` es `CONTINUO`):

```
timestamp, medicion, fase, condicion, flag_hold, bpm, spo2, dedo_detectado, bpm_valido, spo2_valido
```

- `timestamp`: fecha y hora ISO del PC con milisegundos (mismo reloj que el CSV del radar).
- `bpm`, `spo2`: valores enviados por la placa con 2 decimales; vacíos si la placa no tiene lectura.
- `dedo_detectado`, `bpm_valido`, `spo2_valido`: `1` o `0` según la placa. **Se guardan todas las lecturas**, también las no válidas; el filtrado se hace en el análisis.

En la vista en vivo, el gráfico de la placa usa el mismo eje de tiempo y el mismo sombreado de fases que el del radar. Solo dibuja las lecturas válidas (dedo detectado y valor válido).

---

## Sección Análisis

- **Origen de datos:** archivos de la carpeta `datos/` (ordenados del más reciente al más antiguo) o un CSV subido. El formato (secuencia o continuo) se detecta automáticamente.
- **Gráficos** en el estilo de `HRBRWF.py` (línea azul, puntos naranjos), interactivos (zoom, desplazamiento):
  1. Waveform BW
  2. Frecuencia cardíaca (HR)
  3. Frecuencia respiratoria (BR)
- **Selección de medición:** una medición específica o todas.
- **Eje X:** *Índice de muestra* (igual al script original) o *Tiempo (s)*. En modo tiempo, las fases `NORMAL`, `PREP`, `HOLD` y `RECOVERY` se sombrean con colores. Las 5 muestras de cada trama BW se reparten uniformemente en el intervalo entre tramas.
- **Resumen por fase:** media, desviación estándar y cantidad de datos de HR, BR y distancia por medición y fase.
- **Exportar imágenes:** genera un ZIP con una imagen `medicion_XX.png` por medición (Matplotlib, mismo estilo de `HRBRWF.py`, DPI configurable, 300 por defecto).
- **Datos crudos:** tabla con el CSV original.

### Filtro Savitzky-Golay (waveform BW)

Disponible en Análisis y en la vista en vivo. Al activarlo se superponen la **onda bruta** (azul/naranjo, atenuada) y la **onda filtrada** (línea roja).

- **Ventana** en segundos (0,1 a 3 s, por defecto 0,8 s) y **orden del polinomio** (2 a 5, por defecto 2).
- La ventana se convierte a muestras según la frecuencia de muestreo de la BW estimada desde los datos; el dashboard muestra el valor calculado (siempre impar y mayor que el orden).
- Se filtra cada tramo continuo por separado: el filtro no cruza los huecos entre mediciones. Los tramos más cortos que la ventana quedan sin curva filtrada.
- El filtro solo afecta la visualización y las imágenes exportadas; **los CSV guardados conservan los datos brutos**.
- Recomendación: usar una ventana bastante menor que un ciclo respiratorio (aprox. 2–6 s) para no aplanar los picos.

---

## Diferencias con los scripts originales

- El sensor se lee **continuamente** en un hilo aparte. En los scripts originales, los datos que llegaban durante el `input()` o la cuenta regresiva quedaban acumulados en el buffer serial y se guardaban después con la etiqueta de la fase siguiente (por ejemplo, datos de la preparación como retención). Ahora los datos de la preparación quedan etiquetados como `PREP` y los de las esperas no se guardan.
- La captura continua escribe cada línea en el CSV **al recibirla** (el script original guardaba todo al final), por lo que no se pierden datos si el programa se interrumpe.
- Las duraciones y el número de mediciones se configuran desde la interfaz, sin editar el código.
- Los archivos se guardan en `datos/` con fecha y hora en el nombre y no se sobrescriben.

## Limitaciones conocidas

- Solo se ejecuta una adquisición a la vez (compartida entre pestañas del navegador).
- No se ha validado aún con el radar real la unidad de `DIST` ni la escala de `BW`.
- HR y BR son estimaciones internas del sensor; no se dispone de la señal de fase cruda del radar ni de una waveform cardíaca.
- Placa CMAE: la integración se probó con una placa simulada que reproduce una captura real (`.bin`); falta la prueba con la placa real en un PC con Bluetooth.
- Placa CMAE: la sección Análisis todavía no lee los archivos `PBM_...`.
- Placa CMAE: la placa no entrega frecuencia respiratoria, así que no sirve como referencia para `BR`.
