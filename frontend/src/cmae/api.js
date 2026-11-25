// Llamadas a /api/cmae/* (backend/cmae/servicio.py). Los errores traen el mensaje para mostrar.

async function request(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("No hay conexión con el backend. Revisa que esté funcionando.");
  }
  if (!res.ok) {
    let detail = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* sin cuerpo JSON */
    }
    throw new Error(typeof detail === "string" ? detail : detail?.[0]?.msg || `Error ${res.status}`);
  }
  return res.json();
}

export const cmaeApi = {
  config: () => request("GET", "/api/cmae/config"),
  ports: () => request("GET", "/api/cmae/puertos"),
  scanBle: () => request("POST", "/api/cmae/ble/buscar"),
  connect: (pedido) => request("POST", "/api/cmae/conectar", pedido),
  disconnect: () => request("POST", "/api/cmae/desconectar"),
};
