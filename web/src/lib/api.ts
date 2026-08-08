/**
 * Typed fetch client. One function per endpoint, no ad-hoc fetch calls
 * anywhere else in the app.
 *
 * The API distinguishes two failure modes and so must the UI:
 *   503  the pipeline has not been built -- actionable, tell them to run it
 *   any other  the service is unreachable -- likely asleep on a free tier
 * Collapsing these into one "something went wrong" would waste the user's time
 * on exactly the two occasions they most need to know what to do next.
 */

import type {
  BacktestResponse, CallPlanResponse, HcpDetail, HcpPage, MetaResponse,
  ResponseModuleResponse, SegmentsResponse, SizingResponse, Summary,
  TerritoriesResponse,
} from "./types";

/** Same-origin in production (FastAPI serves web/dist); Vite proxies in dev. */
const BASE = "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The pipeline has not been run -- data is missing, not broken. */
  get isPipelineMissing(): boolean {
    return this.status === 503;
  }

  /** Could not reach the service at all (network, DNS, cold-start). */
  get isUnreachable(): boolean {
    return this.status === 0;
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

function qs(params?: Params): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function get<T>(path: string, params?: Params): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${qs(params)}`, {
      headers: { Accept: "application/json" },
    });
  } catch (cause) {
    throw new ApiError(
      "Can't reach the data service.",
      0,
      cause instanceof Error ? cause.message : undefined,
    );
  }

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail;
    } catch {
      detail = await res.text().catch(() => undefined);
    }
    throw new ApiError(
      res.status === 503 ? "Pipeline output missing." : `Request failed (${res.status}).`,
      res.status,
      detail,
    );
  }

  return (await res.json()) as T;
}

/* ------------------------------------------------------------------------ */

export interface HcpQuery {
  state?: string;
  specialty?: string;
  segment?: string;
  decile_min?: number;
  decile_max?: number;
  targets_only?: boolean;
  q?: string;
  sort?: string;
  desc?: boolean;
  page?: number;
  page_size?: number;
}

export const api = {
  health: () => get<{ status: string; data_mode: string }>("/api/health"),
  summary: () => get<Summary>("/api/summary"),
  meta: () => get<MetaResponse>("/api/meta"),

  hcps: (query: HcpQuery = {}) => get<HcpPage>("/api/hcps", query as Params),
  hcp: (npi: number) => get<HcpDetail>(`/api/hcps/${npi}`),

  /** Compact parallel-array sample of real prescribers for the story field. */
  hcpSample: (n = 24_000) =>
    get<{
      n: number; universe: number;
      opportunity_decile: number[]; volume_decile: number[];
      brand_share: number[]; class_fills: number[]; opportunity: number[];
      lat: number[]; lon: number[];
    }>("/api/hcp-sample", { n }),

  callplan: () => get<CallPlanResponse>("/api/callplan"),
  backtest: () => get<BacktestResponse>("/api/backtest"),
  sizing: () => get<SizingResponse>("/api/sizing"),
  segments: () => get<SegmentsResponse>("/api/segments"),
  responseModule: () => get<ResponseModuleResponse>("/api/response"),

  territories: (n_reps: number, alignment: "optimised" | "baseline" = "optimised") =>
    get<TerritoriesResponse>("/api/territories", { n_reps, alignment }),

  /**
   * CSV export. Returns a URL rather than fetching -- letting the browser
   * handle the download means the stream never passes through JS memory, which
   * matters at 50k rows.
   */
  exportUrl: (query: Omit<HcpQuery, "page" | "page_size" | "sort" | "desc"> = {}) =>
    `${BASE}/api/hcps/export/csv${qs(query as Params)}`,
};

/** Query keys, centralised so invalidation can never miss a cache entry. */
export const qk = {
  summary: ["summary"] as const,
  meta: ["meta"] as const,
  hcps: (q: HcpQuery) => ["hcps", q] as const,
  hcp: (npi: number) => ["hcp", npi] as const,
  callplan: ["callplan"] as const,
  backtest: ["backtest"] as const,
  sizing: ["sizing"] as const,
  segments: ["segments"] as const,
  response: ["response"] as const,
  territories: (n: number, a: string) => ["territories", n, a] as const,
};
