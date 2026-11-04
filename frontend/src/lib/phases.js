// Fases del protocolo: texto del banner, color de fondo, tinte (sombreado de
// gráficos) y tinta (etiqueta sobre el tinte). Traspaso de diseño §9.

export const PH = {
  CONECTANDO: { label: "CONECTANDO", bg: "#1d2d3d", name: "Conectando" },
  ESPERA: { label: "COLÓCATE EN POSICIÓN", bg: "#5d5d60", name: "Espera" },
  NORMAL: { label: "RESPIRACIÓN NORMAL", bg: "oklch(0.48 0.10 152)", tint: "oklch(0.94 0.04 152)", ink: "oklch(0.38 0.08 152)", name: "Respiración normal" },
  PREP: { label: "PREPÁRATE", bg: "oklch(0.52 0.12 62)", tint: "oklch(0.95 0.06 92)", ink: "oklch(0.42 0.09 62)", name: "Preparación" },
  HOLD: { label: "AGUANTA LA RESPIRACIÓN", bg: "oklch(0.48 0.15 27)", tint: "oklch(0.93 0.04 27)", ink: "oklch(0.42 0.13 27)", name: "Retención" },
  RECOVERY: { label: "DESCANSO", bg: "#416180", tint: "#e3eefa", ink: "#2c455d", name: "Descanso" },
  PAUSA: { label: "DESCANSO ENTRE MEDICIONES", bg: "#5d5d60", name: "Pausa" },
  CONTINUO: { label: "CAPTURANDO", bg: "oklch(0.48 0.10 152)", name: "Captura continua" },
  FIN: { label: "ADQUISICIÓN COMPLETADA", bg: "#1d2d3d", name: "Fin" },
};

export const phaseOf = (fase) => PH[fase] || PH.CONECTANDO;

/** Fases que se sombrean en los gráficos, en orden dentro de una medición. */
export const SHADE = ["NORMAL", "PREP", "HOLD", "RECOVERY"];

/** Fases que se graban en el CSV (en ellas se pueden poner marcas). */
export const REC = { NORMAL: 1, PREP: 1, HOLD: 1, RECOVERY: 1, CONTINUO: 1 };

export const GREEN = "oklch(0.48 0.10 152)";
export const AMBER = "oklch(0.52 0.12 62)";
export const RED = "oklch(0.48 0.15 27)";
export const GREY = "#98989b";
export const INK = "#1d2d3d";

/** Duración planificada de cada fase de la secuencia. */
export function plannedDurations(p) {
  return { NORMAL: +p.tn, PREP: 1 + +p.cd, HOLD: +p.th, RECOVERY: +p.tr };
}

export const perMeasurement = (p) => +p.tn + 1 + +p.cd + +p.th + +p.tr;
