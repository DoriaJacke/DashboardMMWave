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
    pbm_path_for,
)
from cmae_conexion import Estado, PlacaCMAE, nombre_ble
from cmae_protocolo import Lectura
from data_io import (
    FORMATO_CONTINUO,
    FORMATO_SECUENCIA,
    load_csv,
    pbm_records_to_frame,
    phase_summary,
    records_to_long,
)
from plots import (
    X_INDICE,
    X_TIEMPO,
    DistanceZone,
    SavgolConfig,
    export_zip,
    extract_series,
    figure_distance_gauge,
    figure_distance_trend,
    figure_hrbrwf,
    figure_pbm,
    figure_ppg,
    savgol_window,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "datos"

PROTO_SECUENCIA = "Secuencia con retención "
PROTO_CONTINUO = "Captura continua "

FUENTE_SERIAL = "Puerto serial (ESP32)"
FUENTE_SIMULADOR = "Simulador (sin hardware)"

PLACA_REAL = "Placa real (Bluetooth)"
PLACA_SIMULADA = "Placa simulada (sin hardware)"

VENTANA_MEDICION = "Medición actual"
VENTANA_60S = "Últimos 60 s"
VENTANA_TODO = "Todo"

DIST_STALE_S = 5.0

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


@st.cache_resource
def get_placa() -> PlacaCMAE:
    return PlacaCMAE()


@st.cache_data(show_spinner="Cargando CSV...")
def cached_load(data: bytes):
    return load_csv(data)


def fmt_value(value, unit: str = "", decimals: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    return f"{value:.{decimals}f}{unit}"


def bpm_texto(lectura: Lectura | None) -> str:
    return f"{lectura.bpm:.0f} BPM" if lectura is not None and lectura.bpm_ok else "—"


def spo2_texto(lectura: Lectura | None) -> str:
    return f"{lectura.spo2:.0f} %" if lectura is not None and lectura.spo2_ok else "—"


def lectura_aviso(lectura: Lectura | None) -> str | None:
    """Por qué no hay BPM/SpO2 que mostrar, o None si los hay."""
    if lectura is None:
        return "Sin datos recientes de la placa."
    if not lectura.dedo:
        return "Sin dedo en el sensor MAX30102."
    if not (lectura.bpm_ok and lectura.spo2_ok):
        return "Calculando BPM y SpO2, mantén el dedo quieto."
    return None


# ============================================================
# VISUALIZACIÓN DE RESULTADOS (compartida)
# ============================================================

def savgol_controls(key: str) -> SavgolConfig | None:
    s1, s2, s3 = st.columns([1, 2, 1])
    activo = s1.checkbox("Filtro Savitzky-Golay en BW", value=False, key=f"{key}_sg")
    ventana = s2.slider(
        "Ventana (s)", 0.1, 3.0, 0.8, 0.1, key=f"{key}_sg_ventana", disabled=not activo,
        help="Debe ser bastante menor que un ciclo respiratorio (~2-6 s).",
    )
    orden = s3.selectbox("Orden del polinomio", [2, 3, 4, 5], key=f"{key}_sg_orden", disabled=not activo)
    return SavgolConfig(ventana_s=ventana, orden=orden) if activo else None


def savgol_caption(datos, savgol: SavgolConfig) -> None:
    wave_t = extract_series(datos).wave_t
    if len(wave_t) < 2:
        return
    dt, window = savgol_window(wave_t, savgol)
    st.caption(
        f"Muestreo BW estimado: {1 / dt:.1f} Hz → ventana de {window} muestras "
        f"({window * dt:.2f} s), polinomio de orden {savgol.orden}. "
        "Se filtra cada tramo continuo por separado; los datos guardados no se modifican."
    )


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

    savgol = savgol_controls(key)

    if seleccion == "Todas":
        datos = long
        titulo = "Todas las mediciones — MR60BHA1" if fmt == FORMATO_SECUENCIA else "Captura continua — MR60BHA1"
    else:
        datos = long[long["medicion"] == seleccion]
        titulo = f"Medición {seleccion} — MR60BHA1"

    if savgol is not None:
        savgol_caption(datos, savgol)

    fig = figure_hrbrwf(datos, titulo, x_mode=x_mode, show_phases=show_phases, savgol=savgol)
    st.plotly_chart(fig, width="stretch", theme=None, key=f"{key}_chart")

    if fmt == FORMATO_SECUENCIA:
        summary = phase_summary(long)
        if not summary.empty:
            st.subheader("Resumen HR / BR / distancia por medición y fase")
            st.dataframe(summary, width="stretch")

    st.subheader("Exportar imágenes")
    st.caption(
        "Genera una imagen PNG por medición con el mismo estilo de HRBRWF.py (medicion_XX.png). "
        "Si el filtro Savitzky-Golay está activo, la onda filtrada se superpone también en las imágenes."
    )
    e1, e2 = st.columns([1, 3])
    dpi = e1.number_input("DPI", min_value=72, max_value=600, value=300, step=50, key=f"{key}_dpi")
    zip_key = f"{key}_zip"
    if e2.button("Generar imágenes", key=f"{key}_gen"):
        with st.spinner("Generando imágenes..."):
            st.session_state[zip_key] = export_zip(long, int(dpi), savgol)
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

    render_placa_config()

    st.subheader("Archivo de salida")
    nombre = st.text_input(
        f"Se guardará en {DATA_DIR}", value=default_name, key=f"archivo_{proto}_{stamp}",
    ).strip()
    if not nombre.lower().endswith(".csv"):
        nombre += ".csv"
    output_path = DATA_DIR / nombre
    pbm_path = pbm_path_for(output_path)
    st.caption(f"Si la placa CMAE está conectada al iniciar, sus lecturas se guardarán en `{pbm_path.name}`.")

    if st.button("Iniciar adquisición", type="primary"):
        if output_path.exists():
            st.error(f"El archivo {output_path.name} ya existe. Elige otro nombre.")
            return
        placa = get_placa()
        placa_sesion = placa if placa.disponible else None
        if placa_sesion is not None and pbm_path.exists():
            st.error(f"El archivo {pbm_path.name} ya existe. Elige otro nombre.")
            return
        if fuente == FUENTE_SERIAL:
            if not port:
                st.error("Selecciona un puerto serial.")
                return
            factory = lambda: SerialSource(port, int(baudrate))
        else:
            factory = SimulatedSource
        manager.start(factory, protocol, output_path, placa_sesion)
        del st.session_state["stamp"]
        st.rerun()


# ============================================================
# PLACA BIOMÉDICA CMAE: CONEXIÓN
# ============================================================

def render_placa_config() -> None:
    placa = get_placa()
    st.subheader("Placa biomédica CMAE (opcional)")
    fuente = st.radio(
        "Fuente de la placa", [PLACA_REAL, PLACA_SIMULADA], key="placa_fuente",
        horizontal=True, label_visibility="collapsed", disabled=placa.activa,
    )
    c1, c2 = st.columns([1, 3])
    if placa.activa:
        c1.markdown(f"**{placa.nombre.capitalize()}**")
        c2.button("Desconectar placa", on_click=placa.desconectar, key="placa_desconectar")
    elif fuente == PLACA_SIMULADA:
        c1.caption("Genera BPM, SpO2 y onda PPG sintéticos para ver el dashboard sin la placa.")
        c2.button("Conectar placa", on_click=placa.conectar, args=(0, True), key="placa_conectar")
    else:
        numero = int(c1.number_input("Número de dispositivo", min_value=1, max_value=99, value=1, step=1, key="placa_numero"))
        c2.button("Conectar placa", on_click=placa.conectar, args=(numero, False), key="placa_conectar")
        c2.caption(f"Se buscará {nombre_ble(numero)} por Bluetooth.")
    placa_estado_panel()


@st.fragment(run_every=1.0)
def placa_estado_panel() -> None:
    placa = get_placa()
    estado = placa.estado
    # Si el estado cambió (por ejemplo terminó de conectar), se redibuja la página
    # completa para que el botón Conectar/Desconectar quede al día.
    if st.session_state.get("placa_estado_visto", estado) != estado:
        st.session_state.placa_estado_visto = estado
        st.rerun()
    st.session_state.placa_estado_visto = estado

    if estado == Estado.CONECTADA:
        lectura = placa.ultima()
        st.success(f"Conectada a {placa.detalle}. Al iniciar, sus lecturas se guardarán junto a las del radar.")
        st.caption(
            f"Ahora: {bpm_texto(lectura)} · SpO2 {spo2_texto(lectura)} · tramas recibidas: {placa.tramas_ok}"
            + (f" · {lectura_aviso(lectura)}" if lectura_aviso(lectura) else "")
        )
    elif estado == Estado.RECONECTANDO:
        st.warning(f"Se perdió la conexión con la placa. {placa.detalle}")
    elif estado in (Estado.CONECTANDO, Estado.DESCONECTANDO):
        st.info(placa.detalle or f"{estado.value}...")
    elif estado == Estado.ERROR:
        st.error(f"Error de conexión. {placa.detalle}")
        st.caption("Sin placa, la adquisición será solo del radar.")
    else:
        st.info("Sin placa conectada: la adquisición será solo del radar.")


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


def distance_controls() -> DistanceZone:
    with st.expander("Medidor de distancia: zona adecuada"):
        d1, d2, d3, d4 = st.columns(4)
        unidad = d4.text_input("Unidad", "cm", key="dist_unidad",
                               help="Según el protocolo de Seeed el MR60BHA1 entrega cm (por confirmar).")
        minimo = d1.number_input(f"Mínimo ({unidad})", 0.0, 1000.0, 40.0, 5.0, key="dist_min")
        maximo = d2.number_input(f"Máximo ({unidad})", 0.0, 1000.0, 150.0, 5.0, key="dist_max")
        escala = d3.number_input(f"Escala del medidor ({unidad})", 10.0, 2000.0, 300.0, 10.0, key="dist_escala")
    return DistanceZone(minimo=minimo, maximo=max(maximo, minimo), escala=max(escala, maximo), unidad=unidad)


@st.fragment(run_every=1.0)
def live_panel(savgol: SavgolConfig | None, zone: DistanceZone) -> None:
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
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("HR", fmt_value(latest["HR"], " BPM"))
    m2.metric("BR", fmt_value(latest["BR"], " resp/min"))
    m3.metric("Evento", fmt_value(latest["EVENT"]))
    m4.metric("Líneas recibidas / guardadas", f"{session.n_lines} / {session.n_saved}")

    distancia, edad, historial = session.distance_snapshot()
    stale = edad is not None and edad > DIST_STALE_S
    g1, g2 = st.columns([2, 3])
    g1.plotly_chart(figure_distance_gauge(distancia, zone, stale), width="stretch",
                    theme=None, key="live_dist_gauge")
    g2.plotly_chart(figure_distance_trend(historial, zone), width="stretch",
                    theme=None, key="live_dist_trend")
    if distancia is None:
        st.caption("El radar aún no ha enviado datos de distancia (líneas `DIST,<valor>`).")

    long = records_to_long(records)
    pbm = pbm_records_to_frame(session.snapshot_pbm()) if session.placa is not None else None
    ventana = st.session_state.get("live_ventana", VENTANA_MEDICION)
    if not long.empty:
        if ventana == VENTANA_MEDICION and status.medicion:
            long = long[long["medicion"] == status.medicion]
        elif ventana == VENTANA_60S:
            long = long[long["t"] >= long["t"].max() - 60]
    if pbm is not None and not pbm.empty:
        if ventana == VENTANA_MEDICION and status.medicion:
            pbm = pbm[pbm["medicion"] == status.medicion]
        elif ventana == VENTANA_60S:
            pbm = pbm[pbm["t"] >= pbm["t"].max() - 60]

    x_mode = st.session_state.get("live_x", X_TIEMPO)
    show_phases = st.session_state.get("live_fases", True)
    # Con placa, los dos gráficos usan el mismo rango de tiempo para compararlos.
    x_range = shared_time_range(long, pbm) if pbm is not None and x_mode == X_TIEMPO else None

    titulo = f"Medición {status.medicion} — MR60BHA1" if status.total else "Captura continua — MR60BHA1"
    fig = figure_hrbrwf(
        long, titulo,
        x_mode=x_mode,
        show_phases=show_phases,
        savgol=savgol,
        x_range=x_range,
    )
    st.plotly_chart(fig, width="stretch", theme=None, key="live_chart")

    if session.placa is not None:
        render_pbm_live(session, pbm, long, x_mode, show_phases, x_range)
    else:
        st.caption("Esta adquisición no incluye la placa CMAE.")


def shared_time_range(long, pbm) -> tuple[float, float] | None:
    tiempos = [df["t"].dropna() for df in (long, pbm) if df is not None and not df.empty]
    tiempos = [t for t in tiempos if not t.empty]
    if not tiempos:
        return None
    lo = min(float(t.min()) for t in tiempos)
    hi = max(float(t.max()) for t in tiempos)
    return (lo, hi) if hi > lo else None


def titulo_placa(session) -> str:
    return "Placa biomédica CMAE — simulada" if session.placa_simulada else "Placa biomédica CMAE"


def render_pbm_live(session, pbm, phases_df, x_mode: str, show_phases: bool, x_range) -> None:
    placa = session.placa
    st.subheader(titulo_placa(session))
    if placa.estado == Estado.RECONECTANDO:
        st.warning(
            "Se perdió la conexión con la placa y se está reconectando sola. "
            f"Mientras tanto no se guardan sus lecturas; el radar sigue grabando. {placa.detalle}"
        )
    elif placa.estado != Estado.CONECTADA:
        st.warning(f"Placa CMAE: {placa.estado.value.lower()}. Sus lecturas no se están guardando.")

    lectura = placa.ultima()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("BPM placa", bpm_texto(lectura))
    m2.metric("SpO2 placa", spo2_texto(lectura))
    m3.metric("Estado placa", placa.estado.value)
    m4.metric("Lecturas placa guardadas", f"{session.n_pbm}")
    aviso = lectura_aviso(lectura)
    st.caption(
        (f"{aviso} · " if aviso else "")
        + f"Tramas recibidas: {placa.tramas_ok} · descartadas: {placa.tramas_malas} · cortes de conexión: {placa.cortes}"
    )

    fig = figure_pbm(pbm, phases_df, x_mode=x_mode, show_phases=show_phases, x_range=x_range)
    st.plotly_chart(fig, width="stretch", theme=None, key="live_pbm_chart")

    t_ppg, ir = placa.ppg()
    st.plotly_chart(figure_ppg(t_ppg, ir), width="stretch", theme=None, key="live_ppg_chart")


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

    zone = distance_controls()
    live_panel(savgol_controls("live"), zone)


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

    if session.placa is not None:
        st.subheader(titulo_placa(session))
        st.markdown(f"Archivo: `{session.pbm_path}` · lecturas guardadas: **{session.n_pbm}**")
        fig = figure_pbm(
            pbm_records_to_frame(session.snapshot_pbm()), records_to_long(records),
            title="BPM y SpO2 de la placa — toda la adquisición", x_mode=X_TIEMPO,
        )
        st.plotly_chart(fig, width="stretch", theme=None, key="last_pbm_chart")


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

@st.fragment(run_every=1.0)
def placa_sidebar() -> None:
    """Estado de la placa en la barra lateral; se refresca solo, también durante la adquisición."""
    placa = get_placa()
    if placa.estado == Estado.CONECTADA:
        st.caption("● Placa CMAE simulada conectada" if placa.simulada else f"● Placa CMAE conectada ({placa.nombre})")
    elif placa.estado == Estado.RECONECTANDO:
        st.caption("● Placa CMAE reconectando")


with st.sidebar:
    st.header("Dashboard mmWave")
    pagina = st.radio("Sección", ["Adquisición", "Análisis"])
    if get_manager().busy:
        st.success("● Adquisición en curso")
    placa_sidebar()

if pagina == "Adquisición":
    page_acquisition()
else:
    page_analysis()
