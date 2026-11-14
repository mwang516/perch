import { useEffect, useState } from "react";

import { fetchLive, type Live, type LiveObservation, MODE_LABEL } from "./api";
import { duration } from "./format";

const REFRESH_MS = 3000;

const TRIGGER_TEXT: Record<string, string> = {
  heartbeat: "Heartbeat",
  motion: "Scene changed",
  fast: "Follow-up",
  app_change: "App changed",
  idle_crossed: "Went idle",
  retry: "Retry",
};
// Which rule in the engine decided the frame.
const RULE_TEXT: Record<string, string> = {
  os: "Mac in use: frontmost app decides",
  os_only: "Jev failed: frontmost app decides",
  camera: "Mac idle: camera activity decides",
  away: "Empty seat and Mac idle",
  tablet: "iPad gaming seen",
  controllers: "Controllers seen",
  camera_bad: "Camera view not OK",
  jev_error: "Jev failed, Mac idle: no evidence",
};

const p2 = (v: number | undefined) => (v == null ? "–" : v.toFixed(2));
const time = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });

function topActivity(o: LiveObservation): string {
  if (!o.activity) return "–";
  const [name, prob] = Object.entries(o.activity).sort((a, b) => b[1] - a[1])[0];
  return `${name} ${prob.toFixed(2)}`;
}

/** What the agent is seeing right now: the newest frames and what the engine made of each. */
export function LivePage({ query }: { query: string }) {
  const [data, setData] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<number | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    const load = () =>
      fetchLive(query, ctl.signal).then(
        (d) => {
          setData(d);
          setError(null);
        },
        (e: Error) => e.name !== "AbortError" && setError(e.message),
      );
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      ctl.abort();
      clearInterval(timer);
    };
  }, [query]);

  if (error) return <p className="error">Couldn't load the live view: {error}</p>;
  if (!data) return null;
  const rows = data.observations;
  const latest = rows[0];
  if (!data.session || !latest) {
    return (
      <section className="card" style={{ marginTop: 14 }}>
        <p className="empty">No observations yet. Start the agent and frames appear here within seconds.</p>
      </section>
    );
  }
  const age = data.now - latest.t;
  const ended = data.session.end !== null;
  // The slowest heartbeat is 45 s, so two minutes of silence means the agent isn't sending.
  const status = ended
    ? `Session ended (${data.session.end_reason})`
    : age > 120
      ? `No frames for ${duration(age)}: agent stopped, paused, or camera missing`
      : "Agent running";
  const shown = rows.find((o) => o.id === picked) ?? latest;
  return (
    <>
      <div className="daybar">
        <span className={`live-dot${!ended && age <= 120 ? " on" : ""}`} />
        <span className="progress">
          {status} · session {data.session.id}, {data.session.observations.toLocaleString()} observations
        </span>
      </div>

      <div className="columns live-top">
        <section className="card">
          <h3>{shown === latest ? "Latest frame" : `Frame at ${time(shown.t)}`}</h3>
          {shown.has_thumb ? (
            <img className="label-frame" src={`/api/thumb/${shown.id}`} alt="Desk frame" />
          ) : (
            <p className="empty">No thumbnail for this frame.</p>
          )}
        </section>
        <section className="card">
          <h3>What the engine concluded</h3>
          <div className="live-mode">
            <span className={`swatch mode-${shown.mode ?? "unknown"}`} />
            {shown.mode ? MODE_LABEL[shown.mode] : "–"}
            {shown.coding && <span className="badge">coding</span>}
          </div>
          <dl className="live-facts">
            <dt>Decided by</dt>
            <dd>{RULE_TEXT[shown.rule] ?? shown.rule}</dd>
            <dt>Seen</dt>
            <dd>
              {time(shown.t)} ({shown === latest ? `${duration(Math.max(0, age))} ago` : "selected"})
            </dd>
            <dt>Sent because</dt>
            <dd>
              {TRIGGER_TEXT[shown.trigger] ?? shown.trigger}
              {shown.change_score != null && `, change score ${shown.change_score.toFixed(1)}`}
            </dd>
            <dt>Mac</dt>
            <dd>
              {shown.app ?? "–"}
              {shown.domain && ` (${shown.domain})`}, idle {duration(shown.idle_s)}
            </dd>
            <dt>Jev activity</dt>
            <dd>
              {shown.activity
                ? Object.entries(shown.activity)
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, v]) => `${k} ${v.toFixed(2)}`)
                    .join(" · ")
                : (shown.error ?? "–")}
            </dd>
            <dt>Jev yes/no</dt>
            <dd>
              {shown.nouls
                ? `person ${p2(shown.nouls.person_present)} · iPad gaming ${p2(shown.nouls.tablet_gaming)} · controllers ${p2(shown.nouls.controllers_out)} · camera OK ${p2(shown.nouls.camera_ok)}`
                : "–"}
            </dd>
          </dl>
        </section>
      </div>

      <section className="card">
        <h3>Recent observations</h3>
        <div className="scroll-x">
          <table className="live-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Mode</th>
                <th>Sent because</th>
                <th>Activity</th>
                <th className="num">Person</th>
                <th className="num">iPad</th>
                <th className="num">Ctrl</th>
                <th>App</th>
                <th className="num">Idle</th>
                <th className="num">Latency</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.id} className={o.id === shown.id ? "picked" : undefined} onClick={() => setPicked(o.id === latest.id ? null : o.id)}>
                  <td>{time(o.t)}</td>
                  <td>
                    <span className={`swatch mode-${o.mode ?? "unknown"}`} />
                    {o.mode ? MODE_LABEL[o.mode] : "–"}
                    {o.coding && ", coding"}
                  </td>
                  <td>{TRIGGER_TEXT[o.trigger] ?? o.trigger}</td>
                  <td>{o.ok ? topActivity(o) : <span className="fail">failed</span>}</td>
                  <td className="num">{p2(o.nouls?.person_present)}</td>
                  <td className="num">{p2(o.nouls?.tablet_gaming)}</td>
                  <td className="num">{p2(o.nouls?.controllers_out)}</td>
                  <td>
                    {o.app ?? "–"}
                    {o.domain && ` (${o.domain})`}
                  </td>
                  <td className="num">{duration(o.idle_s)}</td>
                  <td className="num">{o.latency_ms == null ? "–" : `${Math.round(o.latency_ms)} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">Updates every 3 seconds. Click a row to see its frame and how it was decided.</p>
      </section>
    </>
  );
}
