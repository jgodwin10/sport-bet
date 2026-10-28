import { useEffect } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { getToken, setToken } from "../api/client";
import { useMe } from "../api/hooks";
import { Icon, type IconName } from "./icons";
import { cx } from "./ui";

const NAV: { to: string; label: string; short: string; icon: IconName; tab: boolean }[] = [
  { to: "/", label: "Matches", short: "Matches", icon: "dashboard", tab: true },
  { to: "/top", label: "Top 10", short: "Top 10", icon: "star", tab: true },
  { to: "/predictions", label: "Value picks", short: "Picks", icon: "target", tab: true },
  { to: "/teams", label: "Teams", short: "Teams", icon: "shield", tab: true },
  { to: "/performance", label: "Track record", short: "Record", icon: "chart", tab: true },
  { to: "/settings", label: "Settings", short: "Settings", icon: "sliders", tab: false },
];

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <NavLink to="/" className="flex items-center gap-2.5 min-w-0 shrink-0" aria-label="Matchline home">
      <span className={cx("grid place-items-center rounded-lg bg-brand text-brand-ink", compact ? "h-8 w-8" : "h-9 w-9")}>
        <svg width={compact ? 16 : 18} height={compact ? 16 : 18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M4 17l5-6 4 3 7-8" />
        </svg>
      </span>
      <span className={cx("font-display font-extrabold uppercase tracking-[0.02em] leading-none", compact ? "text-[22px]" : "text-[25px]")}>
        Matchline
      </span>
    </NavLink>
  );
}

function useSignOut() {
  const qc = useQueryClient();
  const nav = useNavigate();
  return () => { setToken(null); qc.clear(); nav("/"); };
}

/** Sidebar footer on desktop. */
function SidebarAccount() {
  const me = useMe(!!getToken());
  const signOut = useSignOut();
  if (!me.data) {
    return <NavLink to="/login" className="btn w-full"><Icon name="login" size={15} />Sign in</NavLink>;
  }
  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-line bg-night px-3 py-2.5">
      <span className="grid place-items-center h-8 w-8 shrink-0 rounded-full bg-brand-soft text-brand text-xs font-bold">
        {me.data.email[0].toUpperCase()}
      </span>
      <span className="min-w-0 flex-1 leading-tight">
        <span className="block truncate text-xs font-semibold text-ink">{me.data.email}</span>
        <span className="block text-2xs text-ink-3 capitalize">{me.data.role}</span>
      </span>
      <button className="btn btn-ghost btn-sm btn-icon" aria-label="Sign out" onClick={signOut}><Icon name="logout" size={15} /></button>
    </div>
  );
}

/** Top-bar actions on phones and tablets. */
function BarAccount() {
  const me = useMe(!!getToken());
  const signOut = useSignOut();
  return (
    <div className="flex items-center gap-1">
      <NavLink to="/settings" aria-label="Settings"
               className={({ isActive }) => cx("btn btn-ghost btn-icon", isActive && "text-brand")}>
        <Icon name="sliders" size={18} />
      </NavLink>
      {me.data ? (
        <button onClick={signOut} aria-label={`Sign out ${me.data.email}`}
                className="grid place-items-center h-8 w-8 ml-1 rounded-full bg-brand-soft text-brand text-xs font-bold">
          {me.data.email[0].toUpperCase()}
        </button>
      ) : (
        <NavLink to="/login" className="btn btn-sm ml-1"><Icon name="login" size={14} />Sign in</NavLink>
      )}
    </div>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return (
    <div className="min-h-[100dvh] lg:pl-[248px]">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex fixed inset-y-0 left-0 z-30 w-[248px] flex-col border-r border-line bg-night-2 px-4 py-6">
        <div className="px-2"><Brand /></div>
        <nav aria-label="Main" className="mt-9 flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => cx("group relative flex items-center gap-3 h-11 px-3 rounded-xl text-[14px] font-semibold transition-colors",
                isActive ? "bg-white/[0.06] text-ink" : "text-ink-3 hover:text-ink hover:bg-white/[0.03]")}>
              {({ isActive }) => (
                <>
                  {isActive && <span aria-hidden className="absolute -left-4 top-2 bottom-2 w-1 rounded-r bg-brand" />}
                  <Icon name={n.icon} size={18} className={isActive ? "text-brand" : ""} />{n.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-4">
          <SidebarAccount />
          <p className="px-1 text-2xs text-ink-4 leading-relaxed">
            Statistical estimates, never guarantees. Matchline does not place bets.
          </p>
        </div>
      </aside>

      {/* Phone / tablet top bar */}
      <header className="lg:hidden sticky top-0 z-30 border-b border-line bg-night/90 backdrop-blur-md safe-top">
        <div className="mx-auto flex h-14 max-w-[1180px] items-center gap-3 px-4 sm:px-6">
          <Brand compact />
          <div className="ml-auto"><BarAccount /></div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1180px] px-4 sm:px-6 lg:px-10 pt-5 sm:pt-8 lg:pt-10 pb-28 lg:pb-14">
        <Outlet />
        <footer className="mt-14 border-t border-line pt-6 text-center lg:text-left text-xs text-ink-4 leading-relaxed">
          Predictions are statistical estimates, never guarantees. Matchline does not place bets.
          If gambling stops being fun, get free help at{" "}
          <a className="text-ink-3 underline underline-offset-2 hover:text-ink" href="https://www.begambleaware.org" target="_blank" rel="noreferrer">BeGambleAware</a>.
        </footer>
      </main>

      {/* Phone / tablet bottom tabs */}
      <nav aria-label="Main" className="lg:hidden fixed bottom-0 inset-x-0 z-30 border-t border-line bg-night-2/95 backdrop-blur-md safe-bottom">
        <div className="mx-auto grid max-w-[640px] grid-cols-5">
          {NAV.filter((n) => n.tab).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => cx("relative flex flex-col items-center justify-center gap-1 h-16 text-[11px] font-semibold transition-colors",
                isActive ? "text-ink" : "text-ink-3 active:text-ink-2")}>
              {({ isActive }) => (
                <>
                  {isActive && <span aria-hidden className="absolute top-0 h-[3px] w-8 rounded-b bg-brand" />}
                  <Icon name={n.icon} size={22} className={isActive ? "text-brand" : ""} />
                  {n.short}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
