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
  /** [low, estimate, high] from the prescriber bootstrap. */
  share_growth_ratio_ci?: [number, number, number] | null;
  absolute_growth_ratio_ci?: [number, number, number] | null;
  spearman_ci?: [number, number, number] | null;
  matched_growth_ratio?: number | null;
  matched_paired_difference?: number | null;
  matched_ci?: [number | null, number | null];
  matched_pairs?: number | null;
}

export interface RuleOutcome {
  abs_capture?: number | null;
  share_capture?: number | null;
  net_brand_fill_growth?: number | null;
  median_base_class_fills?: number | null;
}

export interface BusinessCase {
  class: "BACK-TESTED";
  n_budget?: number | null;
  rules: Record<string, RuleOutcome>;
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
  recommended_n_reps?: number | null;
  response_identified?: boolean | null;
  required_ceiling_at_current?: number | null;
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
  kmeans_imbalance?: number;
  kmeans_cv?: number;
  kmeans_contiguity?: number;
  kmeans_travel?: number;
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
  headlines: {
    h1: HeadlineH1;
    business_case?: BusinessCase;
    h2: HeadlineH2;
    h3: HeadlineH3;
    recommendation?: {
      recommended_rule?: string;
      criterion?: string;
      share_vs_volume?: number;
      abs_vs_volume?: number;
    };
    retargeting?: {
      hybrid_vs_volume_contribution?: number | null;
      delta_contribution?: number | null;
      priced_at?: string | null;
      label?: string | null;
    };
  };
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
  explanation?: ExplanationRow[];
  forecast?: ForecastRow | null;
  uplift?: { cate: number; propensity: number } | null;
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
  shap_top_driver: { feature?: string; share?: number; group_shares?: Record<string, number> };
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

/* --------------------------------------------------------------- decision */

export interface FrontierRow {
  period: "selection" | "holdout";
  weight: number;
  abs_capture: number;
  share_capture: number;
  net_brand_fill_growth: number;
  abs_vs_volume: number;
  share_vs_volume: number;
  clears_floor: boolean;
  abs_vs_volume_lo?: number | null;
  abs_vs_volume_hi?: number | null;
  share_vs_volume_lo?: number | null;
  share_vs_volume_hi?: number | null;
  p_clears_floor?: number | null;
}

export interface PilotEndpoint {
  effect_per_year: number;
  sd_per_year: number;
  prior_rho: number;
  icc_territory: number;
  power_holdout20_6m?: number;
  power_holdout20_12m?: number;
  power_territory_split_6m?: number;
  power_territory_split_12m?: number;
  holdout_share_needed_80pct_6m?: number | null;
  holdout_share_needed_80pct_12m?: number | null;
}

export interface PilotDesign {
  weight?: number;
  n_list?: number;
  required_ceiling?: number;
  calls_per_year?: number;
  half_saturation?: number;
  prescribers_per_territory?: number;
  n_territories?: number;
  time_scaling?: string;
  recommended_endpoint?: "share" | "fills";
  share?: PilotEndpoint;
  fills?: PilotEndpoint;
}

export interface DecisionResponse {
  frontier: FrontierRow[];
  frontier_summary: {
    n_budget?: number;
    abs_floor_vs_volume?: number;
    selected_weight?: number;
    selected_on?: string;
    holdout_share_vs_volume?: number;
    holdout_abs_vs_volume?: number;
    holdout_p_clears_floor?: number;
    equal_weight_share_vs_volume?: number;
    equal_weight_abs_vs_volume?: number;
    equal_weight_p_clears_floor?: number;
    holdout_best_weight?: number;
    robust_weight_p95?: number;
  };
  recommendation: Summary["headlines"]["recommendation"];
  pilot: PilotDesign;
  required_response: { n_reps: number; required_ceiling: number | null }[];
  retargeting: Record<string, number | string | null>;
  headline: HeadlineH3 & Record<string, unknown>;
  business_case: BusinessCaseValue;
  value_grid: { n_reps: number; contribution_per_ceiling: number; field_cost: number }[];
  economics: {
    net_revenue_per_30day_fill: { base: number; low: number; high: number };
    contribution_margin: { base: number; low: number; high: number };
    rep_cost_annual: { base: number; low: number; high: number };
    ira_2026_price_per_fill: number;
  };
}

export interface BeliefRow {
  median_x: number;
  hold: number;
  cut: number;
  grow: number;
  act_now: number;
  act_now_n: number;
  pilot_then_decide: number;
  pilot_cost: number;
  evpi: number;
  evsi: number;
  p_pilot_says_grow: number;
  p_pilot_says_cut: number;
  best: "hold" | "cut" | "grow" | "pilot_then_decide";
}

export interface PayoffRow {
  decision: "cut" | "hold" | "grow" | "pilot";
  n_reps: number;
  response_x: number;
  value_vs_hold: number;
  regret: number;
}

export interface BusinessCaseValue {
  horizon_years?: number;
  pilot_months?: number;
  holdout?: number;
  holdout_cost_fraction?: number;
  prior_log_sd?: number;
  break_even_ceiling?: number;
  pilot_se_ceiling?: number;
  pilot_se_x_break_even?: number;
  rep_range?: [number, number];
  current_n_reps?: number;
  rep_cost_annual?: number;
  rep_hire_cost?: number;
  rep_ramp_months?: number;
  rep_separation_cost?: number;
  payoff?: PayoffRow[];
  max_regret?: Record<string, number>;
  minimax_regret_decision?: string;
  by_belief?: BeliefRow[];
  pilot_best_band_x?: [number, number] | null;
  grow_pays_above_x?: number | null;
  base_evpi?: number;
  base_evsi?: number;
  base_pilot_cost?: number;
  base_pilot_value?: number;
  base_net_value_of_pilot?: number;
  retargeting_per_year_by_response?: Record<string, number>;
}

/* ----------------------------------------------------------- data science */

export interface LadderRow {
  rule: string;
  value_capture: number;
  abs_capture: number;
  eb_share_capture: number;
  precision_at_k: number;
  ndcg_at_k: number;
  net_brand_fill_growth: number;
  median_base_class_fills: number;
  value_capture_lo: number;
  value_capture_hi: number;
  abs_vs_volume: number;
  passes_guardrail: boolean;
}

export interface GainRow { rule: string; fraction_targeted: number; abs_gain: number; value_gain: number; value_lift: number }
export interface CoverageRow { variant: string; segment: string; level: string; coverage: number; median_width: number; n: number }
export interface CalibRow { bin: number; mean_pred: number; mean_actual: number; n: number }
export interface ErrorRow { segment: string; level: string; n: number; mae: number; bias: number; relative_bias: number; mean_actual: number }
export interface RepRow { segment: string; level: string; share_of_prescribers: number; share_of_list: number; share_of_value: number; representation_ratio: number; value_captured_in_segment: number }
export interface CausalRow { spec: string; treatment: string; theta: number; se: number | null; ci_low: number | null; ci_high: number | null; t: number | null }
export interface QiniRow { fraction_targeted: number; uplift_model: number; uplift_random: number }
export interface UpliftDecile { decile: number; predicted: number; observed: number; se: number; n: number }
export interface ShapRow { feature: string; label: string; mean_abs_shap: number; share: number }
export interface AblationRow { variant: string; spearman_vs_production: number; value_capture: number; hybrid_value_capture: number; hybrid_abs_vs_volume: number; value_capture_change: number; hybrid_value_capture_change: number }
export interface DriftRow { from_year: number; to_year: number; feature: string; kind: string; psi: number; ks: number | null; status: string; is_score: boolean }
export interface NetworkRow { model: string; value_capture: number; ndcg_at_k: number; abs_capture: number; precision_at_k: number }
export interface H2HRow { rule: string; median_base_class_fills: number; abs_capture: number; eb_share_capture: number; net_brand_fill_growth: number }
export interface FunnelRow { class_fills_observed: number; raw_share: number; eb_share: number; specialty_group: string }
export interface ContractRow { table: string; check: string; passed: boolean; detail: string }

export interface DataScienceResponse {
  summary: Record<string, Record<string, unknown>>;
  ladder: LadderRow[];
  gain_curves: GainRow[];
  coverage: CoverageRow[];
  calibration: CalibRow[];
  hurdle_calibration: CalibRow[];
  errors: ErrorRow[];
  representation: RepRow[];
  causal: CausalRow[];
  qini: QiniRow[];
  uplift_deciles: UpliftDecile[];
  shap_global: ShapRow[];
  ablation: AblationRow[];
  drift: DriftRow[];
  network: NetworkRow[];
  shrinkage_h2h: H2HRow[];
  shrinkage_funnel: FunnelRow[];
  contracts: ContractRow[];
}

export interface ExplanationRow {
  rank: number; feature: string; label: string; contribution: number; multiplier: number; value: string;
  /** The value in human units (log1p counts undone), formatted by the API. */
  display?: string;
}
export interface ForecastRow { forecast_year: number; p_active: number; brand_fills_pred: number; brand_fills_lo: number; brand_fills_hi: number }

/* ---------------------------------------------------------------- call list */

export interface CallListOption {
  territory: number;
  n_hcps: number;
  n_targets: number;
  workload: number;
  opportunity: number;
  states: string;
}

export interface CallListRow {
  priority: number;
  npi: number;
  last_name: string | null;
  first_name: string | null;
  city: string | null;
  state: string | null;
  zip3: string | null;
  specialty_group: string | null;
  class_fills: number | null;
  brand_share: number | null;
  opportunity: number | null;
  opportunity_decile: number | null;
  calls_per_month: number | null;
  is_target: boolean;
  why: string | null;
  forecast_lo: number | null;
  forecast_mid: number | null;
  forecast_hi: number | null;
  p_active: number | null;
}

export interface CallListResponse {
  n_reps: number;
  options: CallListOption[];
  territory: CallListOption | null;
  targets_only?: boolean;
  rows: CallListRow[];
}
