/**
 * Browser port of src/models/value.py, so the business case recomputes as the
 * reader drags their own belief. Same formulas, smaller Monte Carlo (the
 * pipeline's 20,000-draw results are the reference; this is for exploration).
 *
 *   horizon value vs holding of size n, for response c:
 *     H * [(K(n) - K(60)) c - (cost(n) - cost(60))] - switching(n) - ramp(n) c
 */

export interface Grid {
  n_reps: number;
  contribution_per_ceiling: number;
  field_cost: number;
}

export interface Params {
  current: number;
  cReq: number;
  seC: number;
  hire: number;
  rampMonths: number;
  separation: number;
  holdoutCostFraction: number;
  pilotMonths: number;
}

export interface StrategyValues {
  hold: number;
  cut: number;
  grow: number;
  pilot: number;
  pilotCost: number;
  pSaysGrow: number;
  pSaysCut: number;
  best: "hold" | "cut" | "grow" | "pilot";
}

/** Seeded PRNG (mulberry32) so a given slider position always gives one answer. */
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function normal(r: () => number): number {
  const u = Math.max(r(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

export class Economy {
  readonly reps: number[];
  readonly i0: number;
  /** Absolute contribution per unit ceiling at today's size (prices the hold-out). */
  readonly K0: number;
  private readonly dK: number[];
  private readonly dCost: number[];
  private readonly sw: number[];
  private readonly rampK: number[];

  constructor(grid: Grid[], p: Params) {
    this.reps = grid.map((g) => g.n_reps);
    this.i0 = this.reps.reduce((b, n, i) => (Math.abs(n - p.current) < Math.abs(this.reps[b]! - p.current) ? i : b), 0);
    const K0 = grid[this.i0]!.contribution_per_ceiling;
    this.K0 = K0;
    const C0 = grid[this.i0]!.field_cost;
    const n0 = this.reps[this.i0]!;
    this.dK = grid.map((g) => g.contribution_per_ceiling - K0);
    this.dCost = grid.map((g) => g.field_cost - C0);
    this.sw = this.reps.map((n) => (n > n0 ? (n - n0) * p.hire : (n0 - n) * p.separation));
    this.rampK = this.dK.map((dk, i) => (this.reps[i]! > n0 ? 0.5 * (p.rampMonths / 12) * dk : 0));
  }

  /** Horizon value vs holding, for size index i and response c. */
  value(i: number, c: number, horizon: number): number {
    return horizon * (this.dK[i]! * c - this.dCost[i]!) - this.sw[i]! - this.rampK[i]! * c;
  }

  best(c: number, horizon: number): number {
    let b = 0;
    let bv = -Infinity;
    for (let i = 0; i < this.reps.length; i++) {
      const v = this.value(i, c, horizon);
      if (v > bv) { bv = v; b = i; }
    }
    return b;
  }
}

/** E[c | c_hat] for a log-normal prior and normal measurement, as a lookup. */
export function posteriorMean(median: number, logSd: number, se: number) {
  const nC = 260;
  const nO = 360;
  const lo = Math.log(median) - 5 * logSd;
  const hi = Math.log(median) + 5 * logSd;
  const c: number[] = [];
  const prior: number[] = [];
  for (let i = 0; i < nC; i++) {
    const lc = lo + ((hi - lo) * i) / (nC - 1);
    const ci = Math.exp(lc);
    c.push(ci);
    prior.push(Math.exp(-0.5 * ((lc - Math.log(median)) / logSd) ** 2) / ci);
  }
  const oMin = -4 * se;
  const oMax = c[nC - 1]! + 4 * se;
  const obs: number[] = [];
  const pm: number[] = [];
  for (let j = 0; j < nO; j++) {
    const o = oMin + ((oMax - oMin) * j) / (nO - 1);
    let w = 0;
    let wc = 0;
    for (let i = 0; i < nC; i++) {
      const l = Math.exp(-0.5 * ((o - c[i]!) / se) ** 2) * prior[i]!;
      w += l;
      wc += l * c[i]!;
    }
    obs.push(o);
    pm.push(w > 0 ? wc / w : median);
  }
  return (x: number) => {
    if (x <= oMin) return pm[0]!;
    if (x >= oMax) return pm[nO - 1]!;
    const f = ((x - oMin) / (oMax - oMin)) * (nO - 1);
    const k = Math.floor(f);
    return pm[k]! + (f - k) * (pm[k + 1]! - pm[k]!);
  };
}

/** Expected value vs holding of each strategy, for one belief. */
export function strategyValues(eco: Economy, p: Params, medianX: number, logSd: number,
  horizon: number, draws = 1500, seed = 7): StrategyValues {
  const r = rng(seed);
  const median = medianX * p.cReq;
  const post = posteriorMean(median, logSd, p.seC);
  const tP = p.pilotMonths / 12;
  const last = eco.reps.length - 1;
  let cut = 0, grow = 0, pilot = 0, cost = 0, sg = 0, sc = 0;
  for (let d = 0; d < draws; d++) {
    const c = median * Math.exp(logSd * normal(r));
    cut += eco.value(0, c, horizon);
    grow += eco.value(last, c, horizon);
    const cHat = c + p.seC * normal(r);
    const k = eco.best(post(cHat), horizon - tP);
    // Held-out calls are re-spent on the next names: the loss is the gap.
    const pc = p.holdoutCostFraction * tP * c * eco.K0;
    cost += pc;
    pilot += eco.value(k, c, horizon - tP) - pc;
    if (eco.reps[k]! > eco.reps[eco.i0]!) sg++;
    if (eco.reps[k]! < eco.reps[eco.i0]!) sc++;
  }
  const out = {
    hold: 0,
    cut: cut / draws,
    grow: grow / draws,
    pilotCost: cost / draws,
    pilot: 0,
    pSaysGrow: sg / draws,
    pSaysCut: sc / draws,
  };
  out.pilot = pilot / draws;
  const choices: [StrategyValues["best"], number][] = [
    ["hold", out.hold], ["cut", out.cut], ["grow", out.grow], ["pilot", out.pilot],
  ];
  const best = choices.reduce((a, b) => (b[1] > a[1] ? b : a))[0];
  return { ...out, best };
}
