import type { Config } from "tailwindcss";

/**
 * Design tokens live HERE and in src/design/tokens.css -- never as arbitrary
 * values in components. If a value is worth using twice it is worth naming.
 *
 * Colours reference CSS custom properties rather than hard-coding hex, so the
 * story mode's per-act accent cross-fade works by transitioning one variable
 * instead of swapping class names on every element.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Story chassis (dark)
        void: "var(--void)",
        ground: "var(--ground)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        hairline: "var(--hairline)",
        "hairline-hi": "var(--hairline-hi)",
        "text-hi": "var(--text-hi)",
        "text-body": "var(--text)",
        "text-mute": "var(--text-mute)",
        "text-faint": "var(--text-faint)",

        // Tool chassis (light) -- "chart paper"
        paper: "var(--paper)",
        panel: "var(--panel)",
        rule: "var(--rule)",
        "rule-soft": "var(--rule-soft)",
        ink: "var(--ink)",
        "ink-mute": "var(--ink-mute)",
        "ink-faint": "var(--ink-faint)",
        signal: "var(--signal)",
        flag: "var(--flag)",

        // Semantic -- constant in every context, never art-directed
        pos: "var(--pos)",
        neg: "var(--neg)",
        warn: "var(--warn)",
        info: "var(--info)",

        // The live act accent
        accent: "var(--accent-core)",
        "accent-glow": "var(--accent-glow)",
      },
      fontFamily: {
        display: "var(--font-display)",
        ui: "var(--font-ui)",
        mono: "var(--font-mono)",
      },
      fontSize: {
        hero: ["var(--t-hero)", { lineHeight: "1.05", letterSpacing: "-0.03em" }],
        claim: ["var(--t-claim)", { lineHeight: "1.18", letterSpacing: "-0.02em" }],
        h1: ["var(--t-h1)", { lineHeight: "1.25", letterSpacing: "-0.015em" }],
        h2: ["var(--t-h2)", { lineHeight: "1.3", letterSpacing: "-0.01em" }],
        h3: ["var(--t-h3)", { lineHeight: "1.35" }],
        body: ["var(--t-body)", { lineHeight: "1.55" }],
        small: ["var(--t-small)", { lineHeight: "1.45" }],
        micro: ["var(--t-micro)", { lineHeight: "1.4", letterSpacing: "0.08em" }],
      },
      spacing: {
        1: "4px", 2: "8px", 3: "12px", 4: "16px", 6: "24px",
        8: "32px", 12: "48px", 16: "64px", 24: "96px", 32: "128px", 48: "192px",
      },
      borderRadius: { sm: "4px", DEFAULT: "6px", lg: "10px" },
      transitionDuration: {
        instant: "90ms", quick: "160ms", base: "260ms",
        slow: "480ms", cine: "900ms", epic: "1600ms",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
        "in-out": "cubic-bezier(0.65, 0, 0.35, 1)",
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      maxWidth: { content: "1440px", prose: "76ch", lede: "46ch" },
    },
  },
  plugins: [],
} satisfies Config;
