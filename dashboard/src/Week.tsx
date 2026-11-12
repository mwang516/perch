import { useState } from "react";

import { type DaySummary, type Mode, MODE_LABEL } from "./api";
import { duration, parseDate } from "./format";

const STACK: Mode[] = ["computer", "gaming", "other", "away"];

interface Props {
  days: DaySummary[];
  selected: string;
  onSelect: (date: string) => void;
}

export function Week({ days, selected, onSelect }: Props) {
  const [hover, setHover] = useState<string | null>(null);
  const tallest = Math.max(...days.map((d) => STACK.reduce((sum, m) => sum + d.totals[m], 0)), 3600);
  const top = Math.ceil(tallest / 3600);

  return (
    <div className="week">
      <div className="week-scale" aria-hidden="true">
        <span>{top}h</span>
        <span>0</span>
      </div>
      {days.map((d) => {
        const date = parseDate(d.date);
        const full = date.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
        return (
          <button
            key={d.date}
            className={`week-day${d.date === selected ? " selected" : ""}`}
            onClick={() => onSelect(d.date)}
            onMouseEnter={() => setHover(d.date)}
            onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(d.date)}
            onBlur={() => setHover(null)}
            aria-label={`${full}: ${duration(d.totals.at_desk)} at desk`}
          >
            <span className="week-column">
              {STACK.filter((m) => d.totals[m] >= 60).map((m) => (
                <span key={m} className={`fill mode-${m}`} style={{ height: `${(d.totals[m] / (top * 3600)) * 100}%` }} />
              ))}
            </span>
            <span className="week-label">
              {date.toLocaleDateString([], { weekday: "short" })} {date.getDate()}
            </span>
            {hover === d.date && (
              <span className="tooltip week-tip">
                <span className="tooltip-title">{duration(d.totals.at_desk)} at desk</span>
                {STACK.map((m) => (
                  <span className="tooltip-row" key={m}>
                    <span className={`swatch mode-${m}`} />
                    {MODE_LABEL[m]}
                    <span className="tooltip-num">{duration(d.totals[m])}</span>
                  </span>
                ))}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
