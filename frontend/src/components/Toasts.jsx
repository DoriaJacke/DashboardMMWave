// Avisos abajo a la derecha: entran desde la derecha y se cierran solos a los 4,5 s.

import { useCallback, useRef, useState } from "react";

export function useToasts() {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});
  const close = useCallback((id) => {
    clearTimeout(timers.current[id]);
    delete timers.current[id];
    setToasts((ts) => ts.filter((x) => x.id !== id));
  }, []);
  const push = useCallback(
    (text, color = "#5980a6") => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((ts) => [...ts.slice(-3), { id, text, color }]);
      timers.current[id] = setTimeout(() => close(id), 4500);
    },
    [close],
  );
  return { toasts, push, close };
}

export default function Toasts({ toasts, onClose }) {
  return (
    <div aria-live="polite" style={{ position: "fixed", right: 20, bottom: 20, display: "flex", flexDirection: "column", gap: 10, zIndex: 1080, width: 340 }}>
      {toasts.map((t) => (
        <div key={t.id} className="toast show enter-right" role="status" style={{ width: "100%", border: 0, boxShadow: "var(--shadow-lg)", background: "#fff" }}>
          <div className="toast-body d-flex align-items-center gap-2" style={{ fontSize: 14 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: t.color, flex: "none" }} />
            <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{t.text}</span>
            <button type="button" className="btn-close" aria-label="Cerrar" onClick={() => onClose(t.id)} />
          </div>
        </div>
      ))}
    </div>
  );
}
