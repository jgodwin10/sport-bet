import { useEffect } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { getToken, setToken } from "../api/client";
import { useMe } from "../api/hooks";
import { Icon, type IconName } from "./icons";
import { cx } from "./ui";

const NAV: { to: string; label: string; short: string; icon: IconName }[] = [
  { to: "/", label: "Matches", short: "Matches", icon: "dashboard" },
  { to: "/predictions", label: "Value picks", short: "Picks", icon: "target" },
  { to: "/teams", label: "Teams", short: "Teams", icon: "shield" },
  { to: "/performance", label: "Track record", short: "Record", icon: "chart" },
  { to: "/settings", label: "Settings", short: "Settings", icon: "sliders" },
];

/** Soft colour fields behind the glass. Fixed, decorative, and cheap (pure CSS gradients). */
function Ambient() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_-10%,#0f1f3d_0%,#060b18_55%)]" />
      <div className="absolute -top-40 -left-32 h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle,rgba(34,197,94,0.22),transparent_65%)] blur-2xl" />
      <div className="absolute top-[10%] -right-40 h-[560px] w-[560px] rounded-full bg-[radial-gradient(circle,rgba(59,130,246,0.20),transparent_65%)] blur-2xl" />
      <div className="absolute bottom-[-20%] left-[20%] h-[600px] w-[600px] rounded-full bg-[radial-gradient(circle,rgba(139,92,246,0.12),transparent_65%)] blur-2xl" />
      <div className="absolute inset-0 opacity-[0.035] bg-[linear-gradient(rgba(255,255,255,0.6)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.6)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
    </div>
  );
}

function Brand() {
  return (
    <NavLink to="/" className="flex items-center gap-2.5 min-w-0 shrink-0" aria-label="Matchline home">
      <span className="grid place-items-center h-9 w-9 rounded-xl bg-gradient-to-br from-brand-strong to-brand-deep text-[#052e16] shadow-glow">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M4 17l5-6 4 3 7-8" />
        </svg>
      </span>
      <span className="text-[17px] font-extrabold tracking-[-0.02em]">Matchline</span>
    </NavLink>
  );
}

function Account() {
  const me = useMe(!!getToken());
  const qc = useQueryClient();
  const nav = useNavigate();
  if (!me.data) {
    return <NavLink to="/login" className="btn btn-sm"><Icon name="login" size={14} />Sign in</NavLink>;
  }
  return (
    <div className="flex items-center gap-2">
      <span className="hidden md:block text-right leading-tight">
        <span className="block text-xs font-semibold text-ink truncate max-w-[160px]">{me.data.email}</span>
        <span className="block text-2xs text-ink-3 capitalize">{me.data.role}</span>
      </span>
      <span className="grid place-items-center h-8 w-8 rounded-full bg-brand-soft text-brand-strong text-xs font-bold ring-1 ring-brand/30">
        {me.data.email[0].toUpperCase()}
      </span>
      <button className="btn btn-ghost btn-sm btn-icon" aria-label="Sign out"
              onClick={() => { setToken(null); qc.clear(); nav("/"); }}>
        <Icon name="logout" size={15} />
      </button>
    </div>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return (
    <div className="relative min-h-[100dvh]">
      <Ambient />

      {/* Top bar: full nav on desktop, brand + account on mobile */}
      <header className="sticky top-0 z-30 px-3 sm:px-6 pt-3">
        <div className="glass-strong mx-auto max-w-[1240px] flex items-center gap-4 h-14 sm:h-16 rounded-full pl-3 pr-2 sm:pl-4 sm:pr-3">
          <Brand />
          <nav aria-label="Main" className="hidden lg:flex items-center gap-1 mx-auto">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"}
                className={({ isActive }) => cx("flex items-center gap-2 h-10 px-4 rounded-full text-[13.5px] font-semibold transition-all",
                  isActive ? "bg-white text-night" : "text-ink-2 hover:text-ink hover:bg-white/[0.07]")}>
                <Icon name={n.icon} size={16} />{n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto lg:ml-0"><Account /></div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1240px] px-4 sm:px-6 pt-6 sm:pt-10 pb-32 lg:pb-16">
        <Outlet />
        <footer className="mt-16 text-center text-xs text-ink-4 leading-relaxed max-w-2xl mx-auto">
          Predictions are statistical estimates, never guarantees. Matchline does not place bets.
          If gambling stops being fun, get free help at{" "}
          <a className="text-ink-3 underline underline-offset-2 hover:text-ink" href="https://www.begambleaware.org" target="_blank" rel="noreferrer">BeGambleAware</a>.
        </footer>
      </main>

      {/* Mobile bottom tabs */}
      <nav aria-label="Main" className="lg:hidden fixed bottom-0 inset-x-0 z-30 px-3 pb-3 safe-bottom">
        <div className="glass-strong grid grid-cols-5 rounded-[26px] p-1.5">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => cx("relative flex flex-col items-center justify-center gap-1 h-[58px] rounded-[20px] text-[11px] font-semibold transition-all",
                isActive ? "bg-white/[0.1] text-ink" : "text-ink-3 active:bg-white/[0.05]")}>
              {({ isActive }) => (
                <>
                  <Icon name={n.icon} size={21} className={isActive ? "text-brand-strong" : ""} />
                  {n.short}
                  {isActive && <span className="absolute top-1 h-1 w-5 rounded-full bg-brand-strong" aria-hidden />}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
