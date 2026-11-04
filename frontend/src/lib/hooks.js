import { useEffect, useLayoutEffect, useRef, useState } from "react";

const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Vuelve a dibujar el componente cada `ms` milisegundos mientras `active`. */
export function useNow(ms = 250, active = true) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setNow(performance.now()), ms);
    return () => clearInterval(id);
  }, [ms, active]);
  return now;
}

/**
 * Anima el elemento cuando cambia `value` (Web Animations API).
 * `onMount` también anima la primera vez. Respeta prefers-reduced-motion.
 */
export function useAnimateOnChange(value, keyframes, options, onMount = false) {
  const ref = useRef(null);
  const prev = useRef(undefined);
  const first = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    const changed = first.current ? onMount && value != null : prev.current !== value;
    if (el && changed && !reducedMotion() && el.animate) el.animate(keyframes, options);
    prev.current = value;
    first.current = false;
    // keyframes/options son constantes de cada llamada
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return ref;
}

/** Tamaño (ancho y alto) de un elemento, con ResizeObserver. */
export function useSize() {
  const ref = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setSize((s) => {
        const w = Math.round(r.width);
        const h = Math.round(r.height);
        return Math.abs(w - s.w) > 2 || Math.abs(h - s.h) > 2 ? { w, h } : s;
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

export const EASE = "cubic-bezier(.2,.8,.2,1)";
