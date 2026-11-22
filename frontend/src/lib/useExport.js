// Estado de la exportación de imágenes PNG (generar el ZIP y descargarlo).
// Lo usan el Resultado de una adquisición y la sección Análisis.

import { useCallback, useState } from "react";
import { api } from "./api";
import { GREEN, RED } from "./phases";

const NO_EXPORT = { state: null, blob: null, n: 0 };

export function useExport(toast) {
  const [exp, setExp] = useState({ ...NO_EXPORT, dpi: 300, name: "graficos_mediciones.zip" });

  const setDpi = useCallback((v) => setExp((e) => ({ ...e, dpi: v })), []);
  const reset = useCallback(() => setExp((e) => ({ ...e, ...NO_EXPORT })), []);

  /** `params`: { sgWindow, sgOrder, key } como en api.exportZip. */
  const generate = async (params, name = "graficos_mediciones.zip") => {
    const dpi = Math.round(+exp.dpi);
    if (!(dpi >= 72 && dpi <= 600)) {
      toast("El DPI debe estar entre 72 y 600.", RED);
      return;
    }
    setExp((e) => ({ ...e, state: "running", blob: null, name }));
    try {
      const { blob, n } = await api.exportZip({ dpi, ...params });
      setExp((e) => ({ ...e, state: "done", blob, n: n || 1, dpi }));
      toast(`Imágenes listas: ${name}`, GREEN);
    } catch (e) {
      setExp((x) => ({ ...x, ...NO_EXPORT }));
      toast(e.message, RED);
    }
  };

  const download = () => {
    if (!exp.blob) return;
    const url = URL.createObjectURL(exp.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = exp.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast(`Descarga iniciada: ${exp.name}`);
  };

  return { exp, setDpi, reset, generate, download };
}
