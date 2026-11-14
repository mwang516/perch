import { useCallback, useEffect, useState } from "react";

import {
  fetchLabelNext,
  fetchLabelSummary,
  LABEL_MODES,
  type LabelItem,
  type LabelMode,
  type LabelSummary,
  saveLabel,
  type Strategy,
  undoLabel,
} from "./api";

const LABEL_TEXT: Record<LabelMode, string> = {
  computer: "Computer",
  gaming: "Gaming",
  other: "Other",
  away: "Away",
  skip: "Can't tell",
};
const LABEL_HELP: Record<LabelMode, string> = {
  computer: "Typing, using the mouse, or watching the monitor or laptop",
  gaming: "iPad, purple controllers, pen tablet, Switch, or a game on the Mac",
  other: "At the desk doing something else: phone, eating, fiddling, resting",
  away: "Nobody at the desk",
  skip: "The picture is too unclear to judge; left out of accuracy",
};

function when(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Hand-labels saved frames. Jev's answers are hidden on purpose, so the label comes from the picture alone. */
export function LabelPage() {
  const [strategy, setStrategy] = useState<Strategy>("random");
  const [item, setItem] = useState<LabelItem | null>(null);
  const [sampled, setSampled] = useState<Strategy>("random");
  const [summary, setSummary] = useState<LabelSummary | null>(null);
  const [last, setLast] = useState<{ id: number; mode: LabelMode } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = useCallback(async (s: Strategy) => {
    try {
      const [n, sum] = await Promise.all([fetchLabelNext(s), fetchLabelSummary()]);
      setItem(n.item);
      setSampled(n.sampled);
      setSummary(sum);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    next(strategy);
  }, [next, strategy]);

  const label = useCallback(
    async (mode: LabelMode) => {
      if (!item || busy) return;
      setBusy(true);
      try {
        await saveLabel(item.id, mode, sampled);
        setLast({ id: item.id, mode });
        await next(strategy);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [item, busy, sampled, strategy, next],
  );

  const undo = useCallback(async () => {
    if (!last || busy) return;
    setBusy(true);
    try {
      const back = await undoLabel(last.id);
      setItem(back.item);
      setLast(null);
      setSummary(await fetchLabelSummary());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [last, busy]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement).tagName === "SELECT") return;
      const i = Number(e.key) - 1;
      if (i >= 0 && i < LABEL_MODES.length) label(LABEL_MODES[i]);
      else if (e.key === "z" || e.key === "u") undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [label, undo]);

  return (
    <>
      <div className="daybar">
        <span className="progress">
          {summary ? `${summary.labeled.toLocaleString()} labeled · ${summary.remaining.toLocaleString()} left` : ""}
        </span>
        <label className="pick">
          Pick frames
          <select value={strategy} onChange={(e) => setStrategy(e.target.value as Strategy)}>
            <option value="random">At random (unbiased)</option>
            <option value="balanced">Evenly across activities</option>
          </select>
        </label>
      </div>
      {error && <p className="error">{error}</p>}

      <section className="card label-card">
        {!loaded ? null : item ? (
          <>
            <img key={item.id} className="label-frame" src={`/api/thumb/${item.id}`} alt="Desk frame to label" />
            <div className="label-when">{when(item.t)}</div>
            <div className="label-buttons">
              {LABEL_MODES.map((m, i) => (
                <button key={m} className={`label-btn label-${m}`} disabled={busy} onClick={() => label(m)} title={LABEL_HELP[m]}>
                  <kbd>{i + 1}</kbd>
                  {LABEL_TEXT[m]}
                </button>
              ))}
            </div>
          </>
        ) : (
          <p className="empty">
            No frames left to label. Frames appear here once the agent has saved observations with thumbnails.
          </p>
        )}
        <div className="label-foot">
          {last ? (
            <>
              Last frame labeled <b>{LABEL_TEXT[last.mode]}</b>.{" "}
              <button onClick={undo} disabled={busy}>
                Undo <kbd>Z</kbd>
              </button>
            </>
          ) : (
            "Press 1–5 to label, Z to undo."
          )}
        </div>
      </section>

      <section className="card">
        <h3>What each label means</h3>
        <dl className="label-help">
          {LABEL_MODES.map((m) => (
            <div key={m}>
              <dt>
                {LABEL_TEXT[m]}
                {summary?.counts[m] ? <span className="count"> · {summary.counts[m]}</span> : null}
              </dt>
              <dd>{LABEL_HELP[m]}</dd>
            </div>
          ))}
        </dl>
        <p className="hint">
          Label what the picture shows, not what you remember doing. Jev's answers are hidden here so they can't sway the
          label. Frames picked "evenly across activities" are marked, and the Accuracy page can leave them out.
        </p>
      </section>
    </>
  );
}
