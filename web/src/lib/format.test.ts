/**
 * Number formatting is the single choke point every figure in the product
 * passes through, so a bug here is a bug on every screen at once.
 *
 * The rule these tests exist to protect: a MISSING value and a ZERO value must
 * never render the same way. A UI that shows "0" for "we don't know" is lying
 * quietly, and this project's whole argument rests on not doing that.
 */
import { describe, expect, it } from "vitest";

import {
  MISSING_GLYPH, compact, fmt, humanise, mult, personName, pct, pp, signed, stat, usd,
} from "./format";

describe("missing vs zero", () => {
  it.each([null, undefined, NaN, Infinity, -Infinity])(
    "renders %s as the missing glyph, not a number", (v) => {
      expect(fmt(v as number)).toBe(MISSING_GLYPH);
      expect(pct(v as number)).toBe(MISSING_GLYPH);
      expect(usd(v as number)).toBe(MISSING_GLYPH);
      expect(compact(v as number)).toBe(MISSING_GLYPH);
      expect(mult(v as number)).toBe(MISSING_GLYPH);
      expect(stat(v as number)).toBe(MISSING_GLYPH);
    });

  it("renders a real zero as zero", () => {
    expect(fmt(0)).toBe("0");
    expect(pct(0)).toBe("0.0%");
    expect(usd(0)).toBe("$0");
  });

  it("never confuses the two", () => {
    expect(fmt(0)).not.toBe(fmt(null));
  });
});

describe("fmt", () => {
  it("groups thousands", () => {
    expect(fmt(1380665)).toBe("1,380,665");
  });
  it("honours fixed decimals", () => {
    expect(fmt(1.5, 2)).toBe("1.50");
  });
  it("handles negatives", () => {
    expect(fmt(-8389)).toBe("-8,389");
  });
});

describe("compact", () => {
  it.each([
    [1_380_665, "1.4M"],
    [267_171, "267.2k"],
    [8_389, "8.4k"],
    [2_400_000_000, "2.4B"],
  ])("%i -> %s", (input, expected) => {
    expect(compact(input)).toBe(expected);
  });

  it("leaves small integers alone", () => {
    expect(compact(60)).toBe("60");
  });
});

describe("pct", () => {
  it("converts a fraction", () => {
    expect(pct(0.594)).toBe("59.4%");
  });
  it("accepts an already-percent value", () => {
    expect(pct(59.4, 1, true)).toBe("59.4%");
  });
  it("honours precision", () => {
    expect(pct(0.031, 0)).toBe("3%");
  });
});

describe("pp — percentage points, always signed", () => {
  it("signs positives so direction is unambiguous", () => {
    expect(pp(0.042)).toBe("+4.2pp");
  });
  it("signs negatives", () => {
    expect(pp(-0.117)).toBe("-11.7pp");
  });
});

describe("usd", () => {
  it.each([
    [62_124_183, "$62.1M"],
    [15_000_000, "$15.0M"],
    [250_000, "$250,000"],
    [-2_200_000, "-$2.2M"],
  ])("%i -> %s", (input, expected) => {
    expect(usd(input)).toBe(expected);
  });
});

describe("mult / stat / signed", () => {
  it("renders a multiplier with the times sign", () => {
    expect(mult(1.5)).toBe("1.50×");
  });
  it("quotes statistics at three decimals", () => {
    expect(stat(0.9273)).toBe("0.927");
  });
  it("always signs a delta", () => {
    expect(signed(30)).toBe("+30");
    expect(signed(-496)).toBe("-496");
  });
});

describe("personName", () => {
  it("formats surname and initial", () => {
    expect(personName("PATEL", "PRIYA")).toBe("PATEL, P.");
  });
  it("survives a missing first name", () => {
    expect(personName("SQUIBB", null)).toBe("SQUIBB");
  });
  it("returns the missing glyph when both are absent", () => {
    expect(personName(null, undefined)).toBe(MISSING_GLYPH);
  });
});

describe("humanise", () => {
  it("turns a config key into a label", () => {
    expect(humanise("rep_cost_annual")).toBe("Rep cost annual");
  });
});
