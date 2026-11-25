// Llamadas a la API del backend (FastAPI). Los errores traen el mensaje para
// mostrar y, si corresponde, el campo afectado (file, port, range).

export class ApiError extends Error {
  constructor(message, status, field) {
    super(message);
    this.status = status;
    this.field = field;
  }
}

async function request(method, url, body) {
  const raw = body instanceof Blob;
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": raw ? "text/csv" : "application/json" } : undefined,
      body: body !== undefined ? (raw ? body : JSON.stringify(body)) : undefined,
    });
  } catch {
    throw new ApiError("No hay conexión con el backend. Revisa que esté funcionando.", 0, null);
  }
  if (!res.ok) {
    let detail = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* sin cuerpo JSON */
    }
    const msg = typeof detail === "string" ? detail : detail?.msg || `Error ${res.status}`;
    throw new ApiError(msg, res.status, detail?.field ?? null);
  }
  return res;
}

const json = (p) => p.then((r) => r.json());

export const api = {
  ports: () => json(request("GET", "/api/ports")),
  /** Funciones opcionales activas en el backend, p. ej. { cmae: false } (backend/features.py). */
  features: () => json(request("GET", "/api/features")),
  config: () => json(request("GET", "/api/config")),
  saveConfig: (patch) => json(request("PUT", "/api/config", patch)),
  start: (config, filename) => json(request("POST", "/api/acquisition", { config, filename })),
  stop: () => json(request("POST", "/api/acquisition/stop")),
  confirm: () => json(request("POST", "/api/acquisition/confirm")),
  marker: () => json(request("POST", "/api/acquisition/marker")),
  summary: () => json(request("GET", "/api/acquisition/summary")),
  files: () => json(request("GET", "/api/files")),
  openFile: (name) => json(request("GET", `/api/files/${encodeURIComponent(name)}`)),
  uploadFile: (file) => json(request("POST", `/api/analysis/upload?${new URLSearchParams({ name: file.name })}`, file)),
  /** Sin `key` exporta la última adquisición; con `key`, el archivo abierto en Análisis. */
  exportZip: async ({ dpi, sgWindow, sgOrder, key }) => {
    const q = new URLSearchParams({ dpi: String(dpi) });
    if (key) q.set("key", key);
    if (sgWindow != null) {
      q.set("sg_window", String(sgWindow));
      q.set("sg_order", String(sgOrder));
    }
    const res = await request("POST", `${key ? "/api/analysis/export" : "/api/export"}?${q}`);
    const n = Number(res.headers.get("X-Image-Count")) || null;
    return { blob: await res.blob(), n };
  },
};
