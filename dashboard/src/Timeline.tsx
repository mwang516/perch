import { useMemo, useRef, useState } from "react";

import { type Day, MODE_LABEL, type Segment } from "./api";
import { clock, duration, hourLabel } from "./format";

const HOUR = 3600;

/** Whole hours around the tracked time, so an evening-only day isn't a sliver on a 24 h axis. */
function axisRange(day: Day): [number, number] {
  if (day.sessions.length === 0) return [day.start + 8 * HOUR, day.start + 20 * HOUR];
  let lo = Math.floor((Math.min(...day.sessions.map((s) => s.start)) - day.start) / HOUR);
  let hi = Math.ceil((Math.max(...day.sessions.map((s) => s.end)) - day.start) / HOUR);
  while (hi - lo < 6) {
    if (lo > 0) lo--;
    if (hi - lo < 6) hi++;
  }
  return [day.start + lo * HOUR, day.start + hi * HOUR];
}

/** Joins neighbours that draw the same, so the track has no seams where only the coding tag changed. */
function merge<T extends { start: number; end: number }>(items: T[], same: (a: T, b: T) => boolean): T[] {
  const out: T[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (last && same(last, item) && item.start - last.end < 1) out[out.length - 1] = { ...last, end: item.end };
    else out.push(item);
  }
  return out;
}

function describe(seg: Segment | undefined): string {
  if (!seg) return "Not tracked";
  if (seg.gap) return "Away (no observations)";
  return seg.coding ? "Computer, coding" : MODE_LABEL[seg.mode];
}

export function Timeline({ day }: { day: Day }) {
  const [lo, hi] = useMemo(() => axisRange(day), [day]);
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; t: number; width: number } | null>(null);

  const pct = (t: number) => ((t - lo) / (hi - lo)) * 100;
  const modes = useMemo(() => merge(day.segments, (a, b) => a.mode === b.mode && a.gap === b.gap), [day]);
  const coding = useMemo(() => merge(day.segments.filter((s) => s.coding), () => true), [day]);
  const hours = Math.round((hi - lo) / HOUR);
  const step = hours > 16 ? 3 : hours > 8 ? 2 : 1;
  const ticks = Array.from({ length: Math.floor(hours / step) + 1 }, (_, i) => lo + i * step * HOUR);

  const hovered = hover ? day.segments.find((s) => hover.t >= s.start && hover.t < s.end) : undefined;
  const run = hovered && modes.find((s) => hovered.start >= s.start && hovered.end <= s.end);

  return (
    <div
      className="timeline"
      ref={ref}
      onMouseMove={(e) => {
        const box = ref.current!.getBoundingClientRect();
        const x = Math.min(Math.max(e.clientX - box.left, 0), box.width);
        setHover({ x, t: lo + (x / box.width) * (hi - lo), width: box.width });
      }}
      onMouseLeave={() => setHover(null)}
    >
      <div className="track" role="img" aria-label="Desk modes across the day. The segments table lists every one.">
        {modes.map((s) => (
          <div
            key={s.start}
            className={`seg mode-${s.mode}${s.gap ? " gap" : ""}`}
            style={{ left: `${pct(s.start)}%`, width: `${pct(s.end) - pct(s.start)}%` }}
          />
        ))}
      </div>
      <div className="lane" aria-hidden="true">
        {coding.map((s) => (
          <div key={s.start} className="seg coding" style={{ left: `${pct(s.start)}%`, width: `${pct(s.end) - pct(s.start)}%` }} />
        ))}
      </div>
      <div className="axis" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} className="tick" style={{ left: `${pct(t)}%` }}>
            {hourLabel(t)}
          </span>
        ))}
      </div>
      {hover && (
        <>
          <div className="crosshair" style={{ left: hover.x }} />
          <div
            className="tooltip"
            style={hover.x > hover.width / 2 ? { right: hover.width - hover.x + 12 } : { left: hover.x + 12 }}
          >
            <div className="tooltip-title">
              {hovered && <span className={`swatch mode-${hovered.mode}${hovered.gap ? " gap" : ""}`} />}
              {describe(hovered)}
            </div>
            <div className="tooltip-sub">
              {run ? `${clock(run.start)} – ${clock(run.end)} · ${duration(run.end - run.start)}` : clock(hover.t)}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
