/**
 * Call list: the page a rep works from, so the properties that matter are the
 * ones a rep would notice -- the right territory from a shared link, visit
 * order, a reason on each row, and an export of exactly that list.
 */
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CallListResponse } from "@/lib/types";
import { CallList } from "./CallList";

const OPTIONS = [
  { territory: 3, n_hcps: 23066, n_targets: 2, workload: 165, opportunity: 671137, states: "CA" },
  { territory: 7, n_hcps: 9000, n_targets: 0, workload: 150, opportunity: 120000, states: "NV, UT" },
];

const ROW = {
  last_name: "OBATAKE", first_name: "SHARON", city: "BELLFLOWER", state: "CA", zip3: "907",
  specialty_group: "Other", class_fills: 2429, brand_share: 0, opportunity: 4865,
  opportunity_decile: 10, calls_per_month: 2, is_target: true, p_active: 0.11,
  forecast_lo: 11, forecast_mid: 26, forecast_hi: 81,
};

function respond(url: string): CallListResponse {
  const t = new URL(url, "http://x").searchParams.get("territory");
  if (t === null) return { n_reps: 60, options: OPTIONS, territory: null, rows: [] };
  const head = OPTIONS.find((o) => o.territory === Number(t)) ?? null;
  const rows = head?.territory === 3
    ? [
        { ...ROW, priority: 1, npi: 1, why: "Anticoagulant-focused practice: only 55 claims for other drugs (x3.59 potential)" },
        { ...ROW, priority: 2, npi: 2, last_name: "RHEEM", why: null, forecast_lo: null, forecast_hi: null, p_active: null },
      ]
    : [];
  return { n_reps: 60, options: OPTIONS, territory: head, rows };
}

function renderAt(path: string) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(respond(url)), { status: 200 })));
  const router = createMemoryRouter([{ path: "/app/calls", element: <CallList /> }],
    { initialEntries: [path] });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("CallList", () => {
  it("offers every territory when none is chosen", async () => {
    renderAt("/app/calls");
    expect(await screen.findByRole("heading", { name: /choose a territory/i })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^T3/ }).length).toBeGreaterThan(0);
  });

  it("opens the territory named in a shared link, in visit order with reasons", async () => {
    renderAt("/app/calls?t=3");
    const table = await screen.findByRole("table", { name: /visit order/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("OBATAKE");
    expect(rows[0]).toHaveTextContent(/Anticoagulant-focused practice/);
    expect(rows[0]).toHaveTextContent("11–81");
    expect(rows[1]).toHaveTextContent("RHEEM");
  });

  it("exports exactly the territory on screen", async () => {
    renderAt("/app/calls?t=3");
    const link = await screen.findByRole("link", { name: /export csv/i });
    expect(link.getAttribute("href")).toBe("/api/calllist/csv?territory=3&targets_only=true&n_reps=60");
  });

  it("offers a way out when a territory has no targets", async () => {
    renderAt("/app/calls?t=7");
    expect(await screen.findByText(/no targets in this territory/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /show every prescriber/i })).toBeInTheDocument();
  });

  it("says so when the territory in the link does not exist", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ n_reps: 60, options: OPTIONS, territory: null, rows: [] }), { status: 200 })));
    renderAt("/app/calls?t=999");
    expect(await screen.findByText(/does not exist/i)).toBeInTheDocument();
  });
});
