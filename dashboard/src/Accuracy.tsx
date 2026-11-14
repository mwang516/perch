import { useEffect, useState } from "react";

import { type Accuracy, fetchAccuracy, MODE_LABEL, type Mode, MODES, type Reliability, type Scored } from "./api";

const pct = (x: number | null | undefined, digits = 1) => (x == null ? "–" : `${(x * 100).toFixed(digits)}%`);

function Headline({ title, note, s }: { title: string; note: string; s: Scored }) {
  return (
    <div className="tile">
      <div className="tile-label">{title}</div>
      <div className="tile-value">{pct(s.accuracy)}</div>
      <div className="tile-note">
        {s.interval ? `95% interval ${pct(s.interval[0])} to ${pct(s.interval[1])}` : note}
      </div>
    </div>
  );
}

function Confusion({ s }: { s: Scored }) {
  const truths = MODES.filter((m) => s.confusion[m]);
  const preds = MODES.filter((m) => truths.some((t) => s.confusion[t][m]));
  const max = Math.max(1, ...truths.flatMap((t) => Object.values(s.confusion[t])));
  return (
    <table className="confusion">
      <thead>
        <tr>
          <th>Labeled ↓ / predicted →</th>
          {preds.map((m) => (
            <th key={m} className="num">
              {MODE_LABEL[m]}
            </th>
          ))}
          <th className="num">Recall</th>
        </tr>
      </thead>
      <tbody>
        {truths.map((t) => (
          <tr key={t}>
            <td>{MODE_LABEL[t]}</td>
            {preds.map((m) => {
              const n = s.confusion[t][m] ?? 0;
              return (
                <td key={m} className={`num cell${t === m ? " hit" : ""}`} style={{ ["--w" as string]: n / max }}>
                  {n || ""}
                </td>
              );
            })}
            <td className="num">{pct(s.per_mode[t]?.recall, 0)}</td>
          </tr>
        ))}
        <tr className="foot-row">
          <td>Precision</td>
          {preds.map((m) => (
            <td key={m} className="num">
              {pct(s.per_mode[m]?.precision, 0)}
            </td>
          ))}
          <td />
        </tr>
      </tbody>
    </table>
  );
}

/** Reliability diagram: stated probability against how often it was true. The diagonal is perfect calibration. */
function Calibration({ r, yLabel }: { r: Reliability; yLabel: string }) {
  const S = 220;
  const P = 34;
  const x = (v: number) => P + v * (S - P - 8);
  const y = (v: number) => S - P - v * (S - P - 8);
  const maxN = Math.max(1, ...r.bins.map((b) => b.n));
  return (
    <div className="calibration">
      <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={`Calibration: ${yLabel}`}>
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line className="gridline" x1={x(0)} x2={x(1)} y1={y(v)} y2={y(v)} />
            <text className="axis-text" x={x(0) - 6} y={y(v) + 4} textAnchor="end">
              {v * 100}%
            </text>
            <text className="axis-text" x={x(v)} y={S - P + 16} textAnchor="middle">
              {v * 100}%
            </text>
          </g>
        ))}
        <line className="diagonal" x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} />
        <polyline className="cal-line" points={r.bins.map((b) => `${x(b.mean_p)},${y(b.rate)}`).join(" ")} />
        {r.bins.map((b) => (
          <circle key={b.lo} className="cal-dot" cx={x(b.mean_p)} cy={y(b.rate)} r={3 + 5 * Math.sqrt(b.n / maxN)}>
            <title>{`Jev said ${pct(b.mean_p, 0)} on ${b.n} frames; true on ${pct(b.rate, 0)}`}</title>
          </circle>
        ))}
        <text className="axis-text" x={x(0.5)} y={S - 2} textAnchor="middle">
          Probability Jev stated
        </text>
      </svg>
      <div className="cal-note">
        {yLabel}. Calibration error {pct(r.ece)} over {r.n.toLocaleString()} frames. Larger dots hold more frames.
      </div>
    </div>
  );
}

export function AccuracyPage({ query }: { query: string }) {
  const [randomOnly, setRandomOnly] = useState(false);
  const [data, setData] = useState<Accuracy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    fetchAccuracy(query, randomOnly, ctl.signal).then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => e.name !== "AbortError" && setError(e.message),
    );
    return () => ctl.abort();
  }, [query, randomOnly]);

  if (error) return <p className="error">Couldn't load accuracy: {error}</p>;
  if (!data) return null;
  const gain = data.fused.accuracy != null && data.camera.accuracy != null ? data.fused.accuracy - data.camera.accuracy : null;
  const modes = MODES.filter((m): m is Mode => !!data.fused.per_mode[m]?.support);
  return (
    <>
      <div className="daybar">
        <span className="progress">{data.n.toLocaleString()} labeled frames scored</span>
        <label className="pick">
          <input type="checkbox" checked={randomOnly} onChange={(e) => setRandomOnly(e.target.checked)} />
          Only frames picked at random
        </label>
      </div>
      {data.n === 0 ? (
        <section className="card">
          <p className="empty">No labels yet. Label some frames on the Label page and the numbers appear here.</p>
        </section>
      ) : (
        <>
          <section className="tiles">
            <Headline title="Camera + Mac signals" note="" s={data.fused} />
            <Headline title="Camera alone" note="" s={data.camera} />
            <div className="tile">
              <div className="tile-label">Gain from fusing</div>
              <div className="tile-value">{gain == null ? "–" : `${gain >= 0 ? "+" : ""}${(gain * 100).toFixed(1)} pts`}</div>
              <div className="tile-note">same frames, same labels</div>
            </div>
          </section>

          <section className="card">
            <h3>Recall by mode</h3>
            <table>
              <thead>
                <tr>
                  <th>Mode</th>
                  <th className="num">Labeled frames</th>
                  <th className="num">Camera + Mac</th>
                  <th className="num">Camera alone</th>
                </tr>
              </thead>
              <tbody>
                {modes.map((m) => (
                  <tr key={m}>
                    <td>{MODE_LABEL[m]}</td>
                    <td className="num">{data.fused.per_mode[m].support}</td>
                    <td className="num">{pct(data.fused.per_mode[m].recall)}</td>
                    <td className="num">{pct(data.camera.per_mode[m]?.recall)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <div className="columns">
            <section className="card">
              <h3>Confusion: camera + Mac signals</h3>
              <Confusion s={data.fused} />
            </section>
            <section className="card">
              <h3>Confusion: camera alone</h3>
              <Confusion s={data.camera} />
            </section>
          </div>

          <div className="columns">
            <section className="card">
              <h3>Calibration: activity answer</h3>
              <Calibration r={data.calibration.activity} yLabel="How often Jev's top activity matched the label" />
            </section>
            <section className="card">
              <h3>Calibration: person present</h3>
              <Calibration r={data.calibration.person_present} yLabel="How often someone was at the desk" />
            </section>
          </div>
        </>
      )}
    </>
  );
}
