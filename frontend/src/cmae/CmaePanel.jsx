// Tarjeta de un gráfico de la placa CMAE: título, sensor, estado, valores
// actuales y una o más filas de gráfico (cada fila con su propia escala).
// Adaptado de dashboard-cmae/frontend/src/components/ChartPanel.jsx.

import { memo } from "react";
import LiveChart from "./LiveChart";
import LiveValue from "./LiveValue";
import { SPEEDS, panelBadge, panelStatus } from "./panels";

const STATUS_TEXT = {
  ok: "Recibiendo datos",
  stale: "Dejaron de llegar datos",
  none: "La placa no envía datos de este sensor",
  idle: "Placa CMAE sin conectar",
};

function Legend({ row }) {
  return (
    <div className="cm-legend">
      {row.series.map((s) => (
        <span key={s.key} className="cm-legend__item">
          <i style={{ background: `var(${s.color})` }} />
          {row.series.length > 1 && <span>{s.label}</span>}
          {!row.hideValue && (
            <LiveValue serie={s.key} digits={row.digits} staleS={SPEEDS[row.speed].staleS} className="cm-legend__value" />
          )}
        </span>
      ))}
      <span className="cm-legend__unit">{row.unit}</span>
    </div>
  );
}

function CmaePanel({ panel, estado, timeScale = 1, style }) {
  const status = panelStatus(panel, estado);
  const badge = status === "idle" ? null : panelBadge(panel.id, estado?.banderas);
  const stacked = panel.rows.length > 1;

  return (
    <article className={`cm-panel cm-panel--${status}`} data-panel={panel.id} style={style}>
      <header className="cm-panel__head">
        <span className={`cm-dot cm-dot--${status}`} title={STATUS_TEXT[status]} />
        <h3 className="cm-panel__title">{panel.title}</h3>
        <span className="cm-panel__chip">{panel.chip}</span>
        {badge && <span className={`cm-badge cm-badge--${badge.tone}`}>{badge.text}</span>}
        {!stacked && <Legend row={panel.rows[0]} />}
      </header>
      <div className="cm-panel__body">
        {panel.rows.map((row, i) => (
          <div key={row.label ?? i} className={`cm-row${stacked ? " cm-row--stacked" : ""}`}>
            {stacked && (
              <div className={`cm-row__side${row.series.length > 1 ? " cm-row__side--multi" : ""}`}>
                <div className="cm-row__label">{row.label}</div>
                {row.series.map((s) => (
                  <div key={s.key} className="cm-row__value" title={s.label}>
                    {row.series.length > 1 && <i style={{ background: `var(${s.color})` }} />}
                    <LiveValue serie={s.key} digits={row.digits} staleS={SPEEDS[row.speed].staleS} />
                    {row.unit && <small>{row.series.length > 1 ? s.label : row.unit}</small>}
                  </div>
                ))}
              </div>
            )}
            <LiveChart
              series={row.series}
              windowS={SPEEDS[row.speed].windowS * timeScale}
              fps={row.fps ?? SPEEDS[row.speed].fps}
              lineWidth={SPEEDS[row.speed].lineWidth}
              minSpan={row.minSpan}
              yAxis={stacked ? "compact" : "full"}
              xAxis={i === panel.rows.length - 1}
            />
          </div>
        ))}
        {(status === "none" || status === "idle") && <div className="cm-panel__empty">{STATUS_TEXT[status]}</div>}
      </div>
    </article>
  );
}

export default memo(CmaePanel);
