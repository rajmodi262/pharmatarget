import { describe, expect, it } from "vitest";

import { Economy, posteriorMean, rng, strategyValues, type Grid, type Params } from "./decisionMath";

const grid: Grid[] = Array.from({ length: 26 }, (_, i) => {
  const n = 40 + 2 * i;
  return { n_reps: n, contribution_per_ceiling: 2e9 * (1 - Math.exp(-n / 60)), field_cost: n * 250_000 };
});
const p: Params = {
  current: 60, cReq: 0.02, seC: 0.006, hire: 60_000, rampMonths: 6, separation: 50_000,
  holdoutCostFraction: 0.085, pilotMonths: 6,
};

describe("Economy", () => {
  it("values holding at zero", () => {
    const e = new Economy(grid, p);
    expect(e.value(e.i0, 0.05, 2)).toBeCloseTo(0, 6);
  });
  it("prefers cutting when calls do nothing and growing when they do a lot", () => {
    const e = new Economy(grid, p);
    expect(e.reps[e.best(0, 2)]).toBe(40);
    expect(e.reps[e.best(1, 2)]).toBe(90);
  });
});

describe("posteriorMean", () => {
  it("shrinks a high reading towards the prior", () => {
    const f = posteriorMean(0.02, 1, 0.01);
    expect(f(0.2)).toBeLessThan(0.2);
    expect(f(0.2)).toBeGreaterThan(0.02);
  });
});

describe("strategyValues", () => {
  it("is deterministic for a seed and picks a valid best", () => {
    const e = new Economy(grid, p);
    const a = strategyValues(e, p, 1, 1, 2, 400, 3);
    const b = strategyValues(e, p, 1, 1, 2, 400, 3);
    expect(a).toEqual(b);
    expect(["hold", "cut", "grow", "pilot"]).toContain(a.best);
    expect(a.pilotCost).toBeGreaterThan(0);
  });
  it("rng is uniform-ish", () => {
    const r = rng(1);
    let s = 0;
    for (let i = 0; i < 5000; i++) s += r();
    expect(s / 5000).toBeGreaterThan(0.45);
    expect(s / 5000).toBeLessThan(0.55);
  });
});
