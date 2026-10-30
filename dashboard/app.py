# ============================================================
# DASHBOARD MR60BHA1 (radar mmWave 60 GHz)
#
# Ejecutar desde la raíz del repositorio:
#   streamlit run dashboard/app.py
# ============================================================

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from acquisition import (
    AcquisitionManager,
    ContinuousProtocol,
    RetentionProtocol,
    SerialSource,
    SimulatedSource,
    list_serial_ports,
)
from data_io import (
    FORMATO_CONTINUO,
    FORMATO_SECUENCIA,
    load_csv,
    phase_summary,
    records_to_long,
)
from plots import X_INDICE, X_TIEMPO, export_zip, figure_hrbrwf

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "datos"

PROTO_SECUENCIA = "Secuencia con retención (MEDICION20SEQRES)"
PROTO_CONTINUO = "Captura continua (tomadatosSEPT)"

FUENTE_SERIAL = "Puerto serial (ESP32)"
FUENTE_SIMULADOR = "Simulador (sin hardware)"

VENTANA_MEDICION = "Medición actual"
VENTANA_60S = "Últimos 60 s"
VENTANA_TODO = "Todo"

PHASE_COLORS = {
    "ESPERA": "#7f8c8d",
    "NORMAL": "#27ae60",
    "PREP": "#e67e22",
    "HOLD": "#c0392b",
    "RECOVERY": "#2980b9",
    "PAUSA": "#7f8c8d",
    "CONTINUO": "#27ae60",
    "FIN": "#34495e",
}

st.set_page_config(page_title="Dashboard mmWave MR60BHA1", page_icon="📡", layout="wide")


@st.cache_resource
def get_manager() -> AcquisitionManager:
    return AcquisitionManager()


@st.cache_data(show_spinner="Cargando CSV...")
def cached_load(data: bytes):
    return load_csv(data)


def fmt_value(value, unit: str = "", decimals: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    return f"{value:.{decimals}f}{unit}"


# ============================================================
# VISUALIZACIÓN DE RESULTADOS (compartida)
# ============================================================

def render_analysis(long, fmt: str, key: str) -> None:
    if long.empty:
        st.info("No hay datos para graficar.")
        return

    mediciones = [int(m) for m in sorted(long["medicion"].dropna().unique())]

    c1, c2, c3 = st.columns([1, 2, 1])
    seleccion = "Todas"
    if fmt == FORMATO_SECUENCIA and mediciones:
        seleccion = c1.selectbox("Medición", ["Todas", *mediciones], index=1, key=f"{key}_med")
    x_mode = c2.radio("Eje X", [X_INDICE, X_TIEMPO], horizontal=True, key=f"{key}_x")
    show_phases = c3.checkbox(
        "Sombrear fases", value=True, key=f"{key}_fases",
        disabled=x_mode != X_TIEMPO or fmt != FORMATO_SECUENCIA,
    )

    if seleccion == "Todas":
        datos = long
        titulo = "Todas las mediciones — MR60BHA1" if fmt == FORMATO_SECUENCIA else "Captura continua — MR60BHA1"
    else:
        datos = long[long["medicion"] == seleccion]
        titulo = f"Medición {seleccion} — MR60BHA1"

    fig = figure_hrbrwf(datos, titulo, x_mode=x_mode, show_phases=show_phases)
    st.plotly_chart(fig, width="stretch", theme=None, key=f"{key}_chart")

    if fmt == FORMATO_SECUENCIA:
        summary = phase_summary(long)
        if not summary.empty:
            st.subheader("Resumen HR / BR por medición y fase")
            st.dataframe(summary, width="stretch")

    st.subheader("Exportar imágenes")
    st.caption("Genera una imagen PNG por medición con el mismo estilo de HRBRWF.py (medicion_XX.png).")
    e1, e2 = st.columns([1, 3])
    dpi = e1.number_input("DPI", min_value=72, max_value=600, value=300, step=50, key=f"{key}_dpi")
    zip_key = f"{key}_zip"
    if e2.button("Generar imágenes", key=f"{key}_gen"):
        with st.spinner("Generando imágenes..."):
            st.session_state[zip_key] = export_zip(long, int(dpi))
    if zip_key in st.session_state:
        st.download_button(
            "Descargar ZIP", st.session_state[zip_key],
            file_name="graficos_mediciones.zip", mime="application/zip", key=f"{key}_dl",
        )


# ============================================================
# ADQUISICIÓN: CONFIGURACIÓN
# ============================================================

def render_config(manager: AcquisitionManager) -> None:
    stamp = st.session_state.setdefault("stamp", datetime.now().strftime("%Y%m%d_%H%M%S"))

    col_fuente, col_proto = st.columns(2)

    with col_fuente:
        st.subheader("Fuente de datos")
        fuente = st.radio("Fuente", [FUENTE_SERIAL, FUENTE_SIMULADOR], key="fuente", label_visibility="collapsed")
        port, baudrate = None, 115200
        if fuente == FUENTE_SERIAL:
            ports = list_serial_ports()
            p1, p2 = st.columns([3, 1])
            if ports:
                port = p1.selectbox("Puerto", ports, key="puerto")
            else:
                port = p1.text_input("Puerto", "COM4", key="puerto_manual")
                st.caption("No se detectaron puertos. Escribe el puerto manualmente.")
            p2.button("Actualizar", help="Volver a buscar puertos")
            baudrate = st.number_input("Baudrate", value=115200, step=9600, key="baudrate")
        else:
            st.caption("Genera datos sintéticos de HR, BR, distancia, eventos y waveform BW para probar el dashboard.")

    with col_proto:
        st.subheader("Protocolo")
        proto = st.radio("Protocolo", [PROTO_SECUENCIA, PROTO_CONTINUO], key="protocolo", label_visibility="collapsed")

        if proto == PROTO_SECUENCIA:
            a, b, c = st.columns(3)
            n_med = a.number_input("Mediciones", 1, 200, 20, key="n_med")
            t_normal = b.number_input("Respiración normal (s)", 1, 600, 20, key="t_normal")
            t_hold = c.number_input("Retención (s)", 1, 120, 10, key="t_hold")
            d, e, f = st.columns(3)
            t_recovery = d.number_input("Descanso (s)", 1, 600, 30, key="t_recovery")
            t_countdown = e.number_input("Cuenta regresiva", 0, 10, 3, key="t_countdown")
            t_pausa = f.number_input("Pausa entre mediciones (s)", 0, 60, 3, key="t_pausa")
            esperar = st.checkbox(
                "Esperar confirmación antes de cada medición", value=True, key="esperar",
                help="Equivale al 'Presiona ENTER' del script original.",
            )
            protocol = RetentionProtocol(
                n_mediciones=int(n_med), t_normal=t_normal, t_hold=t_hold,
                t_recovery=t_recovery, t_countdown=int(t_countdown),
                t_pausa=t_pausa, esperar_usuario=esperar,
            )
            default_name = f"MR60BHA1_mediciones_{stamp}.csv"
            st.info(
                "Durante la retención realiza solamente un aguante voluntario y cómodo. "
                "No fuerces la respiración."
            )
        else:
            duracion = st.number_input("Duración (s, 0 = hasta detener)", 0, 36000, 0, key="duracion")
            protocol = ContinuousProtocol(duracion=float(duracion) or None)
            default_name = f"MR60BHA1_experimento_{stamp}.csv"

    st.subheader("Archivo de salida")
    nombre = st.text_input(
        f"Se guardará en {DATA_DIR}", value=default_name, key=f"archivo_{proto}_{stamp}",
    ).strip()
    if not nombre.lower().endswith(".csv"):
        nombre += ".csv"
    output_path = DATA_DIR / nombre

    if st.button("Iniciar adquisición", type="primary"):
        if output_path.exists():
            st.error(f"El archivo {output_path.name} ya existe. Elige otro nombre.")
            return
        if fuente == FUENTE_SERIAL:
            if not port:
                st.error("Selecciona un puerto serial.")
                return
            factory = lambda: SerialSource(port, int(baudrate))
        else:
            factory = SimulatedSource
        manager.start(factory, protocol, output_path)
        del st.session_state["stamp"]
        st.rerun()


# ============================================================
# ADQUISICIÓN: VISTA EN VIVO
# ============================================================

def render_banner(status) -> None:
    color = PHASE_COLORS.get(status.fase, "#34495e")
    detalle = ""
    if status.cuenta is not None:
        detalle = f"<div style='font-size:4rem;font-weight:800'>{status.cuenta}</div>"
    elif status.fase_fin is not None:
        restante = max(0, status.fase_fin - time.monotonic())
        detalle = f"<div style='font-size:2.2rem;font-weight:600'>{restante:0.0f} s</div>"
    encabezado = f"MEDICIÓN {status.medicion}/{status.total}" if status.total else "&nbsp;"
    st.markdown(
        f"""
        <div style="background:{color};color:white;border-radius:14px;padding:18px 24px;text-align:center">
          <div style="font-size:1rem;letter-spacing:.15em;opacity:.85">{encabezado}</div>
          <div style="font-size:2.4rem;font-weight:800">{status.estado}</div>
          {detalle}
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every=1.0)
def live_panel() -> None:
    session = get_manager().session
    if session is None:
        return
    status = session.status
    if status.terminado:
        st.rerun()

    if status.error:
        st.error(status.error)

    render_banner(status)

    if status.esperando_usuario:
        st.button(
            f"Estoy en posición — comenzar medición {status.medicion}",
            on_click=session.confirm_ready, type="primary", width="stretch", key="btn_listo",
        )

    if status.total:
        avance = (status.medicion - (0 if status.fase in ("PAUSA", "FIN") else 1)) / status.total
        st.progress(min(max(avance, 0.0), 1.0))

    records, latest = session.snapshot()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("HR", fmt_value(latest["HR"], " BPM"))
    m2.metric("BR", fmt_value(latest["BR"], " resp/min"))
    m3.metric("Distancia", fmt_value(latest["DIST"], "", 1))
    m4.metric("Evento", fmt_value(latest["EVENT"]))
    m5.metric("Líneas recibidas / guardadas", f"{session.n_lines} / {session.n_saved}")

    long = records_to_long(records)
    ventana = st.session_state.get("live_ventana", VENTANA_MEDICION)
    if not long.empty:
        if ventana == VENTANA_MEDICION and status.medicion:
            long = long[long["medicion"] == status.medicion]
        elif ventana == VENTANA_60S:
            long = long[long["t"] >= long["t"].max() - 60]

    titulo = f"Medición {status.medicion} — MR60BHA1" if status.total else "Captura continua — MR60BHA1"
    fig = figure_hrbrwf(
        long, titulo,
        x_mode=st.session_state.get("live_x", X_TIEMPO),
        show_phases=st.session_state.get("live_fases", True),
    )
    st.plotly_chart(fig, width="stretch", theme=None, key="live_chart")


def render_live(manager: AcquisitionManager) -> None:
    session = manager.session
    c1, c2 = st.columns([4, 1])
    c1.markdown(
        f"**{session.protocol.nombre}** · archivo `{session.output_path.name}` · "
        f"iniciado {session.started_at:%H:%M:%S}"
    )
    c2.button("Detener adquisición", on_click=session.stop, type="secondary", width="stretch")

    o1, o2, o3 = st.columns([2, 2, 1])
    o1.radio("Eje X", [X_TIEMPO, X_INDICE], horizontal=True, key="live_x")
    o2.radio("Ventana", [VENTANA_MEDICION, VENTANA_60S, VENTANA_TODO], horizontal=True, key="live_ventana")
    o3.checkbox("Sombrear fases", value=True, key="live_fases")

    live_panel()


def render_last_session(manager: AcquisitionManager) -> None:
    session = manager.session
    status = session.status
    st.divider()
    st.subheader("Última adquisición")
    if status.error:
        st.error(status.error)
    elif status.detenido:
        st.warning(status.estado)
    else:
        st.success(status.estado)
    st.markdown(f"Archivo: `{session.output_path}` · registros guardados: **{session.n_saved}**")

    records, _ = session.snapshot()
    fmt = FORMATO_SECUENCIA if session.protocol.n_mediciones else FORMATO_CONTINUO
    render_analysis(records_to_long(records), fmt, key="last")


def page_acquisition() -> None:
    st.title("📡 Adquisición MR60BHA1")
    manager = get_manager()
    if manager.busy:
        render_live(manager)
    else:
        render_config(manager)
        if manager.session is not None:
            render_last_session(manager)


# ============================================================
# ANÁLISIS DE ARCHIVOS
# ============================================================

def page_analysis() -> None:
    st.title("📈 Análisis de mediciones")

    origen = st.radio("Origen", ["Carpeta datos/", "Subir archivo"], horizontal=True)
    data, nombre = None, None
    if origen == "Carpeta datos/":
        files = sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            st.info(f"No hay archivos CSV en {DATA_DIR}.")
            return
        path = st.selectbox("Archivo", files, format_func=lambda p: p.name)
        data, nombre = path.read_bytes(), path.name
    else:
        upload = st.file_uploader("Archivo CSV", type="csv")
        if upload is None:
            return
        data, nombre = upload.getvalue(), upload.name

    try:
        fmt, raw, long = cached_load(data)
    except Exception as exc:
        st.error(f"No se pudo leer {nombre}: {exc}")
        return

    etiqueta = PROTO_SECUENCIA if fmt == FORMATO_SECUENCIA else PROTO_CONTINUO
    st.caption(f"{nombre} · formato: {etiqueta} · {len(raw)} filas")

    render_analysis(long, fmt, key=f"an_{nombre}")

    with st.expander("Datos crudos"):
        st.dataframe(raw, width="stretch")


# ============================================================
# NAVEGACIÓN
# ============================================================

with st.sidebar:
    st.header("Dashboard mmWave")
    pagina = st.radio("Sección", ["Adquisición", "Análisis"])
    if get_manager().busy:
        st.success("● Adquisición en curso")

if pagina == "Adquisición":
    page_acquisition()
else:
    page_analysis()
