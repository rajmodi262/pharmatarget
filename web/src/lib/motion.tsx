/**
 * Motion primitives: reveal-on-scroll, tweened numbers, count-up.
 *
 * Hand-rolled on IntersectionObserver and requestAnimationFrame rather than a
 * motion library -- the whole set is ~100 lines and every chart needs only
 * these three ideas: arrive once, interpolate a value, never move for a reader
 * who asked the OS for reduced motion.
 */

import { useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from "react";

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * True once the element has scrolled into view (and stays true).
 *
 * The ref is an object whose `current` setter is tracked, so observation
 * starts whenever the element ATTACHES -- including a component that first
 * renders nothing while its data loads. A plain useRef read once in an effect
 * misses that case and leaves the chart invisible forever.
 */
export function useInView<T extends Element>(threshold = 0.2) {
  const [node, setNode] = useState<T | null>(null);
  const ref = useMemo(() => {
    let cur: T | null = null;
    return {
      get current() { return cur; },
      set current(v: T | null) { cur = v; setNode(v); },
    } as MutableRefObject<T | null>;
  }, []);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = node;
    if (!el || inView) return;
    if (typeof IntersectionObserver === "undefined" || prefersReducedMotion()) {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          io.disconnect();
        }
      },
      { threshold },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [node, inView, threshold]);
  return [ref, inView] as const;
}

const easeOut = (t: number) => 1 - (1 - t) ** 3;

/**
 * Animate towards `target` whenever it changes. Starts from the previous value,
 * so dragging a slider glides rather than jumping back to zero each time.
 */
export function useTween(target: number, duration = 700, enabled = true): number {
  const [value, setValue] = useState(enabled ? 0 : target);
  const from = useRef(value);
  const raf = useRef<number>();

  useEffect(() => {
    if (!Number.isFinite(target)) return;
    if (!enabled || prefersReducedMotion()) {
      from.current = target;
      setValue(target);
      return;
    }
    const start = performance.now();
    const v0 = from.current;
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const v = v0 + (target - v0) * easeOut(t);
      from.current = v;
      setValue(v);
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [target, duration, enabled]);

  return value;
}

/** A number that counts up when it first scrolls into view. */
export function CountUp({ value, format, duration = 1400 }: {
  value: number | null | undefined;
  format: (v: number) => string;
  duration?: number;
}) {
  const [ref, inView] = useInView<HTMLSpanElement>(0.4);
  const v = useTween(inView && value != null ? value : 0, duration, true);
  return (
    <span ref={ref} className="num">
      {value == null || !Number.isFinite(value) ? "–" : format(inView ? v : 0)}
    </span>
  );
}

/** Rise-in wrapper. `delay` staggers siblings. */
export function Reveal({ children, delay = 0, className = "", as: Tag = "div" }: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "section" | "li" | "article";
}) {
  const [ref, inView] = useInView<HTMLDivElement>(0.12);
  return (
    <Tag
      ref={ref as never}
      className={`reveal ${inView ? "in" : ""} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}
