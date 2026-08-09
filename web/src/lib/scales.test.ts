/**
 * The two decile ramps are a rhetorical device AND an accessibility guarantee.
 *
 * Opportunity is chromatic; volume -- the industry default this project argues
 * against -- is neutral grey. A reader absorbs the argument before reading a
 * word, and because the two ramps differ in chroma rather than hue they stay
 * distinguishable under every form of colour blindness.
 *
 * If someone ever "brightens up" the volume ramp, both properties die at once.
 * These tests exist to stop that.
 */
import { describe, expect, it } from "vitest";

import { heatAlpha, linear, niceMax, onRampText, opportunityColor, volumeColor } from "./scales";

const hex = (c: string) => c.replace("#", "").toLowerCase();
const rgb = (c: string) => {
  const h = hex(c);
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ] as const;
};
/** Chroma proxy: how far the channels spread. Grey ~= 0. */
const chroma = (c: string) => {
  const [r, g, b] = rgb(c);
  return Math.max(r, g, b) - Math.min(r, g, b);
};
const luminance = (c: string) => {
  const [r, g, b] = rgb(c);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

describe("decile ramps", () => {
  it("returns a colour for every decile", () => {
    for (let d = 1; d <= 10; d++) {
      expect(opportunityColor(d)).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(volumeColor(d)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it("clamps out-of-range and missing deciles instead of throwing", () => {
    expect(opportunityColor(0)).toBe(opportunityColor(1));
    expect(opportunityColor(99)).toBe(opportunityColor(10));
    expect(opportunityColor(null)).toBe(opportunityColor(1));
    expect(opportunityColor(undefined)).toBe(opportunityColor(1));
    expect(opportunityColor(NaN)).toBe(opportunityColor(1));
  });

  it("darkens monotonically, so rank is readable without a legend", () => {
    for (let d = 1; d < 10; d++) {
      expect(luminance(opportunityColor(d))).toBeGreaterThan(
        luminance(opportunityColor(d + 1)));
      expect(luminance(volumeColor(d))).toBeGreaterThan(
        luminance(volumeColor(d + 1)));
    }
  });

  it("keeps the volume ramp NEUTRAL — the argument depends on it", () => {
    for (let d = 1; d <= 10; d++) {
      expect(chroma(volumeColor(d))).toBeLessThan(20);
    }
  });

  it("keeps the opportunity ramp CHROMATIC at the top of the scale", () => {
    expect(chroma(opportunityColor(8))).toBeGreaterThan(30);
    expect(chroma(opportunityColor(10))).toBeGreaterThan(30);
  });

  it("separates the two ramps by chroma, not hue — colour-blind safe", () => {
    for (let d = 6; d <= 10; d++) {
      expect(chroma(opportunityColor(d)) - chroma(volumeColor(d))).toBeGreaterThan(15);
    }
  });
});

describe("onRampText", () => {
  it("switches to light text once the swatch is dark", () => {
    expect(onRampText(2)).not.toBe("#FFFFFF");
    expect(onRampText(9)).toBe("#FFFFFF");
  });
});

describe("heatAlpha", () => {
  it("is transparent at zero and capped at the ceiling", () => {
    expect(heatAlpha(0, 100)).toContain("0.000");
    expect(heatAlpha(100, 100, 0.88)).toContain("0.880");
  });
  it("does not divide by zero", () => {
    expect(heatAlpha(5, 0)).toBe("transparent");
  });
});

describe("linear", () => {
  it("maps a domain onto a range", () => {
    const s = linear([0, 10], [0, 100]);
    expect(s(0)).toBe(0);
    expect(s(5)).toBe(50);
    expect(s(10)).toBe(100);
  });
  it("survives a degenerate domain instead of producing Infinity", () => {
    const s = linear([5, 5], [0, 100]);
    expect(Number.isFinite(s(5))).toBe(true);
  });
});

describe("niceMax", () => {
  it.each([[0.9, 1], [1.4, 2], [4.2, 5], [7.7, 10], [42, 50]])(
    "%f -> %i", (input, expected) => {
      expect(niceMax(input)).toBe(expected);
    });
  it("never returns zero, which would collapse an axis", () => {
    expect(niceMax(0)).toBeGreaterThan(0);
    expect(niceMax(-3)).toBeGreaterThan(0);
  });
});
