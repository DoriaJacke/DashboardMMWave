// Conexión en vivo con la placa CMAE (WebSocket /ws/cmae).
//
// Llegan dos clases de mensajes:
//   - texto (JSON): el catálogo de series al conectarse y, dos veces por
//     segundo, el estado (conexión, sensores, banderas). Va al estado de React.
//   - binario: los puntos nuevos de cada curva, unas 30 veces por segundo.
//     Van directo al almacén (cmae/store.js), sin pasar por React: son
//     cientos de puntos por segundo y redibujar la interfaz con cada uno la haría lenta.
// Si la conexión se corta, se reconecta sola y el servidor reenvía la historia.
//
// Se usa una sola vez, en App.jsx: el almacén es único para toda la página.
// Con enabled = false (placa deshabilitada en el backend) no se conecta.

import { useEffect, useState } from "react";
import { observe, resetClock } from "./clock";
import { FOTO, store } from "./store";

export function useCmae(enabled = true) {
  const [estado, setEstado] = useState(null);

  useEffect(() => {
    if (!enabled) {
      setEstado(null);
      return undefined;
    }
    let ws = null;
    let closed = false;
    let retry = null;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws/cmae`);
      ws.binaryType = "arraybuffer";
      ws.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          const msg = JSON.parse(ev.data);
          if (msg.type === "catalogo") {
            store.setCatalog(msg.series);
            resetClock();
          } else if (msg.type === "estado") {
            setEstado(msg);
          }
          return;
        }
        const r = store.ingest(ev.data);
        if (!r) return;
        if (r.tipo === FOTO) resetClock();
        if (r.tMax !== null) observe(r.tMax);
      };
      ws.onclose = () => {
        setEstado(null);
        if (!closed) retry = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      if (ws) ws.close();
    };
  }, [enabled]);

  return estado;
}
