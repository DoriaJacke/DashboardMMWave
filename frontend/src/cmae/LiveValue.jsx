// Último valor de una serie, como texto. Se actualiza solo, unas 4 veces por
// segundo, escribiendo directo en la página (sin volver a dibujar el resto).
// Si la última lectura es vieja muestra "—".

import { memo, useEffect, useRef } from "react";
import { addDrawable } from "./clock";
import { num } from "./format";
import { store } from "./store";

function LiveValue({ serie, digits = 1, staleS = 3, suffix = "", className }) {
  const ref = useRef(null);

  useEffect(() => {
    let shown = null;
    return addDrawable(4, (t) => {
      const last = t === null ? null : store.get(serie)?.last();
      const text = last && t - last.t <= staleS * 1000 ? num(last.v, digits) + suffix : "—";
      if (text !== shown && ref.current) {
        shown = text;
        ref.current.textContent = text;
      }
    }, "numeros");
  }, [serie, digits, staleS, suffix]);

  return (
    <span ref={ref} className={className}>
      —
    </span>
  );
}

export default memo(LiveValue);
