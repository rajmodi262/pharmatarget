/**
 * The prescriber field -- the visual spine of the story.
 *
 * EVERY PARTICLE IS A REAL PRESCRIBER, sampled from /api/hcp-sample. The same
 * points are re-arranged by each act rather than being replaced, so the viewer
 * carries one population through the whole argument: noise, then ranked, then
 * split, then ignited, then geographic. That continuity is what makes it read
 * as authored rather than as five separate graphics.
 *
 * WHY CANVAS 2D AND NOT WEBGL
 * ---------------------------
 * 24,000 points at 60fps is comfortably inside canvas 2D if you avoid the
 * things that make it slow: no per-point objects, no save/restore per point, no
 * arc() calls. Positions live in flat Float32Arrays, points are drawn as
 * 1-3px fillRect runs batched by colour, and layout targets are recomputed only
 * when the act changes rather than every frame. That keeps the whole story
 * dependency-free -- no 600 KB of three.js on a page whose job is to be
 * instantly readable -- and it degrades to a static frame with two lines of
 * code when prefers-reduced-motion is set.
 *
 * The animation is a spring toward per-act targets, so acts blend into each
 * other during a scrub instead of cutting. Scrubbing backwards looks correct
 * because the target set is a pure function of the act index.
 */

import { useEffect, useRef } from "react";

export interface FieldData {
  n: number;
  universe: number;
  opportunity_decile: number[];
  volume_decile: number[];
  brand_share: number[];
  class_fills: number[];
  opportunity: number[];
  lat: number[];
  lon: number[];
}

/** Chromatic ramp -- the ranking this project argues FOR. */
const OPP_RAMP = [
  "#EEF3F8", "#DCE6F1", "#C4D6EA", "#A6C2E0", "#83AAD4",
  "#5F91C7", "#4176B4", "#2A5C9B", "#17437B", "#0A2C5C",
];
/** Neutral ramp -- the industry default it argues AGAINST. */
const VOL_RAMP = [
  "#3A3A38", "#474542", "#57534E", "#66615C", "#767068",
  "#8C8681", "#A29C96", "#B8B2AC", "#CFC9C3", "#E7E1DB",
];

export type ActLayout = "noise" | "volume" | "split" | "ignite" | "geo";

export function ParticleField({
  data,
  layout,
  progress,
  reducedMotion,
}: {
  data: FieldData | null;
  layout: ActLayout;
  progress: number;
  reducedMotion: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<{
    x: Float32Array; y: Float32Array;
    tx: Float32Array; ty: Float32Array;
    vx: Float32Array; vy: Float32Array;
    size: Float32Array; colour: string[];
    layout: ActLayout | null; w: number; h: number;
  } | null>(null);
  const layoutRef = useRef(layout);
  const progressRef = useRef(progress);
  layoutRef.current = layout;
  progressRef.current = progress;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data || data.n === 0) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;
    let running = true;

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(r.width * dpr));
      canvas.height = Math.max(1, Math.floor(r.height * dpr));
      if (stateRef.current) {
        stateRef.current.w = r.width;
        stateRef.current.h = r.height;
        stateRef.current.layout = null;   // force target recompute
      }
    };

    const n = data.n;
    const rect = canvas.getBoundingClientRect();
    const st = {
      x: new Float32Array(n), y: new Float32Array(n),
      tx: new Float32Array(n), ty: new Float32Array(n),
      vx: new Float32Array(n), vy: new Float32Array(n),
      size: new Float32Array(n), colour: new Array<string>(n),
      layout: null as ActLayout | null,
      w: rect.width, h: rect.height,
    };
    stateRef.current = st;

    // Deterministic jitter -- the field must look identical on every reload,
    // or a screen recording cannot be re-shot to match.
    const rnd = (i: number, salt: number) => {
      const v = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453;
      return v - Math.floor(v);
    };

    for (let i = 0; i < n; i++) {
      st.x[i] = rnd(i, 1) * st.w;
      st.y[i] = rnd(i, 2) * st.h;
      st.size[i] = 1 + Math.min(2, Math.sqrt((data.class_fills[i] ?? 1) / 400));
    }

    const computeTargets = (l: ActLayout) => {
      const W = st.w, H = st.h;
      const pad = 48;
      const iw = W - pad * 2, ih = H - pad * 2;

      for (let i = 0; i < n; i++) {
        const od = data.opportunity_decile[i] ?? 1;
        const vd = data.volume_decile[i] ?? 1;

        if (l === "noise") {
          st.tx[i] = rnd(i, 3) * W;
          st.ty[i] = rnd(i, 4) * H;
          st.colour[i] = "rgba(124,138,156,0.55)";
        } else if (l === "volume") {
          // Ranked columns, greyscale: order without insight.
          const col = vd - 1;
          st.tx[i] = pad + (col + 0.5) * (iw / 10) + (rnd(i, 5) - 0.5) * (iw / 11);
          st.ty[i] = pad + rnd(i, 6) * ih;
          st.colour[i] = VOL_RAMP[col] ?? VOL_RAMP[0]!;
        } else if (l === "split") {
          // Volume rank on the left, opportunity rank on the right. Particles
          // whose rank moves are the argument, so they alone stay bright.
          const half = iw / 2;
          const moved = Math.abs(od - vd) >= 2;
          const onRight = rnd(i, 7) > 0.5;
          const d = onRight ? od : vd;
          st.tx[i] = pad + (onRight ? half + 24 : 0)
            + ((d - 1) + 0.5) * ((half - 24) / 10)
            + (rnd(i, 8) - 0.5) * (half / 13);
          st.ty[i] = pad + rnd(i, 9) * ih;
          st.colour[i] = moved
            ? (onRight ? (OPP_RAMP[od - 1] ?? "#5F91C7") : "#C77A22")
            : "rgba(90,102,118,0.16)";
        } else if (l === "ignite") {
          // Opportunity-ranked; the top three deciles bloom, the rest recede.
          const col = od - 1;
          st.tx[i] = pad + (col + 0.5) * (iw / 10) + (rnd(i, 10) - 0.5) * (iw / 11);
          st.ty[i] = pad + rnd(i, 11) * ih;
          st.colour[i] = od >= 8
            ? (OPP_RAMP[col] ?? "#0A2C5C")
            : "rgba(90,102,118,0.13)";
        } else {
          // Geographic. Equirectangular with a cos(lat) correction -- honest
          // enough at CONUS scale and free of a projection dependency.
          const lon = data.lon[i] ?? -96, lat = data.lat[i] ?? 38;
          const nx = (lon + 125) / 59;
          const ny = 1 - (lat - 24) / 26;
          const sc = Math.min(iw, ih * 1.7);
          st.tx[i] = W / 2 + (nx - 0.5) * sc;
          st.ty[i] = H / 2 + (ny - 0.5) * sc * 0.58;
          st.colour[i] = OPP_RAMP[od - 1] ?? "#4176B4";
        }
      }
      st.layout = l;
    };

    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const draw = () => {
      const W = st.w, H = st.h;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      // Batch by colour: one fillStyle assignment per distinct colour instead
      // of 24,000. This is the difference between 60fps and 12.
      const buckets = new Map<string, number[]>();
      for (let i = 0; i < n; i++) {
        const c = st.colour[i] ?? "#5F91C7";
        let b = buckets.get(c);
        if (!b) { b = []; buckets.set(c, b); }
        b.push(i);
      }
      for (const [colour, idx] of buckets) {
        ctx.fillStyle = colour;
        for (const i of idx) {
          const s = st.size[i] ?? 1;
          ctx.fillRect(st.x[i]! - s / 2, st.y[i]! - s / 2, s, s);
        }
      }
    };

    const step = () => {
      if (!running) return;
      const l = layoutRef.current;
      if (st.layout !== l) computeTargets(l);

      if (reducedMotion) {
        for (let i = 0; i < n; i++) { st.x[i] = st.tx[i]!; st.y[i] = st.ty[i]!; }
        draw();
        return;                                   // static frame, no loop
      }

      // Critically-damped-ish spring. Stiffness rises slightly with scroll
      // progress so a fast scrub settles quickly instead of trailing.
      const k = 0.055 + 0.05 * progressRef.current;
      const damp = 0.86;
      for (let i = 0; i < n; i++) {
        st.vx[i] = (st.vx[i]! + (st.tx[i]! - st.x[i]!) * k) * damp;
        st.vy[i] = (st.vy[i]! + (st.ty[i]! - st.y[i]!) * k) * damp;
        st.x[i] = st.x[i]! + st.vx[i]!;
        st.y[i] = st.y[i]! + st.vy[i]!;
      }
      draw();
      raf = requestAnimationFrame(step);
    };

    resize();
    window.addEventListener("resize", resize);
    step();

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [data, reducedMotion]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 h-full w-full"
      aria-hidden="true"
    />
  );
}
