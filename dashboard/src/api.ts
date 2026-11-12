export type Mode = "computer" | "gaming" | "other" | "away" | "unknown";

export const MODES: Mode[] = ["computer", "gaming", "other", "away", "unknown"];
export const MODE_LABEL: Record<Mode, string> = {
  computer: "Computer",
  gaming: "Gaming",
  other: "Other",
  away: "Away",
  unknown: "Unknown",
};

export interface Segment {
  session_id: number;
  mode: Mode;
  coding: boolean;
  start: number; // epoch seconds
  end: number;
  gap: boolean; // away inferred from a hole in the observations (lid closed, asleep)
}

export type Totals = Record<Mode | "coding" | "tracked" | "at_desk", number>; // seconds

export interface Day {
  date: string;
  start: number;
  end: number;
  sessions: { id: number; start: number; end: number; crashed: boolean }[];
  segments: Segment[];
  totals: Totals;
  stats: {
    observations: number;
    failed: number;
    median_latency_ms: number | null;
    input_tokens: number;
    cost_usd: number;
    triggers: Record<string, number>;
  };
}

export interface DaySummary {
  date: string;
  totals: Totals;
}

export interface Meta {
  db: string;
  synthetic: boolean;
  params: Record<string, number>;
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const fetchMeta = (signal?: AbortSignal) => get<Meta>("/api/meta", signal);
export const fetchDay = (date: string, signal?: AbortSignal) => get<Day>(`/api/day?date=${date}`, signal);
export const fetchDays = (until: string, n: number, signal?: AbortSignal) =>
  get<DaySummary[]>(`/api/days?until=${until}&n=${n}`, signal);
