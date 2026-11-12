import { MODE_LABEL, MODES, type Totals as TotalsData } from "./api";
import { duration } from "./format";

export function Totals({ totals }: { totals: TotalsData }) {
  const rows = MODES.filter((m) => m !== "unknown" || totals.unknown >= 60);
  const max = Math.max(...rows.map((m) => totals[m]), 1);
  return (
    <div className="totals">
      {rows.map((m) => {
        const coding = m === "computer" ? totals.coding : 0;
        return (
          <div className="total-row" key={m}>
            <span className="total-label">{MODE_LABEL[m]}</span>
            <span className="total-bar">
              {coding > 0 && <span className="fill coding" style={{ width: `${(coding / max) * 100}%` }} />}
              <span className={`fill mode-${m}`} style={{ width: `${((totals[m] - coding) / max) * 100}%` }} />
              <span className="total-value">
                {duration(totals[m])}
                {coding > 0 && <span className="total-note"> · {duration(coding)} coding</span>}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
