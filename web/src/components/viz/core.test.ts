import { describe, expect, it } from "vitest";

import { last, linePath, normCdf, smoothPath } from "./core";

describe("normCdf", () => {
  it("matches standard normal reference values", () => {
    expect(normCdf(0)).toBeCloseTo(0.5, 6);
    expect(normCdf(1.959964)).toBeCloseTo(0.975, 4);
    expect(normCdf(-1.959964)).toBeCloseTo(0.025, 4);
    expect(normCdf(0.841621)).toBeCloseTo(0.8, 4);
  });

  it("is monotone and bounded", () => {
    let prev = 0;
    for (let x = -6; x <= 6; x += 0.25) {
      const v = normCdf(x);
      expect(v).toBeGreaterThanOrEqual(prev);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
      prev = v;
    }
  });
});

describe("paths", () => {
  it("linePath starts with a move and joins with lines", () => {
    expect(linePath([[0, 0], [10, 5]])).toBe("M0.0 0.0 L10.0 5.0");
  });

  it("smoothPath passes through every point", () => {
    const pts: [number, number][] = [[0, 0], [10, 10], [20, 5], [30, 15]];
    const d = smoothPath(pts);
    expect(d.startsWith("M0.0 0.0")).toBe(true);
    for (const [x, y] of pts.slice(1)) {
      expect(d).toContain(`${x.toFixed(1)} ${y.toFixed(1)}`);
    }
  });

  it("falls back to a line for two points", () => {
    expect(smoothPath([[0, 0], [1, 1]])).toBe(linePath([[0, 0], [1, 1]]));
  });
});

describe("last", () => {
  it("returns the final element or undefined", () => {
    expect(last([1, 2, 3])).toBe(3);
    expect(last([])).toBeUndefined();
  });
});
