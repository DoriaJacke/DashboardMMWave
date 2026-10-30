# ============================================================
# VISUALIZACIÓN MR60BHA1
# 20 IMÁGENES × 3 SUBPLOTS
#
# SUBPLOT 1 -> Waveform BW
# SUBPLOT 2 -> HR
# SUBPLOT 3 -> BR
#
# PUNTOS      -> NARANJO
# LÍNEA       -> AZUL
# ============================================================

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_FILE = "MR60BHA1_20mediciones.csv"
OUTPUT_DIR = "graficos_mediciones"

N_MEDICIONES = 20

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# CARGAR DATOS
# ============================================================

df = pd.read_csv(INPUT_FILE)

# ============================================================
# COLUMNAS WAVEFORM
# ============================================================

wave_cols = [
    "valor_1",
    "valor_2",
    "valor_3",
    "valor_4",
    "valor_5"
]

for col in wave_cols:
    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )

# ============================================================
# COLORES
# ============================================================

COLOR_PUNTOS = "orange"
COLOR_LINEA = "blue"

# ============================================================
# PROCESAR CADA MEDICIÓN
# ============================================================

for medicion in range(1, N_MEDICIONES + 1):

    # --------------------------------------------------------
    # DATOS DE LA MEDICIÓN
    # --------------------------------------------------------

    datos = df[
        df["medicion"] == medicion
    ].copy()

    if datos.empty:
        print(
            f"Medición {medicion}: sin datos"
        )
        continue

    # --------------------------------------------------------
    # SEPARAR TIPOS
    # --------------------------------------------------------

    datos_bw = datos[
        datos["tipo"] == "BW"
    ].copy()

    datos_hr = datos[
        datos["tipo"] == "HR"
    ].copy()

    datos_br = datos[
        datos["tipo"] == "BR"
    ].copy()

    # ========================================================
    # WAVEFORM BW
    # ========================================================

    waveform = []

    for _, row in datos_bw.iterrows():

        valores = row[
            wave_cols
        ].values.astype(float)

        valores = valores[
            ~np.isnan(valores)
        ]

        waveform.extend(valores)

    waveform = np.array(waveform)

    # ========================================================
    # HR
    # ========================================================

    hr = datos_hr[
        "valor_1"
    ].dropna().values

    # ========================================================
    # BR
    # ========================================================

    br = datos_br[
        "valor_1"
    ].dropna().values

    # ========================================================
    # CREAR FIGURA
    # ========================================================

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(14, 10)
    )

    # ========================================================
    # 1. WAVEFORM BW
    # ========================================================

    ax = axes[0]

    if len(waveform) > 0:

        x_wave = np.arange(
            len(waveform)
        )

        # Línea azul
        ax.plot(
            x_wave,
            waveform,
            color=COLOR_LINEA,
            linewidth=1.2,
            zorder=1
        )

        # Puntos naranjos
        ax.scatter(
            x_wave,
            waveform,
            color=COLOR_PUNTOS,
            s=12,
            zorder=2
        )

    ax.set_title(
        "Waveform BW",
        fontsize=13,
        fontweight="bold",
        loc="left"
    )

    ax.set_ylabel(
        "BW",
        fontsize=11
    )

    ax.set_xlabel(
        "Índice de muestra de waveform",
        fontsize=10
    )

    ax.grid(
        True,
        alpha=0.25,
        linestyle="--"
    )

    # ========================================================
    # 2. HR
    # ========================================================

    ax = axes[1]

    if len(hr) > 0:

        x_hr = np.arange(
            len(hr)
        )

        # Línea azul
        ax.plot(
            x_hr,
            hr,
            color=COLOR_LINEA,
            linewidth=1.2,
            zorder=1
        )

        # Puntos naranjos
        ax.scatter(
            x_hr,
            hr,
            color=COLOR_PUNTOS,
            s=25,
            zorder=2
        )

    ax.set_title(
        "Frecuencia cardíaca",
        fontsize=13,
        fontweight="bold",
        loc="left"
    )

    ax.set_ylabel(
        "HR (BPM)",
        fontsize=11
    )

    ax.set_xlabel(
        "Índice de muestra",
        fontsize=10
    )

    ax.grid(
        True,
        alpha=0.25,
        linestyle="--"
    )

    # ========================================================
    # 3. BR
    # ========================================================

    ax = axes[2]

    if len(br) > 0:

        x_br = np.arange(
            len(br)
        )

        # Línea azul
        ax.plot(
            x_br,
            br,
            color=COLOR_LINEA,
            linewidth=1.2,
            zorder=1
        )

        # Puntos naranjos
        ax.scatter(
            x_br,
            br,
            color=COLOR_PUNTOS,
            s=25,
            zorder=2
        )

    ax.set_title(
        "Frecuencia respiratoria",
        fontsize=13,
        fontweight="bold",
        loc="left"
    )

    ax.set_ylabel(
        "BR (resp/min)",
        fontsize=11
    )

    ax.set_xlabel(
        "Índice de muestra",
        fontsize=10
    )

    ax.grid(
        True,
        alpha=0.25,
        linestyle="--"
    )

    # ========================================================
    # TÍTULO GENERAL
    # ========================================================

    fig.suptitle(
        f"Medición {medicion} — MR60BHA1",
        fontsize=16,
        fontweight="bold"
    )

    # ========================================================
    # AJUSTAR
    # ========================================================

    plt.tight_layout(
        rect=[0, 0, 1, 0.96]
    )

    # ========================================================
    # GUARDAR
    # ========================================================

    output_file = os.path.join(
        OUTPUT_DIR,
        f"medicion_{medicion:02d}.png"
    )

    plt.savefig(
        output_file,
        dpi=300,
        bbox_inches="tight"
    )

    plt.show()

    plt.close()

    print(
        f"Guardado: {output_file}"
    )

# ============================================================
# FIN
# ============================================================

print("\n==========================================")
print("Proceso terminado.")
print(f"Imágenes guardadas en: {OUTPUT_DIR}")
print("==========================================")