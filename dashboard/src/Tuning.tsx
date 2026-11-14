const HELP: Record<string, string> = {
  tau_s: "Smoothing time constant, seconds",
  switch_score: "Smoothed score a mode needs to take over",
  switch_lead: "Lead over the current mode needed to switch",
  min_dwell_s: "Seconds a mode must last before it can be replaced",
  recent_input_s: "Input this recent ends away instantly, seconds",
  active_input_s: "Frontmost app is trusted with input this recent, seconds",
  away_idle_s: "Mac idle time needed for away, seconds",
  person_cutoff: "person_present below this means an empty seat",
  tablet_cutoff: "tablet_gaming at or above this means gaming",
  controllers_cutoff: "controllers_out at or above this means gaming",
  camera_cutoff: "camera_ok below this means unknown",
  reset_gap_s: "A longer gap between observations becomes away, seconds",
  stale_s: "Seconds without usable evidence before unknown",
};

interface Props {
  defaults: Record<string, number>;
  overrides: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
}

/** Engine thresholds. Modes are derived at read time, so a change re-derives every day on screen. */
export function Tuning({ defaults, overrides, onChange }: Props) {
  const changed = Object.keys(overrides);
  const set = (name: string, raw: string) => {
    const next = { ...overrides };
    const value = Number(raw);
    if (raw === "" || Number.isNaN(value) || value === defaults[name]) delete next[name];
    else next[name] = value;
    onChange(next);
  };
  return (
    <details className="card tuning">
      <summary>
        Engine thresholds
        {changed.length > 0 && <span className="badge">{changed.length} changed, not saved</span>}
      </summary>
      <p className="hint">
        Changes apply to this page only. To keep them, copy the values into <code>Params</code> in <code>engine.py</code>.
      </p>
      <div className="tuning-grid">
        {Object.entries(defaults).map(([name, def]) => (
          <label key={name} className={name in overrides ? "changed" : undefined} title={HELP[name]}>
            <span>{name}</span>
            <input
              type="number"
              step={def < 1 ? 0.05 : 5}
              min={0}
              value={overrides[name] ?? def}
              onChange={(e) => set(name, e.target.value)}
            />
            <small>{HELP[name]}</small>
          </label>
        ))}
      </div>
      {changed.length > 0 && (
        <div className="tuning-foot">
          <code>{changed.map((k) => `${k}=${overrides[k]}`).join("  ")}</code>
          <button onClick={() => onChange({})}>Reset to defaults</button>
        </div>
      )}
    </details>
  );
}
