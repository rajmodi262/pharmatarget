/**
 * Tool-mode shell: a plum rail with the wordmark, numbered sections, and the
 * blush paper for content.
 *
 * Sections are numbered rather than iconed. The numbers give the reader the
 * order of the argument -- answer, case, decision, then the instruments that
 * back it -- which an icon cannot.
 */

import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

const NAV = [
  { to: "/app", label: "Overview", end: true, hint: "The answer" },
  { to: "/app/case", label: "The Case", hint: "Issue tree · red team · roadmap" },
  { to: "/app/lab", label: "Decision Lab", hint: "Drag the assumptions" },
  { to: "/app/models", label: "Model Lab", hint: "Evaluation · uncertainty · causal ML" },
  { to: "/app/targets", label: "Targets", hint: "Prescriber list" },
  { to: "/app/territories", label: "Territories", hint: "Alignment map" },
  { to: "/app/response", label: "Response", hint: "Promotion evidence" },
  { to: "/app/method", label: "Method", hint: "Data and gates" },
];

export function AppShell() {
  // Its own cache key -- reusing qk.meta here would collide with the Method
  // route's /api/meta query (two response shapes under one key).
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    staleTime: 60_000,
    retry: 1,
  });
  const loc = useLocation();

  return (
    <div className="grain flex min-h-screen bg-paper text-ink">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50
                   focus:rounded focus:bg-panel focus:px-3 focus:py-2 focus:text-small"
      >
        Skip to content
      </a>

      <nav
        aria-label="Sections"
        className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col overflow-hidden py-7 md:flex"
        style={{
          background:
            "radial-gradient(120% 50% at 0% 0%, rgba(199,90,58,.35), transparent 60%), radial-gradient(90% 40% at 100% 100%, rgba(195,160,167,.22), transparent 60%), var(--plum)",
          color: "var(--text-hi)",
        }}
      >
        <div className="px-7">
          <Link to="/" className="block no-underline" style={{ color: "var(--text-hi)" }}>
            <span className="display block text-[30px] leading-[0.9]">Pharma</span>
            <span className="display block text-[30px] leading-[0.9]" style={{ color: "var(--terracotta-hi)" }}>
              Target<span style={{ color: "var(--mauve)" }}>.</span>
            </span>
          </Link>
          <p className="serif-i mt-3 text-[15px] leading-snug" style={{ color: "var(--text-mute)" }}>
            Field-force strategy for a branded DOAC
          </p>
        </div>

        <ul className="mt-8 flex flex-col">
          {NAV.map((item, i) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className="group relative flex items-baseline gap-3 px-7 py-2.5 no-underline transition-colors duration-quick"
                style={({ isActive }) => ({
                  color: isActive ? "var(--text-hi)" : "var(--text-mute)",
                  background: isActive ? "rgba(248,238,234,.07)" : undefined,
                })}
              >
                {({ isActive }) => (
                  <>
                    <span
                      className="absolute inset-y-1 left-0 w-[3px] rounded-r transition-all duration-base ease-out"
                      style={{
                        background: "var(--terracotta)",
                        transform: isActive ? "scaleY(1)" : "scaleY(0)",
                      }}
                    />
                    <span className="num text-[10px]" style={{ color: isActive ? "var(--terracotta-hi)" : "var(--text-faint)" }}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span>
                      <span className="block text-[14px] font-medium group-hover:text-[var(--text-hi)]">{item.label}</span>
                      <span className="block text-[11px]" style={{ color: "var(--text-faint)" }}>{item.hint}</span>
                    </span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="mt-auto space-y-3 px-7">
          <Link
            to="/brief"
            className="flex items-center justify-between rounded-full border px-4 py-2 text-small no-underline transition-colors duration-quick hover:bg-white/10"
            style={{ borderColor: "rgba(248,238,234,.3)", color: "var(--text-hi)" }}
          >
            Present the brief <span aria-hidden>▶</span>
          </Link>
          <Link
            to="/story"
            className="flex items-center justify-between rounded-full px-4 py-2 text-small no-underline transition-transform duration-quick hover:scale-[1.02]"
            style={{ background: "var(--terracotta)", color: "#fff" }}
          >
            Watch the story <span aria-hidden>→</span>
          </Link>
          {health && (
            <p className="flex items-center gap-2 text-[11px]" style={{ color: "var(--text-faint)" }}>
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
                  style={{ background: health.data_mode === "REAL" ? "#7fc08f" : "var(--warn)" }} />
                <span className="relative inline-flex h-2 w-2 rounded-full"
                  style={{ background: health.data_mode === "REAL" ? "#7fc08f" : "var(--warn)" }} />
              </span>
              {health.data_mode === "REAL" ? "Live on real CMS data" : `Data mode ${health.data_mode}`}
            </p>
          )}
        </div>
      </nav>

      {/* Mobile nav: horizontal scroller, since the rail is unusable at 375px */}
      <nav
        aria-label="Sections"
        className="fixed inset-x-0 top-0 z-40 flex gap-1 overflow-x-auto px-3 py-2 md:hidden"
        style={{ background: "var(--plum)" }}
      >
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className="whitespace-nowrap rounded-full px-3 py-1.5 text-small no-underline"
            style={({ isActive }) => ({
              background: isActive ? "var(--terracotta)" : "transparent",
              color: isActive ? "#fff" : "var(--text-mute)",
            })}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main
        id="main"
        key={loc.pathname}
        className="mx-auto w-full min-w-0 max-w-content flex-1 px-4 pb-24 pt-16 sm:px-8 md:pt-10"
        style={{ animation: "page-in 600ms cubic-bezier(.16,1,.3,1)" }}
      >
        <Outlet />
      </main>
      <style>{`@keyframes page-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  );
}
