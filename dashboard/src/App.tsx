import { useEffect, useMemo, useState } from "react";

import { AccuracyPage } from "./Accuracy";
import { fetchMeta, type Meta } from "./api";
import { DayPage } from "./Day";
import { LabelPage } from "./Label";
import { LivePage } from "./Live";
import { StatsPage } from "./Stats";
import { Tuning } from "./Tuning";

const PAGES = { day: "Day", live: "Live", label: "Label", accuracy: "Accuracy", stats: "Stats" } as const;
type Page = keyof typeof PAGES;

function pageFromHash(): Page {
  const key = window.location.hash.slice(1);
  return key in PAGES ? (key as Page) : "day";
}

export function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [meta, setMeta] = useState<Meta | null>(null);
  // Engine thresholds changed in the tuning panel. They only affect what this browser tab shows.
  const [overrides, setOverrides] = useState<Record<string, number>>({});

  useEffect(() => {
    fetchMeta().then(setMeta, () => {});
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const query = useMemo(
    () =>
      Object.entries(overrides)
        .map(([k, v]) => `&${k}=${v}`)
        .join(""),
    [overrides],
  );

  return (
    <main>
      <header>
        <h1>Perch</h1>
        {meta?.synthetic && <span className="badge">Synthetic data</span>}
        <div className="tabs" role="tablist">
          {(Object.keys(PAGES) as Page[]).map((p) => (
            <a key={p} href={`#${p}`} role="tab" aria-selected={p === page} className={p === page ? "tab active" : "tab"}>
              {PAGES[p]}
            </a>
          ))}
        </div>
      </header>

      {meta && (page === "day" || page === "live" || page === "accuracy") && (
        <Tuning defaults={meta.params} overrides={overrides} onChange={setOverrides} />
      )}
      {page === "day" && <DayPage query={query} />}
      {page === "live" && <LivePage query={query} />}
      {page === "label" && <LabelPage />}
      {page === "accuracy" && <AccuracyPage query={query} />}
      {page === "stats" && <StatsPage />}
    </main>
  );
}
