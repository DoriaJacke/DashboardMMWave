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
│   └── plots.py               Filtro Savitzky-Golay y exportación de imágenes PNG
├── frontend/                  Interfaz (Vite + React + React-Bootstrap)
│   └── src/
│       ├── App.jsx            Pantallas y estado general
│       ├── components/        Banner, métricas, distancia, gráficos, resultado…
│       ├── lib/               Conexión en vivo, API, series y cálculos de los gráficos
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
| `HR` | latidos por minuto (BPM) | Valor estimado por el sensor, aprox. uno por segundo. Un 0 significa que no hay estimación |
| `BR` | respiraciones por minuto | Valor estimado por el sensor, aprox. uno por segundo |
| `DIST` | centímetros (según protocolo Seeed, **por confirmar**) | El medidor de distancia asume cm; la unidad se puede cambiar en el dashboard |
| `BW` | sin unidad física (amplitud relativa) | Sirve para forma, ritmo y amplitud relativa de la respiración; según el protocolo Seeed serían valores 0–255 centrados cerca de 128 (**por confirmar**) |
| `EVENT` | texto | Estado categórico |
| `timestamp` | hora del PC al recibir la línea | No es la hora de medición del sensor; puede haber un pequeño desfase por el puerto serial y el `delay(200)` del firmware |

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

> **En Windows, el contenedor no ve los puertos COM.** Sirve para probar el dashboard con el **Simulador**, pero no para medir con el radar: para eso hay que ejecutarlo sin Docker, como se indica arriba. Lo mismo ocurrirá con Bluetooth si se suma la placa CMAE.

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

#### Captura continua (basado en `tomadatosSEPT.py`)

Registra todas las líneas recibidas hasta presionar *Detener adquisición*, o durante una duración fija si se indica (0 = indefinida).

### 3. Archivo de salida

Los CSV se guardan en `datos/` con un nombre por defecto que incluye fecha y hora (`MR60BHA1_mediciones_AAAAMMDD_HHMMSS.csv` o `MR60BHA1_experimento_AAAAMMDD_HHMMSS.csv`). El nombre se puede editar; si el archivo ya existe, el dashboard no lo sobrescribe.

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
  - La zona adecuada (40–150 cm por defecto), la escala del medidor (300 cm) y la unidad se configuran con el botón que muestra la zona actual.
  - Si no llegan datos `DIST` por más de 5 s, el medidor indica *Sin datos recientes*.
- **Gráficos** de waveform BW, HR y BR, con el eje X compartido. El botón de opciones cambia el eje X (*Tiempo* o *Índice de muestra*), la ventana (*Medición actual*, *Últimos 60 s*, *Todo*), el sombreado de fases y el filtro Savitzky-Golay. En *Medición actual* las fases que faltan se ven atenuadas y una línea punteada marca el instante actual.
- **Zoom:** arrastrar sobre un gráfico acerca los tres; doble clic restablece. Los botones ← + − → hacen lo mismo con el teclado o el mouse.
- Botón **Detener adquisición**, en el encabezado.

Si se recarga la página o se abre otra pestaña, se vuelve a ver la adquisición en curso. Si se corta la conexión con el backend, la página avisa y se reconecta sola. Desde la pestaña Análisis, un indicador muestra la adquisición en curso y permite volver a ella.

### 6. Resultado

Al terminar se muestra el estado final (completada, detenida manualmente o con error), la configuración de la siguiente adquisición y:

- **Gráficos** de la adquisición, por medición o todas, por índice de muestra o por tiempo.
- **Resumen por fase:** media, desviación estándar y cantidad de datos de HR, BR y distancia por medición y fase (solo en secuencia).
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

## Sección Análisis

**En construcción.** Se diseña en la siguiente etapa; por ahora solo muestra el indicador de la adquisición en curso. Abrir archivos guardados de `datos/` o subir un CSV todavía no está disponible en esta interfaz. `backend/data_io.py` ya lee los dos formatos, incluidos los CSV antiguos.

---

## Formatos de CSV

### Secuencia con retención (formato largo)

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
| GET | `/api/acquisition` | Estado de la adquisición actual |
| POST | `/api/acquisition` | Inicia una adquisición: `{config, filename}`. 400 si hay un campo inválido; 409 si ya hay una en curso |
| POST | `/api/acquisition/stop` | Detiene la adquisición |
| POST | `/api/acquisition/confirm` | Confirma la posición en la fase de espera |
| POST | `/api/acquisition/marker` | Agrega una marca; 409 fuera de las fases que se graban |
| GET | `/api/acquisition/last` | Resultado de la última adquisición terminada |
| GET | `/api/acquisition/summary` | Resumen por fase |
| POST | `/api/export?dpi=300&sg_window=0.8&sg_order=2` | Genera y devuelve `graficos_mediciones.zip` |
| WS | `/ws/live` | Al conectarse envía el historial completo; después, una vez por segundo o apenas cambia la fase, el estado y solo los datos nuevos |

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
