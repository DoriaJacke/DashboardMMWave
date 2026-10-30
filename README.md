# DashboardMMWave
Dashboard preliminar para proyecto de titulo sobre uso de radar de onda milimetrica para estudio piloto

## Dashboard (Streamlit)

Instalación:

```
pip install -r requirements.txt
```

Ejecución (desde la raíz del repositorio):

```
streamlit run dashboard/app.py
```

### Secciones

- **Adquisición**: lee el ESP32 + MR60BHA1 por puerto serial (o un simulador sin hardware) con uno de dos protocolos:
  - *Secuencia con retención* (`MEDICION20SEQRES.py`): N mediciones de respiración normal → preparación con cuenta regresiva → retención → descanso. Genera el CSV en formato largo (`timestamp, medicion, fase, condicion, flag_hold, tipo, valor_1..valor_5`).
  - *Captura continua* (`tomadatosSEPT.py`): registra hasta que se detiene (o por una duración fija). Genera el CSV con columnas `timestamp, datetime, HR, BR, distance, movement, raw`.
- **Análisis**: abre CSV de la carpeta `datos/` o subidos, grafica Waveform BW, HR y BR (estilo `HRBRWF.py`), muestra un resumen de HR/BR por medición y fase, y exporta un PNG por medición en un ZIP.

Los archivos se guardan en `datos/`.

### Estructura

- `dashboard/app.py`: interfaz Streamlit.
- `dashboard/acquisition.py`: fuentes de datos, sesión de adquisición en segundo plano y protocolos.
- `dashboard/data_io.py`: lectura de CSV y resúmenes por fase.
- `dashboard/plots.py`: gráficos (Plotly interactivo y exportación Matplotlib).
