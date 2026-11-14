import { useEffect, useState } from "react";

import { fetchStats, type Stats } from "./api";
import { duration, parseDate } from "./format";

const ms = (v: number | null) => (v == null ? "–" : `${Math.round(v)} ms`);
const TRIGGER_TEXT: Record<string, string> = {
  heartbeat: "Heartbeat (nothing changed)",
  motion: "Scene changed",
  fast: "Follow-up after a scene change",
  app_change: "Frontmost app changed",
  idle_crossed: "Mac went idle",
  retry: "Fresh frame after a failed call",
};

export function StatsPage() {
  const [n, setN] = useState(14);
  const [data, setData] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    fetchStats(n, ctl.signal).then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => e.name !== "AbortError" && setError(e.message),
    );
    return () => ctl.abort();
  }, [n]);

  if (error) return <p className="error">Couldn't load stats: {error}</p>;
  if (!data) return null;
  const days = data.days.filter((d) => d.observations > 0);
  const triggers = Object.entries(data.triggers).sort((a, b) => b[1] - a[1]);
  const maxTrigger = Math.max(1, ...triggers.map(([, c]) => c));
  return (
    <>
      <div className="daybar">
        <span className="progress">{data.observations.toLocaleString()} observations</span>
        <label className="pick">
          Period
          <select value={n} onChange={(e) => setN(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </label>
      </div>

      <section className="tiles">
        <div className="tile">
          <div className="tile-label">Median latency</div>
          <div className="tile-value">{ms(data.latency_ms.p50)}</div>
          <div className="tile-note">
            90th percentile {ms(data.latency_ms.p90)} · 99th {ms(data.latency_ms.p99)}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Jev cost</div>
          <div className="tile-value">${data.cost_usd.toFixed(2)}</div>
          <div className="tile-note">
            {days.length > 0 ? `$${(data.cost_usd / days.length).toFixed(2)} per day with data` : "no data yet"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Failed calls</div>
          <div className="tile-value">{data.observations ? `${((data.failed / data.observations) * 100).toFixed(1)}%` : "–"}</div>
          <div className="tile-note">{data.failed.toLocaleString()} failed</div>
        </div>
        <div className="tile">
          <div className="tile-label">Tokens per call</div>
          <div className="tile-value">{data.tokens_per_call == null ? "–" : Math.round(data.tokens_per_call).toLocaleString()}</div>
          <div className="tile-note">input tokens, one frame</div>
        </div>
      </section>

      <div className="columns">
        <section className="card">
          <h3>Why frames were sent</h3>
          {triggers.length === 0 ? (
            <p className="empty">No observations in this period.</p>
          ) : (
            <div className="totals">
              {triggers.map(([name, count]) => (
                <div className="total-row wide" key={name}>
                  <span className="total-label">{TRIGGER_TEXT[name] ?? name}</span>
                  <span className="total-bar">
                    <span className="fill mode-computer" style={{ width: `${(count / maxTrigger) * 100}%` }} />
                    <span className="total-value">
                      {count.toLocaleString()}
                      <span className="total-note"> · {Math.round((count / data.observations) * 100)}%</span>
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="card">
          <h3>Failures by type</h3>
          {Object.keys(data.errors).length === 0 ? (
            <p className="empty">No failed calls.</p>
          ) : (
            <table>
              <tbody>
                {Object.entries(data.errors)
                  .sort((a, b) => b[1] - a[1])
                  .map(([kind, count]) => (
                    <tr key={kind}>
                      <td>{kind}</td>
                      <td className="num">{count.toLocaleString()}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="card">
        <h3>By day</h3>
        {days.length === 0 ? (
          <p className="empty">No observations in this period.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Day</th>
                <th className="num">Agent running</th>
                <th className="num">Observations</th>
                <th className="num">Per hour</th>
                <th className="num">Failed</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date}>
                  <td>{parseDate(d.date).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}</td>
                  <td className="num">{duration(d.running_s)}</td>
                  <td className="num">{d.observations.toLocaleString()}</td>
                  <td className="num">{d.per_hour == null ? "–" : Math.round(d.per_hour)}</td>
                  <td className="num">{d.failed}</td>
                  <td className="num">${d.cost_usd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
