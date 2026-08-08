/**
 * Types mirroring the FastAPI response shapes in api/schemas.py and api/main.py.
 *
 * Fields are optional where the backend genuinely may omit them -- a module that
 * has not run yet returns an empty manifest section rather than an error. The
 * UI is expected to handle absence, not assume it away.
 */

export type EvidenceClass = "BACK-TESTED" | "ARITHMETIC" | "SCENARIO" | "PROXY";

export type DataMode = "REAL" | "SYNTHETIC" | "UNKNOWN";

/* ---------------------------------------------------------------- summary */

export interface HeadlineH1 {
  class: "BACK-TESTED";
  claim: string;
  share_growth_ratio?: number | null;
  absolute_growth_ratio?: number | null;
  decile_spearman?: number | null;
  gate_passed?: boolean | null;
  caveat?: string | null;
  opportunity_pct_of_share_growth?: number | null;
  volume_pct_of_share_growth?: number | null;
}

export interface HeadlineH2 {
  class: "ARITHMETIC";
  claim: string;
  opportunity_reach?: number | null;
  volume_reach?: number | null;
  geography_reach?: number | null;
  n_reps?: number | null;
  hcps_reachable?: number | null;
}

export interface HeadlineH3 {
  class: "SCENARIO";
  claim: string;
  current_n_reps?: number | null;
  break_even_n_reps?: number | null;
  rep_gap?: number | null;
  marginal_roi_at_current?: number | null;
  incremental_profit?: number | null;
  sensitivity_range?: [number | null, number | null];
  caveat?: string | null;
}

export interface Disagreement {
  n_hcps?: number;
  exact_agreement_pct?: number;
  within_one_decile_pct?: number;
  disagree_by_2plus_pct?: number;
  volume_low_opportunity_high?: number;
  volume_high_opportunity_low?: number;
}

export interface TerritoryHeadline {
  n_reps?: number;
  imbalance_before?: number;
  imbalance_after?: number;
  cv_before?: number;
  cv_after?: number;
  contiguity_before?: number;
  contiguity_after?: number;
  travel_before?: number;
  travel_after?: number;
  travel_reduction_pct?: number;
}

export interface Summary {
  data_mode: DataMode;
  kpis: {
    hcps_analysed?: number | null;
    hcps_in_market?: number | null;
    hcps_targeted?: number | null;
    pct_targeted?: number | null;
    monthly_calls?: number | null;
    implied_reps?: number | null;
    current_reps?: number | null;
  };
  headlines: { h1: HeadlineH1; h2: HeadlineH2; h3: HeadlineH3 };
  disagreement: Disagreement;
  territory: TerritoryHeadline;
}

/* ------------------------------------------------------------------- hcps */

export interface HcpRow {
  npi: number;
  last_name: string | null;
  first_name: string | null;
  city: string | null;
  state: string | null;
  specialty: string | null;
  specialty_group: string | null;
  zip3: string | null;
  class_fills: number | null;
  brand_fills: number | null;
  brand_share: number | null;
  potential_class: number | null;
  potential_brand: number | null;
  opportunity: number | null;
  opportunity_decile: number;
  volume_decile: number;
  decile_shift: number | null;
  calls_per_month: number | null;
  is_target: boolean | null;
  achievable_share: number | null;
}

export interface HcpPage {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  rows: HcpRow[];
}

export interface HcpTrendPoint {
  year: number;
  class_fills: number | null;
  brand_fills: number | null;
  brand_share: number | null;
  class_growth_yoy: number | null;
}

export interface HcpPayment {
  year: number;
  pay_total: number | null;
  pay_count: number | null;
  n_manufacturers: number | null;
  pay_focus: number | null;
  pay_competitor: number | null;
}

export interface HcpDetail {
  hcp: HcpRow & Record<string, unknown>;
  trend: HcpTrendPoint[];
  payments: HcpPayment[];
  segment: string | null;
}

/* --------------------------------------------------------------- callplan */

export interface CallPlanCell {
  decile_band: string;
  share_band: string;
  calls_per_month: number;
  hcp_count: number;
  class_fills: number;
  brand_fills: number;
  opportunity: number;
  monthly_calls: number;
}

export interface ReachPoint {
  rule: "opportunity" | "volume" | "geography";
  hcps_called: number;
  pct_of_universe: number;
  calls_index: number;
  pct_opportunity_reached: number;
  pct_class_volume_reached: number;
}

export interface DisagreementCell {
  volume_decile: number;
  opportunity_decile: number;
  hcp_count: number;
  class_fills: number;
  opportunity: number;
}

export interface CallPlanResponse {
  matrix: CallPlanCell[];
  reach_curve: ReachPoint[];
  disagreement_matrix: DisagreementCell[];
  summary: Record<string, unknown>;
}

/* --------------------------------------------------------------- backtest */

export interface LiftRow {
  rule: "opportunity" | "volume";
  decile: number;
  n: number;
  mean_growth_abs: number;
  median_growth_abs: number;
  total_growth_abs: number;
  mean_share_growth: number;
}

export interface BacktestResponse {
  decile_lift: LiftRow[];
  head_to_head: Record<string, number | null>;
  matched: Record<string, number | boolean | null>;
  gate: {
    gate?: string;
    passed?: boolean;
    decile_spearman?: number;
    share_growth_ratio?: number;
    absolute_growth_ratio?: number;
    criterion?: string;
    note?: string;
  };
  misses: Record<string, unknown>[];
  miss_diagnosis: Record<string, unknown>;
}

/* ----------------------------------------------------------------- sizing */

export interface RoiPoint {
  n_reps: number;
  contribution: number;
  field_cost: number;
  profit: number;
  roi: number | null;
  marginal_contribution: number | null;
  marginal_roi: number | null;
  incremental_fills: number;
  hcps_reached: number;
}

export interface TornadoRow {
  assumption: string;
  base_value: number;
  low_value: number;
  high_value: number;
  break_even_low: number;
  break_even_base: number;
  break_even_high: number;
  swing: number;
  basis: string;
}

export interface SizingResponse {
  roi_curve: RoiPoint[];
  tornado: TornadoRow[];
  pnl: Record<string, unknown>[];
  headline: HeadlineH3 & Record<string, unknown>;
  assumptions: Record<string, { base: number; low: number; high: number; basis: string; unit?: string }>;
}

/* ------------------------------------------------------------ territories */

export interface TerritorySummaryRow {
  alignment: string;
  n_reps: number;
  territory: number;
  workload: number;
  n_units: number;
  n_hcps: number;
  n_targets: number;
  high_decile_hcps: number;
  opportunity: number;
  lat: number;
  lon: number;
}

export interface TerritoryUnit {
  unit: string;
  state: string | null;
  lat: number;
  lon: number;
  territory: number;
  workload: number;
  n_hcps: number;
  n_targets: number;
  high_decile_hcps: number;
}

export interface TerritoryStats {
  alignment: string;
  n_reps: number;
  n_territories: number;
  workload_total: number;
  workload_mean: number;
  workload_max: number;
  workload_min: number;
  imbalance_ratio: number | null;
  workload_cv: number | null;
  mean_weighted_distance_mi: number;
  contiguity_rate: number;
  n_contiguous: number;
  high_decile_hcps_covered: number;
}

export interface TerritoriesResponse {
  alignment: string;
  n_reps: number;
  territories: TerritorySummaryRow[];
  units: TerritoryUnit[];
  stats: TerritoryStats[];
  all_stats: TerritoryStats[];
  headline: TerritoryHeadline;
  presolved_rep_counts: number[];
}

/* ------------------------------------------------------------------- meta */

export interface DataScope {
  mode: "full" | "deploy_bundle";
  prescribers_served: number;
  prescribers_analysed: number;
  note: string;
}

export interface MetaResponse {
  data_mode: DataMode;
  data_mode_warning: string | null;
  data_scope?: DataScope;
  years: { all: number[]; train_start: number; train_end: number; holdout: number };
  therapeutic_class: Record<string, unknown>;
  volume_metric: string;
  row_counts: Record<string, { rows?: number; cols?: number; path?: string }>;
  suppression: Record<string, Record<string, number>>;
  open_payments_match: Record<string, number | null>;
  potential_model: Record<string, number>;
  sfa_crosscheck: Record<string, number>;
  shap_top_driver: { feature?: string; share?: number };
  gates: Record<string, { passed?: boolean; criterion?: string } | null>;
  economic_assumptions: Record<string, { base: number; low: number; high: number; basis: string; unit?: string }>;
  territory_config: Record<string, unknown>;
  limitations: string[];
  sources: { name: string; url: string }[];
}

/* --------------------------------------------------------------- segments */

export interface SegmentProfile {
  cluster: number;
  segment: string;
  strategy: string;
  n_hcps: number;
  pct_of_universe: number;
  brand_share: number;
  share_delta_recent: number;
  opportunity_pct: number;
  [k: string]: unknown;
}

export interface SegmentsResponse {
  profiles: SegmentProfile[];
  diagnostics: { k: number; silhouette: number; stability_ari: number }[];
  summary: Record<string, unknown>;
}

/* --------------------------------------------------------------- response */

export interface ResponseModuleResponse {
  naive_ols: Record<string, number | null>;
  pretrend: Record<string, number | boolean | null>;
  matching: Record<string, number | boolean | null>;
  did: Record<string, number | string | boolean | null>;
  saturation: Record<string, unknown>;
  saturation_curve: { payment_usd: number; predicted_share_delta: number; ci_low: number; ci_high: number }[];
  balance: { covariate: string; smd_before: number; smd_after: number }[];
  caveat: string;
}
