// Conexión en vivo con el backend (WebSocket /ws/live).
// Al conectarse llega el historial completo ("snapshot") y después, ~1 vez por
// segundo o apenas cambia la fase, el estado y solo los datos nuevos ("update").
// Si la conexión se corta, se reconecta sola y vuelve a pedir el historial.

import { useEffect, useRef, useState } from "react";
import { emptyStore, ingest } from "./series";

export function useLive() {
  const storeRef = useRef(emptyStore());
  const [state, setState] = useState({
    connected: false,
    loaded: false, // ya llegó el primer snapshot
    session: null,
    status: null,
    receivedAt: 0,
    version: 0,
    endedOnArrival: false, // la adquisición ya había terminado al conectarse
    exportProgress: null,
  });

  useEffect(() => {
    let ws = null;
    let closed = false;
    let retry = null;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws/live`);
      // Solo el primer historial de cada conexión dice si la página llegó con la
      // adquisición ya terminada (por ejemplo, al recargar). Una adquisición nueva
      // que falla de inmediato (puerto que no abre) debe mostrar su error en vivo.
      let firstSnapshot = true;
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        const now = performance.now();
        if (msg.type === "snapshot") {
          const store = emptyStore();
          ingest(store, msg.records, msg.dist);
          storeRef.current = store;
          const endedOnArrival = firstSnapshot && !!msg.status?.terminado;
          firstSnapshot = false;
          setState((s) => ({
            ...s,
            loaded: true,
            session: msg.session,
            status: msg.status,
            receivedAt: now,
            version: s.version + 1,
            endedOnArrival,
          }));
        } else if (msg.type === "update") {
          if (msg.data) ingest(storeRef.current, msg.data.records, msg.data.dist);
          setState((s) => ({
            ...s,
            status: msg.status,
            receivedAt: now,
            version: msg.data ? s.version + 1 : s.version,
          }));
        } else if (msg.type === "export") {
          setState((s) => ({ ...s, exportProgress: msg }));
        }
      };
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) retry = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      if (ws) ws.close();
    };
  }, []);

  return { ...state, store: storeRef.current };
}

/** Segundos desde el inicio, interpolados entre mensajes (para contadores fluidos). */
export function liveT(live, nowMs = performance.now()) {
  const st = live.status;
  if (!st) return 0;
  if (st.terminado) return st.t;
  return st.t + Math.max(0, (nowMs - live.receivedAt) / 1000);
}
