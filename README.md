# DashboardMMWave

Dashboard preliminar para proyecto de título sobre el uso de radar de onda milimétrica (mmWave) en un estudio piloto de monitoreo de respiración y frecuencia cardíaca.

El sistema adquiere datos de un radar **Seeed MR60BHA1 (60 GHz)** conectado a un **ESP32**, los registra en CSV siguiendo protocolos de medición definidos y los muestra en un dashboard web. Un **backend en Python (FastAPI)** lee el sensor y escribe los archivos; un **frontend en React + React-Bootstrap** es la interfaz.

---

## Contenido del repositorio

```
DashboardMMWave/
├── backend/                   Backend Python (FastAPI)
│   ├── main.py                API REST y WebSocket en vivo
│   ├── acquisition.py         Fuentes de datos, sesión de adquisición y protocolos
│   ├── config.py              Valores por defecto, validación y configuración guardada
│   ├── data_io.py             Lectura de CSV, intervalos de fase y resúmenes
│   ├── plots.py               Filtro Savitzky-Golay y exportación de imágenes PNG
│   └── cmae/                  Placa CMAE: protocolo, conexión y datos en vivo (ver "Placa CMAE")
├── frontend/                  Interfaz (Vite + React + React-Bootstrap)
│   └── src/
│       ├── App.jsx            Pantallas y estado general
│       ├── components/        Banner, métricas, distancia, gráficos, resultado…
│       ├── lib/               Conexión en vivo, API, series y cálculos de los gráficos
│       ├── cmae/              Gráficos en vivo de la placa CMAE (uPlot) y su conexión
│       └── styles/            Sistema de diseño y tema Bootstrap
├── CodigosBaseMirko/          Scripts originales en que se basa el dashboard
│   ├── MEDICION20SEQRES.py    Protocolo de 20 mediciones con retención respiratoria
│   ├── tomadatosSEPT.py       Captura continua
│   └── HRBRWF.py              Gráficos Waveform BW / HR / BR por medición
├── MedirHRBRVF/
│   └── MedirHRBRVF.ino        Firmware del ESP32
├── datos/                     CSV generados por el dashboard (se crea automáticamente)
├── Dockerfile                 Imagen con la interfaz compilada y el backend
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

> **Nota sobre el firmware:** `MedirHRBRVF.ino` actualmente desactiva la waveform y solo envía `HR` y `BR`. Con ese firmware los gráficos de waveform BW, la distancia y el evento quedan vacíos, y la interfaz lo indica. Para usarlos, el firmware debe enviar también las líneas `BW`, `DIST` y `EVENT`.

### Unidades de cada parámetro

Todos los valores los calcula internamente el MR60BHA1; el ESP32 solo los reenvía.

| Parámetro | Unidad | Observaciones |
|---|---|---|
| `HR` | latidos por minuto (BPM) | Valor estimado por el sensor, uno cada 3 s. Un 0 significa que no hay estimación |
| `BR` | respiraciones por minuto | Valor estimado por el sensor, uno cada 3 s |
| `DIST` | metros, resolución de 1 cm | Uno por segundo. Confirmado con datos reales (por ejemplo, 0,59 m) |
| `BW` | sin unidad física (amplitud relativa) | Sirve para forma, ritmo y amplitud relativa de la respiración; según el protocolo Seeed serían valores 0–255 centrados cerca de 128 (**por confirmar**) |
| `EVENT` | texto | Estado categórico |
| `timestamp` | hora del PC al recibir la línea | No es la hora de medición del sensor; ver *Retraso de los datos* |

### Retraso de los datos

Medido con la placa real (COM3, 11-11-2026), los datos llegan al PC con este ritmo:

| Línea | Cada cuánto llega | Retraso que introduce |
|---|---|---|
| `HR`, `BR` | 3,0 s (exacto) | Hasta 3 s entre que cambia el valor y se ve, más la ventana de cálculo interna del radar |
| `BW` | 1,0 s, con 5 muestras | La onda llega en bloques de 1 s: la muestra más antigua de cada bloque ya tiene ~1 s |
| `DIST`, `EVENT` | 1,0 s | Hasta 1 s |

El retraso de ~3 s que se nota en HR y BR viene del MR60BHA1: entrega un valor nuevo cada 3 s y lo calcula sobre los segundos anteriores. No se puede reducir desde el dashboard. El `timestamp` del CSV es la hora de llegada al PC, así que el valor de HR o BR de una fila describe lo que pasó unos segundos antes. Tenlo en cuenta al comparar con las marcas o con el cambio de fase (por ejemplo, el inicio de la retención).

El dashboard envía cada dato a la página apenas llega (se revisa cada 0,1 s), así que no agrega un retraso apreciable.

---

## Instalación

Requiere **Python 3.10 o superior** y **Node.js 20.19 o superior** (Node solo hace falta para compilar la interfaz).

Desde la raíz del repositorio:

```
pip install -r requirements.txt
cd frontend
npm install
npm run build
```

`npm run build` genera `frontend/dist`, la interfaz compilada que sirve el backend. No está en el repositorio: hay que volver a generarla cada vez que cambie el código de `frontend/`. Después de compilar, Node ya no se necesita para usar el dashboard, y la interfaz funciona sin internet.

## Ejecución

Desde la raíz del repositorio:

```
uvicorn backend.main:app --port 8000
```

El dashboard se abre en http://localhost:8000.

### Para desarrollar la interfaz

En dos terminales, para ver los cambios sin compilar:

```
uvicorn backend.main:app --port 8000
cd frontend && npm run dev
```

La interfaz queda en http://localhost:5173 y redirige la API y el WebSocket al puerto 8000.

### Con Docker

> **En Windows, el contenedor no ve los puertos COM ni el Bluetooth.** Sirve para probar el dashboard con el **Simulador** del radar y la placa CMAE **Simulada**, pero no para medir con el hardware: para eso hay que ejecutarlo sin Docker, como se indica arriba.

La imagen compila la interfaz por su cuenta, así que solo hace falta Docker. Desde la raíz del repositorio, en PowerShell:

```
docker build -t dashboard-mmwave .
docker run --rm -p 8000:8000 -v "${PWD}/datos:/app/datos" dashboard-mmwave
```

El dashboard se abre en http://localhost:8000.

- **No omitas `-v`:** es lo que guarda los CSV en la carpeta `datos/` del PC. Sin esa opción, los archivos se pierden al detener el contenedor.
- **Zona horaria:** los CSV guardan la hora local del contenedor. La imagen usa `America/Santiago`; para otra zona, agrega `-e TZ=<zona>` a `docker run`. Comprueba que coincida con la del PC, porque la sincronización con otros equipos depende de esa hora.

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

#### Apnea + monitoreo

Una sola maniobra de apnea y, a continuación, monitoreo continuo:

| Fase | Etiqueta en el CSV | `flag_hold` | Duración por defecto |
|---|---|---|---|
| Espera a que la persona se posicione | (no se guarda) | – | hasta presionar el botón |
| Respiración basal | `NORMAL` / `RESPIRACION_NORMAL` | 0 | 20 s (0 = sin basal) |
| Preparación + cuenta regresiva | `PREP` / `PREPARACION` | 0 | 1 s + 3 s |
| Apnea voluntaria | `HOLD` / `APNEA` | 1 | 10 s |
| Monitoreo continuo | `MONITOREO` / `MONITOREO_CONTINUO` | 0 | 300 s (0 = hasta detener) |
| Fin | fila `END` | 0 | – |

- Usa el mismo CSV de formato largo que la secuencia (medición 1), así que Análisis, el resumen por fase y la exportación funcionan igual. El nombre por defecto es `MR60BHA1_apnea_AAAAMMDD_HHMMSS.csv`.
- Si el monitoreo no tiene duración, **Detener adquisición** es el fin normal: se escribe la fila `END` y el resultado queda como *completada*.
- Durante el monitoreo el banner muestra el tiempo restante o el transcurrido, y se pueden poner marcas como en las demás fases.
- Los gráficos en vivo empiezan en la ventana *Últimos 5 min*: mientras la toma dura menos de 5 min se ve desde el inicio (con la basal y la apnea); después la ventana avanza y muestra siempre los últimos 5 min. Se puede cambiar en las opciones del gráfico.
- Las duraciones de este modo se guardan aparte de las de la secuencia (`a_tn`, `a_cd`, `a_th`, `a_tm` en la configuración), así que cambiar una no altera la otra.

#### Captura continua (basado en `tomadatosSEPT.py`)

Registra todas las líneas recibidas hasta presionar *Detener adquisición*, o durante una duración fija si se indica (0 = indefinida).

### 3. Archivo de salida

Los CSV se guardan en `datos/` con un nombre por defecto que incluye fecha y hora (`MR60BHA1_mediciones_…`, `MR60BHA1_apnea_…` o `MR60BHA1_experimento_AAAAMMDD_HHMMSS.csv`). El nombre se puede editar; si el archivo ya existe, el dashboard no lo sobrescribe.

### 4. Configuración conservada

La última configuración usada (fuente, puerto, baudrate, protocolo y zona de distancia) se guarda en `datos/.dashboard_config.json` y se recupera al volver a abrir el dashboard, así la siguiente adquisición no vuelve en silencio a los valores por defecto. El nombre de archivo no se guarda: cada adquisición genera uno nuevo. Ese archivo es local y no se sube al repositorio.

### 5. Vista en vivo

Mientras se adquiere:

- **Banner de fase**, legible a distancia por el participante: color por fase, número de medición y segundos restantes o cuenta regresiva, con el avance de todas las mediciones.
- Botón **"Estoy en posición — comenzar medición N"** cuando el protocolo espera confirmación (o tecla **Enter**).
- Botón **"Marcar punto de interés"** (o tecla **M**) en las fases que se graban. Ver *Marcas*, más abajo.
- Últimos valores de HR, BR y evento, con la antigüedad de cada dato (en gris si tiene más de 3 s, o 12 s para el evento), y líneas recibidas / guardadas.
- **Medidor de distancia:** indicador tipo velocímetro con la distancia actual de la persona al radar y tres zonas de color: *muy cerca* (naranjo), *distancia adecuada* (verde) y *muy lejos* (rojo). Debajo, la distancia de los últimos 60 s con la zona adecuada sombreada.
  - Funciona también durante la espera de posicionamiento (antes de presionar "Estoy en posición"), para ubicar a la persona antes de medir.
  - La zona adecuada (0,40–1,50 m por defecto) y la escala del medidor (3 m) se configuran con el botón que muestra la zona actual. Una configuración guardada en cm se convierte sola a metros.
  - Si no llegan datos `DIST` por más de 5 s, el medidor indica *Sin datos recientes*.
- **Gráficos** de waveform BW, HR y BR, con el eje X compartido. El botón de opciones cambia el eje X (*Tiempo* o *Índice de muestra*), la ventana (*Medición actual*, *Últimos 60 s*, *Últimos 5 min*, *Todo*), el sombreado de fases y el filtro Savitzky-Golay. En *Medición actual* las fases que faltan se ven atenuadas y una línea punteada marca el instante actual.
- **Zoom:** arrastrar sobre un gráfico acerca los tres; doble clic restablece. Los botones ← + − → hacen lo mismo con el teclado o el mouse.
- Botón **Detener adquisición**, en el encabezado.

Si se recarga la página o se abre otra pestaña, se vuelve a ver la adquisición en curso. Si se corta la conexión con el backend, la página avisa y se reconecta sola. Desde la pestaña Análisis, un indicador muestra la adquisición en curso y permite volver a ella.

### 6. Resultado

Al terminar se muestra el estado final (completada, detenida manualmente o con error), la configuración de la siguiente adquisición y:

- **Gráficos** de la adquisición, por medición o todas, por índice de muestra o por tiempo.
- **Resumen por fase:** media, desviación estándar y cantidad de datos de HR, BR y distancia por medición y fase (en secuencia y en apnea + monitoreo).
- **Exportar imágenes:** genera un ZIP con una imagen `medicion_XX.png` por medición (Matplotlib, mismo estilo de `HRBRWF.py`, DPI configurable, 300 por defecto).

### Marcas

El operador puede marcar puntos de interés durante las fases que se graban. Cada marca recibe una etiqueta (M1, M2…, numeradas por adquisición), aparece como una línea vertical en los tres gráficos y queda guardada en el CSV junto con su fase y su hora.

### Filtro Savitzky-Golay (waveform BW)

Disponible en la vista en vivo y en el resultado. Al activarlo se superponen la **onda original** (atenuada) y la **onda filtrada** (línea oscura).

- **Ventana** en segundos (0,1 a 3 s, por defecto 0,8 s) y **orden del polinomio** (2 a 5, por defecto 2).
- La ventana se convierte a muestras según la frecuencia de muestreo de la BW estimada desde los datos; el dashboard muestra el valor calculado (siempre impar y mayor que el orden).
- El filtro no cruza los huecos entre mediciones. Los tramos más cortos que la ventana quedan sin curva filtrada.
- El filtro solo afecta la visualización y las imágenes exportadas; **los CSV guardados conservan los datos brutos**.
- Recomendación: usar una ventana bastante menor que un ciclo respiratorio (aprox. 2–6 s) para no aplanar los picos.

---

## Placa CMAE

> **Deshabilitada por defecto.** Mientras se revisa la integración con el profesor guía, la placa está aislada del
> dashboard del radar: el backend no carga `backend/cmae/` (ni Bluetooth), no expone `/api/cmae/*` ni `/ws/cmae`,
> no graba `<archivo>_cmae.csv`, y la interfaz oculta la pestaña *Placa CMAE* y sus tarjetas. El código sigue en el
> repositorio. Para encenderla, define `MMWAVE_CMAE=1` antes de iniciar el backend
> (PowerShell: `$env:MMWAVE_CMAE = "1"`; cmd: `set MMWAVE_CMAE=1`) o descomenta la línea en `levantar_dashboard.bat`.
> `GET /api/features` dice si está activa. Ver `backend/features.py`.

El dashboard adquiere, junto con el radar, tres señales de la placa CMAE como referencia, sincronizadas con el protocolo de captura:

| Gráfico | Sensor | Qué muestra |
|---|---|---|
| ECG filtrado | ADS1220 · AD8233 | Señal de ECG en µV, últimos 10 s |
| Pulsómetro y oxímetro | MAX30102 | SpO₂ (%) y pulso (BPM) del oxímetro, más el pulso calculado desde el ECG |
| Pulsómetro | MAX30102 | Onda de pulso infrarroja (cuentas, ~100 por segundo) |
| Presión diferencial | SDP810 | Presión diferencial en Pa (~9 por segundo): sube y baja con cada respiración, para comparar con la frecuencia respiratoria del radar |
| Presión barométrica | BME680 | Presión atmosférica en hPa. Se graba y se muestra como valor; no se grafica en la adquisición |

### Conectar la placa

En la pestaña **Placa CMAE**, botón **Conectar placa**:

| Forma | Qué necesita |
|---|---|
| Bluetooth | Bluetooth en el PC y el número de la placa (el de su nombre `CMAE-N-S3-N16R8`). **Buscar placas cercanas** lista las que están encendidas |
| USB | Cable en la entrada **USB Serial Carga** de la placa (controlador CP210x). Es otro puerto COM que el del ESP32 del radar |
| Simulada | Nada. Inventa datos con el formato real de la placa, para probar sin hardware |

La conexión de la placa es **independiente de la adquisición del radar**: se puede conectar antes, durante o después, y desconectarla no detiene la adquisición. Si se corta el Bluetooth, vuelve a intentar sola hasta presionar **Desconectar**. La última forma de conexión usada se recuerda en `datos/.cmae_config.json`.

### En la adquisición

- **Conectar.** En *Nueva adquisición*, la tarjeta **Placa CMAE** (bajo *Fuente de datos*) tiene el botón **Conectar placa**. Durante la toma, la tarjeta *Placa CMAE* de la columna izquierda también permite conectar o desconectar.
- **Gráficos aparte, sincronizados.** Los de la placa van en una tarjeta propia, a la derecha de la del radar: ECG, pulsómetro (onda de pulso IR del MAX30102), BPM (oxímetro y calculado desde el ECG), SpO₂ y presión diferencial (respiración, SDP810). Usan el mismo eje X que el radar (segundos desde el inicio), la misma ventana, el sombreado de fases, las marcas y la línea del instante actual. El zoom está enlazado: acercar o desplazar una tarjeta mueve también la otra. Al acercar se ve cada latido del ECG y de la onda de pulso. Funciona igual en la vista en vivo y en el Resultado. La tarjeta de la placa siempre usa tiempo; si el radar está en modo Índice, el zoom de cada tarjeta es independiente.
- **Valores actuales.** La tarjeta *Placa CMAE* de la columna izquierda muestra SpO₂, pulso del oxímetro, pulso del ECG y presión barométrica, con los avisos de la placa (*Sin dedo*, *Electrodos desconectados*). Se ven también durante la espera de posicionamiento, para revisar los sensores antes de medir.
- **Grabación.** Las muestras se guardan en `datos/<archivo>_cmae.csv`, junto al CSV del radar. Como en el radar, solo se graban las fases que se graban (no la espera ni la pausa entre mediciones). El Resultado indica el archivo y cuántas muestras tiene. Si la placa se conecta a mitad de la adquisición, se graba desde ese momento.

La placa puede conectarse antes de iniciar la adquisición (recomendado) o durante ella. Desconectarla no detiene la adquisición del radar.

#### Cómo se sincronizan

La placa marca cada muestra con su propio reloj (ms desde que se encendió). El backend estima a qué hora del PC corresponde ese reloj con la trama que llega con menos demora (`RelojPlaca` en `backend/cmae/sincronia.py`), y convierte cada muestra al mismo `t` de la adquisición del radar. Así cada muestra queda en el instante en que la midió la placa, no cuando llegó por Bluetooth. Su medición y su fase se toman de las marcas de fase del radar en ese instante. Desfase medido con la placa simulada: unos 50 ms.

Ten en cuenta que HR y BR del radar llegan con su propio retraso de cálculo (ver *Retraso de los datos*): el ECG y el oxímetro reaccionan antes que el HR del radar.

#### CSV de la placa (`<archivo>_cmae.csv`)

Formato largo, una fila por muestra:

```
timestamp, t, medicion, fase, flag_hold, senal, valor
```

- `timestamp`: hora del PC de la muestra, con milisegundos. `t`: segundos desde el inicio de la adquisición, la misma escala del CSV del radar.
- `medicion`, `fase`, `flag_hold`: los del protocolo en ese instante (`NORMAL`, `PREP`, `HOLD`, `RECOVERY`, `MONITOREO` o `CONTINUO`).
- `senal`: `ECG_uV` (~600 por segundo), `PPG_IR` (onda de pulso, ~100 por segundo), `SPO2_pct`, `BPM_OXIMETRO`, `BPM_ECG`, `PRESION_DIF_Pa` (~9 por segundo) y `PRESION_hPa` (1 por segundo). SpO₂ y BPM solo cuando la placa los da por válidos.

Estos archivos no aparecen solos en la lista de Análisis: acompañan al CSV del radar.

### Pestaña Placa CMAE

Los tres gráficos en grande con el reloj de la placa, sin necesidad de una adquisición, y el estado de la conexión (tramas por segundo, porcentaje de muestras perdidas, cortes). **Corta / Normal / Larga** cambian cuánto tiempo se ve. El punto junto a *Placa CMAE* en el encabezado indica la conexión: verde conectada, ámbar conectando o reconectando, rojo error, gris desconectada.

Cada gráfico tiene un punto de estado (verde si llegan datos, ámbar si dejaron de llegar, rojo si la placa nunca envió datos de ese sensor) y muestra los avisos de la placa: *Electrodos desconectados*, *Sin dedo*, *Calculando…*. No se dibujan los valores de SpO₂ y BPM que la placa marca como no válidos.

> **Pendiente:** la sección Análisis y la exportación de imágenes todavía no leen el CSV de la placa; solo el Resultado de la última adquisición muestra sus gráficos.

### Protocolo

La placa envía tramas binarias `AA 55 | versión | cantidad | reloj u32 | paquetes… | CRC16-CCITT`; cada paquete es `tipo u16 | secuencia u32 | tiempo_ms u32 | largo u16 | contenido`.

- **Bluetooth (BLE):** servicio Nordic UART. Al conectar se escribe `START` en la característica RX (`6E400002-…`) y se reciben notificaciones en TX (`6E400003-…`); al desconectar se envía `STOP`. Cada trama llega partida en fragmentos `CB 1E` que se rearman y validan con CRC. Las señales rápidas (ECG, PPG) llegan en bloques de varias muestras (tipos `0x8xxx`).
- **USB:** puerto COM a 921600 baudios; las tramas se buscan en el flujo de bytes y se validan con CRC.

El código viene del dashboard CMAE y está en `backend/cmae/` (`protocolo.py`, `conexion.py`, `en_vivo.py`, `simulador.py`, `pulso_ecg.py`). Si se corrige allá, se vuelve a copiar; `en_vivo.py` tiene un único cambio propio (la lista de series que se envían), marcado al comienzo. `servicio.py` es lo que conecta todo con este dashboard y `sincronia.py` lleva la placa a la escala de tiempo de la adquisición. En la interfaz, `frontend/src/cmae/` trae `LiveChart.jsx`, `LiveValue.jsx`, `store.js` y `clock.js` del dashboard CMAE; las curvas no pasan por el estado de React.

---

## Sección Análisis

Sirve para revisar mediciones ya guardadas, incluidas las antiguas, sin hacer una adquisición nueva.

- **Archivos:** lista los CSV de `datos/` del más reciente al más antiguo, con fecha y tamaño. Al hacer clic en uno se abre. **Actualizar** vuelve a leer la carpeta. **Subir CSV desde el equipo** abre un archivo de otra carpeta; no se copia a `datos/`.
- **Formato:** se detecta solo. Se leen los CSV de secuencia (`MEDICION20SEQRES.py`), de apnea + monitoreo (formato de secuencia con fase `MONITOREO`) y de captura continua (`tomadatosSEPT.py`), también los antiguos sin columna `marker`.
- **Archivo abierto:** nombre, origen, formato, filas, mediciones (y cuántas están completas), duración y hora de inicio.
- **Gráficos y resumen por fase:** los mismos del Resultado de una adquisición: selector de medición, eje en muestras o en segundos, sombreado de fases, marcas y filtro Savitzky-Golay. El resumen por fase está disponible para archivos de secuencia y de apnea + monitoreo.
- **Exportar imágenes:** genera un PNG por medición del archivo abierto y lo descarga como `graficos_<archivo>.zip`.

Si el archivo elegido es el que se está grabando, se muestra lo guardado hasta el momento de abrirlo. Mientras hay una adquisición en curso, un indicador arriba muestra su estado y permite volver a ella.

---

## Formatos de CSV

### Secuencia con retención y apnea + monitoreo (formato largo)

Una fila por línea recibida, más filas de marca de fase:

```
timestamp, medicion, fase, condicion, flag_hold, tipo, valor_1, valor_2, valor_3, valor_4, valor_5
```

- `timestamp`: fecha y hora ISO del PC con milisegundos.
- `tipo`: `START`, `PHASE` (inicio de fase), `END` (fin de medición), `HR`, `BR`, `DIST`, `EVENT`, `BW` o `MARK` (marca del operador).
- `valor_1`: valor de `HR`, `BR`, `DIST`, texto de `EVENT` o etiqueta de `MARK`.
- `valor_1` a `valor_5`: las 5 muestras de `BW`.

### Captura continua (formato ancho)

Una fila por línea recibida, con el último valor conocido de cada parámetro:

```
timestamp, datetime, HR, BR, distance, movement, raw, marker
```

- `timestamp`: segundos desde el inicio de la adquisición.
- `datetime`: fecha y hora ISO del PC.
- `raw`: línea original recibida (de aquí se recupera la waveform `BW`). En una marca del operador es `MARK,<etiqueta>`.
- `marker`: etiqueta de la marca en esa fila; vacío en las demás.

La secuencia conserva el formato de los scripts originales: `HRBRWF.py` filtra por `tipo`, así que ignora las filas `MARK`. La captura continua agrega la columna `marker` al final. Los CSV antiguos, sin marcas, se siguen leyendo.

---

## API del backend

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/ports` | Puertos seriales detectados |
| GET / PUT | `/api/config` | Configuración guardada (PUT acepta cambios parciales) |
| GET | `/api/files` | CSV de `datos/`, del más reciente al más antiguo |
| GET | `/api/files/{nombre}` | Abre un CSV de `datos/` para Análisis: registros, distancia, resumen por fase y una `key` para exportar |
| POST | `/api/analysis/upload?name=archivo.csv` | Igual, con el CSV en el cuerpo de la petición (hasta 200 MB) |
| POST | `/api/analysis/export?key=…&dpi=300` | Genera el ZIP de imágenes del archivo abierto en Análisis (mismos parámetros que `/api/export`) |
| GET | `/api/acquisition` | Estado de la adquisición actual |
| POST | `/api/acquisition` | Inicia una adquisición: `{config, filename}`. 400 si hay un campo inválido; 409 si ya hay una en curso |
| POST | `/api/acquisition/stop` | Detiene la adquisición |
| POST | `/api/acquisition/confirm` | Confirma la posición en la fase de espera |
| POST | `/api/acquisition/marker` | Agrega una marca; 409 fuera de las fases que se graban |
| GET | `/api/acquisition/last` | Resultado de la última adquisición terminada |
| GET | `/api/acquisition/summary` | Resumen por fase |
| POST | `/api/export?dpi=300&sg_window=0.8&sg_order=2` | Genera y devuelve `graficos_mediciones.zip` |
| GET | `/api/features` | Funciones opcionales activas: `{cmae: true \| false}` |
| GET | `/api/cmae/estado` | Placa CMAE: conexión, sensores y avisos |
| GET | `/api/cmae/puertos` | Puertos COM; marca el que parece ser la placa |
| POST | `/api/cmae/ble/buscar` | Placas CMAE cercanas por Bluetooth (5 s) |
| POST | `/api/cmae/conectar` | `{origen: "ble" \| "uart" \| "simulada", numero, puerto, formato}`. 409 si ya está conectada |
| POST | `/api/cmae/desconectar` | Desconecta la placa |
| GET / PUT | `/api/cmae/config` | Última forma de conexión usada |
| WS | `/ws/cmae` | Catálogo de series y estado (JSON, 2 por segundo) y curvas nuevas (binario, ~30 por segundo) |
| WS | `/ws/live` | Al conectarse envía el historial completo; después, apenas llegan datos nuevos o cambia la fase (y al menos una vez por segundo), el estado y solo los datos nuevos. Incluye `cmae` (`{señal: [[t…], [valor…]]}`) con las muestras de la placa en la escala de la adquisición, y `status.cmae` con su CSV |

La variable de entorno `MMWAVE_DATA_DIR` cambia la carpeta de datos (por defecto `datos/`), lo que sirve para hacer pruebas sin tocar los datos reales.

---

## Diferencias con los scripts originales

- El sensor se lee **continuamente** en un hilo aparte. En los scripts originales, los datos que llegaban durante el `input()` o la cuenta regresiva quedaban acumulados en el buffer serial y se guardaban después con la etiqueta de la fase siguiente (por ejemplo, datos de la preparación como retención). Ahora los datos de la preparación quedan etiquetados como `PREP` y los de las esperas no se guardan.
- La captura continua escribe cada línea en el CSV **al recibirla** (el script original guardaba todo al final), por lo que no se pierden datos si el programa se interrumpe.
- Las duraciones y el número de mediciones se configuran desde la interfaz, sin editar el código.
- Los archivos se guardan en `datos/` con fecha y hora en el nombre y no se sobrescriben.

## Limitaciones conocidas

- Solo se ejecuta una adquisición a la vez (compartida entre pestañas del navegador). El backend debe correr con un solo proceso (`uvicorn` sin `--workers`).
- La interfaz nueva se ha probado con el simulador y con fuentes de prueba, **todavía no con el radar real**.
- No se ha validado aún con el radar real la unidad de `DIST` ni la escala de `BW`.
- HR y BR son estimaciones internas del sensor; no se dispone de la señal de fase cruda del radar ni de una waveform cardíaca.
