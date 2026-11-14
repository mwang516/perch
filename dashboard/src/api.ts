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
// `query` carries engine threshold overrides from the tuning panel, e.g. "&tau_s=45".
export const fetchDay = (date: string, query: string, signal?: AbortSignal) =>
  get<Day>(`/api/day?date=${date}${query}`, signal);
export const fetchDays = (until: string, n: number, query: string, signal?: AbortSignal) =>
  get<DaySummary[]>(`/api/days?until=${until}&n=${n}${query}`, signal);

export const LABEL_MODES = ["computer", "gaming", "other", "away", "skip"] as const;
export type LabelMode = (typeof LABEL_MODES)[number];
export type Strategy = "random" | "balanced";

export interface LabelItem {
  id: number;
  t: number;
}
export interface LabelNext {
  item: LabelItem | null;
  remaining: number;
  sampled: Strategy;
}
export interface LabelSummary {
  counts: Partial<Record<LabelMode, number>>;
  labeled: number;
  remaining: number;
}

export const fetchLabelNext = (strategy: Strategy) => get<LabelNext>(`/api/label/next?strategy=${strategy}`);
export const fetchLabelSummary = () => get<LabelSummary>("/api/label/summary");

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const saveLabel = (observation_id: number, mode: LabelMode, sampled: Strategy) =>
  send<{ ok: true }>("POST", "/api/label", { observation_id, mode, sampled });
export const undoLabel = (observation_id: number) => send<{ item: LabelItem }>("DELETE", `/api/label/${observation_id}`);

export interface ModeScore {
  support: number;
  predicted: number;
  recall: number | null;
  precision: number | null;
}
export interface Scored {
  accuracy: number | null;
  interval: [number, number] | null;
  confusion: Record<string, Record<string, number>>;
  per_mode: Record<string, ModeScore>;
}
export interface Reliability {
  n: number;
  ece: number | null;
  bins: { lo: number; hi: number; n: number; mean_p: number; rate: number }[];
}
export interface Accuracy {
  n: number;
  fused: Scored;
  camera: Scored;
  calibration: { activity: Reliability; person_present: Reliability };
}

export const fetchAccuracy = (query: string, randomOnly: boolean, signal?: AbortSignal) =>
  get<Accuracy>(`/api/accuracy?${randomOnly ? "sampled=random" : ""}${query}`, signal);

export interface Stats {
  days: {
    date: string;
    observations: number;
    failed: number;
    input_tokens: number;
    cost_usd: number;
    running_s: number;
    per_hour: number | null;
  }[];
  observations: number;
  failed: number;
  latency_ms: { p50: number | null; p90: number | null; p99: number | null };
  tokens_per_call: number | null;
  cost_usd: number;
  triggers: Record<string, number>;
  errors: Record<string, number>;
}

export const fetchStats = (n: number, signal?: AbortSignal) => get<Stats>(`/api/stats?n=${n}`, signal);
