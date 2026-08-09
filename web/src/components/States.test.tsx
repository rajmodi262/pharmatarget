/**
 * Failure and disclosure states.
 *
 * These are the components most likely to be on screen at the worst possible
 * moment -- a cold-started host during a demo, or a checkout where the pipeline
 * has never been run. Two properties matter more than anything visual:
 *
 *   1. A 503 (pipeline not built) and a network failure are DIFFERENT problems
 *      with different fixes. Collapsing them into "something went wrong" wastes
 *      the user's time on exactly the two occasions they most need direction.
 *   2. The synthetic-data banner must never be suppressible. Publishing a
 *      number without saying it came from data whose generating process assumed
 *      the conclusion would undermine the entire project.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { EmptyState, ErrorState, SyntheticBanner } from "./States";

describe("ErrorState", () => {
  it("tells the user to run the pipeline on a 503", () => {
    render(<ErrorState error={new ApiError("Pipeline output missing.", 503)} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/pipeline output missing/i)).toBeInTheDocument();
    expect(screen.getByText(/src\.pipeline/)).toBeInTheDocument();
  });

  it("tells the user the host is asleep on a network failure", () => {
    render(<ErrorState error={new ApiError("Can't reach the data service.", 0)} />);
    expect(screen.getByText(/sleeps after 15 minutes/i)).toBeInTheDocument();
  });

  it("distinguishes the two — they have different fixes", () => {
    const { unmount } = render(
      <ErrorState error={new ApiError("Pipeline output missing.", 503)} />);
    const pipelineCopy = screen.getByRole("alert").textContent ?? "";
    unmount();
    render(<ErrorState error={new ApiError("unreachable", 0)} />);
    expect(screen.getByRole("alert").textContent).not.toBe(pipelineCopy);
  });

  it("offers a retry that actually retries", async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new ApiError("unreachable", 0)} onRetry={onRetry} />);
    screen.getByRole("button", { name: /retry/i }).click();
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("handles a non-ApiError without crashing", () => {
    render(<ErrorState error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

describe("SyntheticBanner", () => {
  it("warns when the data is synthetic", () => {
    render(<SyntheticBanner mode="SYNTHETIC" />);
    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
    expect(screen.getByText(/circular by construction/i)).toBeInTheDocument();
  });

  it("says nothing when the data is real", () => {
    const { container } = render(<SyntheticBanner mode="REAL" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders no dismiss control — this must not be suppressible", () => {
    render(<SyntheticBanner mode="SYNTHETIC" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("EmptyState", () => {
  it("says what happened and offers a way forward", () => {
    render(
      <EmptyState
        title="No prescribers match these filters."
        action={<button type="button">Clear filters</button>}
      />,
    );
    expect(screen.getByText(/no prescribers match/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear filters/i })).toBeInTheDocument();
  });
});
