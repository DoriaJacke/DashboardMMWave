// Almacén de los datos en vivo.
//
// Cada curva ("serie") guarda sus últimos puntos en dos arreglos de tamaño
// fijo: tiempos (ms de la placa) y valores. Al llenarse, lo más viejo se
// descarta, así la memoria no crece aunque la app esté horas abierta.
//
// Estos datos NO pasan por el estado de React: llegan cientos de puntos por
// segundo y redibujar la interfaz con cada uno la haría lenta. Los gráficos
// leen el almacén directamente cuando les toca dibujar.

export const LOTE = 1; // puntos nuevos: se agregan
export const FOTO = 2; // historia completa: reemplaza lo que había

class Ring {
  constructor(key, capacity) {
    this.key = key;
    this.capacity = capacity;
    // El doble de espacio permite entregar siempre un tramo continuo sin copiar:
    // solo se reacomoda cuando se llega al final.
    this.t = new Float64Array(capacity * 2);
    this.v = new Float32Array(capacity * 2);
    this.start = 0;
    this.end = 0;
    this.rev = 0; // cambia cada vez que entran datos
  }

  get length() {
    return this.end - this.start;
  }

  clear() {
    this.start = 0;
    this.end = 0;
    this.rev++;
  }

  push(times, values) {
    let n = times.length;
    if (!n) return;
    if (n > this.capacity) {
      times = times.subarray(n - this.capacity);
      values = values.subarray(n - this.capacity);
      n = this.capacity;
    }
    if (this.end + n > this.t.length) {
      const keep = Math.min(this.end - this.start, this.capacity - n);
      this.t.copyWithin(0, this.end - keep, this.end);
      this.v.copyWithin(0, this.end - keep, this.end);
      this.start = 0;
      this.end = keep;
    }
    this.t.set(times, this.end);
    this.v.set(values, this.end);
    this.end += n;
    if (this.end - this.start > this.capacity) this.start = this.end - this.capacity;
    this.rev++;
  }

  /** Último punto, o null si está vacía. */
  last() {
    if (this.end === this.start) return null;
    return { t: this.t[this.end - 1], v: this.v[this.end - 1] };
  }

  /** Índice del primer punto con tiempo >= t (búsqueda binaria). */
  lowerBound(t) {
    let lo = this.start;
    let hi = this.end;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (this.t[mid] < t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }
}

class SeriesStore {
  constructor() {
    this.byId = [];
    this.byKey = new Map();
    this.tMax = null; // el tiempo de la placa más reciente que se ha visto
    this.epoch = 0; // cambia cuando llega una FOTO (conexión nueva o reinicio de la placa)
  }

  setCatalog(series) {
    this.byId = [];
    this.byKey = new Map();
    for (const s of series) {
      const ring = new Ring(s.clave, s.capacidad);
      this.byId[s.id] = ring;
      this.byKey.set(s.clave, ring);
    }
    this.tMax = null;
    this.epoch++;
  }

  get(key) {
    return this.byKey.get(key);
  }

  clear() {
    for (const ring of this.byId) if (ring) ring.clear();
    this.tMax = null;
    this.epoch++;
  }

  /**
   * Lee un mensaje binario del servidor (formato en backend/en_vivo.py).
   * Todo viene alineado a 8 bytes, así que los números se leen directo del
   * mensaje, sin copiarlos uno por uno.
   */
  ingest(buffer) {
    const head = new DataView(buffer);
    if (head.getUint8(0) !== 1) return null;
    const tipo = head.getUint8(1);
    const count = head.getUint16(2, true);
    if (tipo === FOTO) this.clear();

    let pos = 8;
    let tMax = null;
    for (let i = 0; i < count; i++) {
      const id = head.getUint16(pos, true);
      const n = head.getUint32(pos + 4, true);
      pos += 8;
      const times = new Float64Array(buffer, pos, n);
      pos += 8 * n;
      const values = new Float32Array(buffer, pos, n);
      pos += 4 * n + (n & 1 ? 4 : 0);
      const ring = this.byId[id];
      if (ring && n) {
        ring.push(times, values);
        const last = times[n - 1];
        if (tMax === null || last > tMax) tMax = last;
      }
    }
    if (tMax !== null && (this.tMax === null || tMax > this.tMax)) this.tMax = tMax;
    return { tipo, tMax };
  }
}

export const store = new SeriesStore();
