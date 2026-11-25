// Reloj de pantalla y ritmo de dibujo.
//
// Los datos llegan a saltos (por BLE, un bloque de varias muestras cada tanto).
// Para que las curvas avancen parejo, la pantalla no dibuja "lo último que
// llegó": calcula qué hora marca la placa en este instante y dibuja hasta
// medio segundo antes. Ese pequeño atraso tapa los saltos de llegada.

import { store } from "./store";

/** Atraso de pantalla. Debe ser mayor que la pausa entre bloques (PPG: ~0,4 s). */
export const DISPLAY_DELAY_MS = 500;

let offset = null; // hora de la placa ≈ performance.now() + offset

/** Se llama cada vez que llegan datos, con el tiempo más reciente del lote. */
export function observe(tMax, perf = performance.now()) {
  const candidate = tMax - perf;
  if (offset === null || candidate > offset || offset - candidate > 3000) {
    // El lote que llega con menos demora es el que mejor dice la hora de la placa.
    offset = candidate;
  } else {
    // Corrección lenta, por si el reloj de la placa y el del PC no avanzan igual.
    offset += (candidate - offset) * 0.002;
  }
}

export function resetClock() {
  offset = null;
}

/**
 * Hasta qué instante (en ms de la placa) hay que dibujar ahora.
 * Si dejan de llegar datos, se detiene en el último que llegó: la pantalla
 * queda quieta en vez de seguir corriendo vacía.
 */
export function displayTime(perf = performance.now()) {
  if (offset === null || store.tMax === null) return null;
  return Math.min(perf + offset - DISPLAY_DELAY_MS, store.tMax);
}

// --------------------------------------------------------
// Ritmo de dibujo: un solo compás para toda la app
// --------------------------------------------------------
//
// Todo lo que se mueve en pantalla (gráficos, modelo 3D, números, el corazón)
// se dibuja al mismo compás, 30 veces por segundo. Así el navegador arma una
// sola imagen nueva por compás. Si cada cosa se dibujara por su cuenta, tendría
// que rearmar la pantalla muchas más veces (hasta la frecuencia del monitor),
// que es lo que más procesador y tarjeta gráfica consume.

/** Compases por segundo. ?maxfps=15 en la dirección lo baja (para diagnóstico). */
export const TICK_HZ = Math.min(30, Number(new URLSearchParams(window.location.search).get("maxfps")) || 30);

const drawables = new Set();
let started = false;
let tick = 0;
let sequence = 0;

// Diagnóstico (?perfil=1): cuánto tarda en dibujarse cada cosa. window.__cmaePerfil() lo entrega.
const PERFIL = new URLSearchParams(window.location.search).has("perfil") ? new Map() : null;
if (PERFIL) {
  const inicio = performance.now();
  window.__cmaePerfil = () => {
    const segundos = (performance.now() - inicio) / 1000;
    const filas = [...PERFIL].map(([tag, v]) => ({
      tag,
      veces_s: +(v.n / segundos).toFixed(1),
      ms_c_u: +(v.ms / v.n).toFixed(3),
      ms_por_s: +(v.ms / segundos).toFixed(1),
    }));
    filas.sort((a, b) => b.ms_por_s - a.ms_por_s);
    return { segundos: +segundos.toFixed(1), compases_s: +(tick / segundos).toFixed(1), filas };
  };
}

function frame(perf) {
  tick++;
  const t = displayTime(perf);
  for (const d of drawables) {
    if ((tick + d.phase) % d.every === 0) {
      try {
        if (PERFIL) {
          const t0 = performance.now();
          d.draw(t, perf);
          const v = PERFIL.get(d.tag) || { n: 0, ms: 0 };
          v.n++;
          v.ms += performance.now() - t0;
          PERFIL.set(d.tag, v);
        } else {
          d.draw(t, perf);
        }
      } catch (err) {
        console.error(err);
      }
    }
  }
}

/**
 * Arranca el compás.
 *
 * El dibujo siempre pasa por requestAnimationFrame, que lo alinea con el
 * monitor y no corre si la ventana está minimizada u oculta (ahí la app deja
 * de dibujar). Lo que cambia según el monitor es cómo se espera entre compases:
 *
 *   - Hasta 90 Hz: se sigue cada cuadro del monitor y se dibuja cuando ya pasó
 *     el tiempo de un compás (a 60 Hz, uno de cada dos cuadros).
 *   - Monitores más rápidos (144 Hz, 180 Hz...): seguir cada cuadro despertaría
 *     al navegador 180 veces por segundo solo para descartar cinco de cada
 *     seis. Se usa un temporizador que pide el cuadro justo antes de que toque.
 *
 * La frecuencia del monitor se mide al empezar, con el menor tiempo entre
 * cuadros seguidos (el menor, y no el promedio, porque al cargar la página
 * algunos cuadros se atrasan).
 */
function start() {
  const period = 1000 / TICK_HZ;
  let last = -Infinity;
  const gate = (perf) => {
    if (perf - last >= period - 1.5) {
      last = perf;
      frame(perf);
    }
  };

  const follow = (perf) => {
    gate(perf);
    requestAnimationFrame(follow);
  };

  const timed = (vsync) => {
    // "ajuste" corrige de a poco la espera para que, en promedio, el compás
    // dure lo que debe (el cuadro del monitor en que cae cada pedido varía).
    let ajuste = 0;
    const run = (perf) => {
      if (last > 0) ajuste = Math.max(-8, Math.min(8, ajuste + (period - (perf - last)) * 0.05));
      last = perf;
      frame(perf);
      const wait = perf + period - vsync / 2 + ajuste - performance.now();
      setTimeout(() => requestAnimationFrame(run), Math.max(0, wait));
    };
    requestAnimationFrame(run);
  };

  let prev = 0;
  let vsync = Infinity;
  let n = 0;
  const probe = (perf) => {
    if (prev) vsync = Math.min(vsync, perf - prev);
    prev = perf;
    gate(perf); // mientras se mide ya se dibuja
    if (++n < 45) requestAnimationFrame(probe);
    else if (1000 / vsync > 90) timed(vsync);
    else requestAnimationFrame(follow);
  };
  requestAnimationFrame(probe);
}

/**
 * Registra algo que se dibuja `fps` veces por segundo (como máximo, el compás).
 * draw(t, perf): t es el instante de la placa a mostrar (o null si no hay datos).
 * tag es solo un nombre para el diagnóstico (?perfil=1).
 * Devuelve una función para quitarlo.
 */
export function addDrawable(fps, draw, tag = "otros") {
  const every = Math.max(1, Math.round(TICK_HZ / fps));
  // Las cosas lentas se reparten entre compases distintos para no juntar trabajo.
  const d = { every, phase: sequence++ % every, draw, tag };
  drawables.add(d);
  if (!started) {
    started = true;
    start();
  }
  return () => drawables.delete(d);
}
