/**
 * Tool-mode shell: fixed left rail, no icons, content column.
 *
 * Six nav items with labels only. Icons on six text items are decoration --
 * they add visual noise and no information, and "Territories" is not clearer
 * with a pin next to it.
 */

import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

const NAV = [
  { to: "/app", label: "Overview", end: true },
  { to: "/app/targets", label: "Targets" },
  { to: "/app/territories", label: "Territories" },
  { to: "/app/response", label: "Response" },
  { to: "/app/method", label: "Method" },
];

export function AppShell() {
  // Health is cheap and tells the rail whether we are on real or synthetic
  // data. It deliberately does not block rendering.
  //
  // Its own cache key -- reusing qk.meta here would collide with the Method
  // route's /api/meta query: two different response shapes under one key, so
  // whichever resolved last would win and the other would render garbage.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    staleTime: 60_000,
    retry: 1,
  });

  return (
    <div className="flex min-h-screen bg-paper text-ink">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50
                   focus:rounded focus:bg-panel focus:px-3 focus:py-2 focus:text-small"
      >
        Skip to content
      </a>

      <nav
        aria-label="Sections"
        className="sticky top-0 hidden h-screen w-[220px] shrink-0 flex-col
                   border-r border-rule bg-panel py-6 md:flex"
      >
        <div className="px-6">
          <h1 className="text-[15px] font-semibold tracking-tight">PharmaTarget</h1>
          <p className="text-micro text-ink-mute mt-1 normal-case tracking-normal leading-snug">
            Northwind Pharma
            <br />
            DOAC field planning
          </p>
        </div>

        <ul className="mt-7 flex flex-col">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  [
                    "block px-6 py-2 text-small transition-colors duration-instant",
                    isActive
                      ? "font-medium text-signal shadow-[inset_2px_0_0_var(--signal)]"
                      : "text-ink-mute hover:bg-rule-soft hover:text-ink",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="mt-auto px-6">
          {health && (
            <p className="text-micro text-ink-faint normal-case tracking-normal">
              Data mode{" "}
              <span
                className="num"
                style={{ color: health.data_mode === "REAL" ? "var(--pos)" : "var(--warn)" }}
              >
                {health.data_mode}
              </span>
            </p>
          )}
        </div>
      </nav>

      {/* Mobile nav: horizontal scroller, since a 220px rail is unusable at 375px */}
      <nav
        aria-label="Sections"
        className="fixed inset-x-0 top-0 z-40 flex gap-1 overflow-x-auto border-b
                   border-rule bg-panel px-3 py-2 md:hidden"
      >
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              [
                "whitespace-nowrap rounded px-3 py-1.5 text-small transition-colors duration-instant",
                isActive ? "bg-rule-soft font-medium text-signal" : "text-ink-mute",
              ].join(" ")
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main
        id="main"
        className="mx-auto w-full max-w-content flex-1 px-6 pb-24 pt-16 md:pt-8"
      >
        <Outlet />
      </main>
    </div>
  );
}
