/**
 * Loading, error and empty states.
 *
 * These are built FIRST, before any page that uses them. A product whose
 * failure states are an afterthought fails in front of the person you were
 * trying to impress -- and on a free-tier host, the cold-start error is the
 * state an interviewer is most likely to see first.
 */

import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

/* ----------------------------------------------------------------- loading */

/**
 * Skeletons match the geometry of the real content, so the shape of the answer
 * is visible before the answer arrives and nothing shifts when it does.
 * Spinners communicate "wait"; skeletons communicate "here is what is coming".
 */
export function Skeleton({ w = "100%", h = 14, className = "" }: {
  w?: string | number;
  h?: string | number;
  className?: string;
}) {
  return (
    <div
      className={`skeleton ${className}`}
      style={{ width: w, height: h }}
      aria-hidden="true"
    />
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  const widths = ["92%", "76%", "84%", "61%", "70%"];
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} w={widths[i % widths.length] ?? "80%"} />
      ))}
    </div>
  );
}

export function SkeletonKpiRow({ n = 4 }: { n?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-4" role="status" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="card p-4">
          <Skeleton w="60%" h={10} />
          <div className="h-3" />
          <Skeleton w="45%" h={26} />
        </div>
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 12 }: { rows?: number }) {
  return (
    <div className="p-4" role="status" aria-label="Loading table">
      <Skeleton w="100%" h={28} className="mb-3" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} w="100%" h={20} className="mb-2" />
      ))}
    </div>
  );
}

export function SkeletonChart({ h = 200 }: { h?: number }) {
  return <Skeleton w="100%" h={h} className="rounded" />;
}

/* ------------------------------------------------------------------- error */

/**
 * Two genuinely different failures, two genuinely different messages.
 *
 * 503 means the data was never built -- the fix is a command the user can run.
 * Anything else usually means a sleeping free-tier host -- the fix is to wait.
 * Telling someone to "try again later" when they actually need to run `make`
 * is how a demo dies quietly.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;

  if (api?.isPipelineMissing) {
    return (
      <div
        role="alert"
        className="rounded border border-[var(--warn)]/40 bg-[var(--warn)]/[0.06] p-6"
      >
        <h3 className="text-h3 mb-2">Pipeline output missing</h3>
        <p className="text-small text-ink-mute max-w-prose">
          The API is running but the analysis has not been built yet. Run the
          pipeline, then reload:
        </p>
        <pre className="num mt-3 rounded bg-[var(--rule-soft)] p-3 text-small">
          python -m src.pipeline --synthetic --sample
        </pre>
        {api.detail && (
          <p className="text-micro text-ink-faint mt-3 font-mono">{api.detail}</p>
        )}
      </div>
    );
  }

  return (
    <div
      role="alert"
      className="rounded border border-[var(--neg)]/40 bg-[var(--neg)]/[0.06] p-6"
    >
      <h3 className="text-h3 mb-2">Can&apos;t reach the data service</h3>
      <p className="text-small text-ink-mute max-w-prose">
        It sleeps after 15 minutes of inactivity — retry in 30 seconds.
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded border border-[var(--rule)] px-3 py-1.5 text-small
                     transition-colors duration-instant hover:border-signal hover:text-signal"
        >
          Retry
        </button>
      )}
      {api?.detail && (
        <p className="text-micro text-ink-faint mt-3 font-mono">{api.detail}</p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- empty */

/**
 * An empty state says what happened AND what to do about it. "No results" is
 * a dead end; naming the filter most likely responsible is a way forward.
 */
export function EmptyState({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="px-6 py-16 text-center">
      <p className="text-body text-ink-mute">{title}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------- synthetic banner */

/**
 * Never dismissible, never hidden to make a screenshot look better. Publishing
 * a number without saying it came from data whose generating process assumed
 * the conclusion would be the single worst thing this project could do.
 */
export function SyntheticBanner({ mode, warning }: { mode: string; warning?: string | null }) {
  if (mode === "REAL") return null;
  return (
    <div
      role="status"
      className="mb-5 rounded border border-[var(--warn)]/45 bg-[var(--warn)]/[0.07] px-4 py-2.5 text-small"
    >
      <strong className="text-[var(--warn)]">Synthetic data.</strong>{" "}
      {warning ??
        "The generative process encodes the hypothesis the model tests, so confirming it here is circular by construction. This validates the pipeline, not the finding."}
    </div>
  );
}
