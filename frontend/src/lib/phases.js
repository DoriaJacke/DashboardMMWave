// Fases del protocolo: texto del banner, color de fondo, tinte (sombreado de
// gráficos) y tinta (etiqueta sobre el tinte). Traspaso de diseño §9.

export const PH = {
  CONECTANDO: { label: "CONECTANDO", bg: "#1d2d3d", name: "Conectando" },
  ESPERA: { label: "COLÓCATE EN POSICIÓN", bg: "#5d5d60", name: "Espera" },
  NORMAL: { label: "RESPIRACIÓN NORMAL", bg: "oklch(0.48 0.10 152)", tint: "oklch(0.94 0.04 152)", ink: "oklch(0.38 0.08 152)", name: "Respiración normal" },
  PREP: { label: "PREPÁRATE", bg: "oklch(0.52 0.12 62)", tint: "oklch(0.95 0.06 92)", ink: "oklch(0.42 0.09 62)", name: "Preparación" },
  HOLD: { label: "AGUANTA LA RESPIRACIÓN", bg: "oklch(0.48 0.15 27)", tint: "oklch(0.93 0.04 27)", ink: "oklch(0.42 0.13 27)", name: "Retención" },
  RECOVERY: { label: "DESCANSO", bg: "#416180", tint: "#e3eefa", ink: "#2c455d", name: "Descanso" },
  MONITOREO: { label: "MONITOREO CONTINUO", bg: "oklch(0.45 0.09 200)", tint: "oklch(0.94 0.03 200)", ink: "oklch(0.36 0.07 200)", name: "Monitoreo" },
  PAUSA: { label: "DESCANSO ENTRE MEDICIONES", bg: "#5d5d60", name: "Pausa" },
  CONTINUO: { label: "CAPTURANDO", bg: "oklch(0.48 0.10 152)", name: "Captura continua" },
  FIN: { label: "ADQUISICIÓN COMPLETADA", bg: "#1d2d3d", name: "Fin" },
};

export const phaseOf = (fase) => PH[fase] || PH.CONECTANDO;

/** Fases que se sombrean en los gráficos, en orden dentro de una medición. */
export const SHADE = ["NORMAL", "PREP", "HOLD", "RECOVERY", "MONITOREO"];

/** Fases que se graban en el CSV (en ellas se pueden poner marcas). */
export const REC = { NORMAL: 1, PREP: 1, HOLD: 1, RECOVERY: 1, MONITOREO: 1, CONTINUO: 1 };

export const PROTO_NAMES = { seq: "Secuencia con retención", apnea: "Apnea + monitoreo", cont: "Captura continua" };

/** Protocolos con fases y mediciones (CSV en formato largo). */
export const isSeqLike = (proto) => proto === "seq" || proto === "apnea";

/** Fases de una medición, en orden, según el protocolo. */
export function phaseSeq(proto, p) {
  if (proto === "apnea") return [...(+p.tn > 0 ? ["NORMAL"] : []), "PREP", "HOLD", "MONITOREO"];
  return ["NORMAL", "PREP", "HOLD", "RECOVERY"];
}

export const GREEN = "oklch(0.48 0.10 152)";
export const AMBER = "oklch(0.52 0.12 62)";
export const RED = "oklch(0.48 0.15 27)";
export const GREY = "#98989b";
export const INK = "#1d2d3d";

/** Duración planificada de cada fase (MONITOREO = 0 si no tiene duración fija). */
export function plannedDurations(p) {
  return { NORMAL: +p.tn, PREP: 1 + +p.cd, HOLD: +p.th, RECOVERY: +p.tr || 0, MONITOREO: +p.tm || 0 };
}

export const perMeasurement = (p, proto = "seq") => {
  const durs = plannedDurations(p);
  return phaseSeq(proto, p).reduce((sum, ph) => sum + durs[ph], 0);
};
