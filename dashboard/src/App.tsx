import { useEffect, useState } from "react";

import { type Day, type DaySummary, fetchDay, fetchDays, fetchMeta, type Meta, MODE_LABEL, MODES } from "./api";
import { clock, duration, isoDate, longDate, shiftDate } from "./format";
import { Timeline } from "./Timeline";
import { Totals } from "./Totals";
import { Week } from "./Week";

const REFRESH_MS = 30_000;

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      {MODES.map((m) => (
        <span key={m}>
          <span className={`swatch mode-${m}`} />
          {m === "unknown" ? "Unknown or no observations" : MODE_LABEL[m]}
        </span>
      ))}
      <span>
        <span className="swatch coding lane-key" />
        Coding (lower strip)
      </span>
    </div>
  );
}

export function App() {
  const today = isoDate(new Date());
  const [date, setDate] = useState(today);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [day, setDay] = useState<Day | null>(null);
  const [week, setWeek] = useState<DaySummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta().then(setMeta, () => {});
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    // The week strip ends today unless the selected day is older than that.
    const weekEnd = date < shiftDate(today, -6) ? date : today;
    const load = () =>
      Promise.all([fetchDay(date, ctl.signal), fetchDays(weekEnd, 7, ctl.signal)]).then(
        ([d, w]) => {
          setDay(d);
          setWeek(w);
          setError(null);
        },
        (e: Error) => {
          if (e.name !== "AbortError") setError(e.message);
        },
      );
    load();
    const timer = date === today ? setInterval(load, REFRESH_MS) : undefined;
    return () => {
      ctl.abort();
      clearInterval(timer);
    };
  }, [date, today]);

  const t = day?.totals;
  const stats = day?.stats;
  return (
    <main>
      <header>
        <h1>Perch</h1>
        {meta?.synthetic && <span className="badge">Synthetic data</span>}
        <nav>
          <button onClick={() => setDate(shiftDate(date, -1))} aria-label="Previous day">
            ‹
          </button>
          <input
            type="date"
            value={date}
            max={today}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            aria-label="Day"
          />
          <button onClick={() => setDate(shiftDate(date, 1))} disabled={date >= today} aria-label="Next day">
            ›
          </button>
          <button onClick={() => setDate(today)} disabled={date === today}>
            Today
          </button>
        </nav>
      </header>

      {error && <p className="error">Couldn't load the day: {error}</p>}

      {day && t && stats && (
        // The previous day stays up, dimmed, while the next one loads.
        <div className={day.date === date ? undefined : "stale"}>
          <h2>{longDate(day.date)}</h2>
          <section className="tiles">
            <Tile label="At desk" value={duration(t.at_desk)} note={`${duration(t.tracked)} tracked`} />
            <Tile
              label="Coding"
              value={duration(t.coding)}
              note={t.computer > 0 ? `${Math.round((t.coding / t.computer) * 100)}% of computer time` : undefined}
            />
            <Tile label="Gaming" value={duration(t.gaming)} />
            <Tile label="Away" value={duration(t.away)} note="while the agent was running" />
          </section>

          <section className="card">
            <h3>Timeline</h3>
            {day.segments.length === 0 ? (
              <p className="empty">Nothing tracked on this day.</p>
            ) : (
              <>
                <Timeline day={day} />
                <Legend />
              </>
            )}
          </section>

          <div className="columns">
            <section className="card">
              <h3>Time by mode</h3>
              <Totals totals={t} />
            </section>
            <section className="card">
              <h3>Seven days</h3>
              <Week days={week} selected={date} onSelect={setDate} />
            </section>
          </div>

          {day.segments.length > 0 && (
            <details className="card">
              <summary>Segments table ({day.segments.length})</summary>
              <table>
                <thead>
                  <tr>
                    <th>Start</th>
                    <th>End</th>
                    <th>Mode</th>
                    <th className="num">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {day.segments.map((s) => (
                    <tr key={s.start}>
                      <td>{clock(s.start)}</td>
                      <td>{clock(s.end)}</td>
                      <td>
                        {MODE_LABEL[s.mode]}
                        {s.coding && ", coding"}
                        {s.gap && " (no observations)"}
                      </td>
                      <td className="num">{duration(s.end - s.start)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          <footer>
            {stats.observations.toLocaleString()} observations · {stats.failed} failed
            {stats.observations > 0 && ` (${((stats.failed / stats.observations) * 100).toFixed(1)}%)`}
            {stats.median_latency_ms !== null && ` · median ${Math.round(stats.median_latency_ms)} ms`} · about $
            {stats.cost_usd.toFixed(2)} of Jev calls
          </footer>
        </div>
      )}
    </main>
  );
}
