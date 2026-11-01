import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { getToken, setToken } from "../api/client";
import { useMe } from "../api/hooks";
import { Icon, type IconName } from "./icons";
import { cx } from "./ui";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Matches", icon: "dashboard" },
  { to: "/top", label: "Top picks", icon: "star" },
  { to: "/teams", label: "Teams", icon: "shield" },
  { to: "/performance", label: "Record", icon: "chart" },
];

function Brand() {
  return (
    <NavLink to="/" className="flex items-center gap-2 shrink-0" aria-label="Matchline home">
      <span className="grid place-items-center h-7 w-7 rounded-lg bg-ink text-bg">
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 17l5-6 4 3 7-8" /></svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight">Matchline</span>
    </NavLink>
  );
}

function Account() {
  const me = useMe(!!getToken());
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!me.data) return <NavLink to="/login" className="btn btn-sm">Sign in</NavLink>;
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-label={`Account ${me.data.email}`} aria-expanded={open}
              className="grid place-items-center h-8 w-8 rounded-full bg-subtle text-xs font-semibold text-ink-2 hover:text-ink">
        {me.data.email[0].toUpperCase()}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 z-40 w-60 max-w-[calc(100vw-2rem)] rounded-xl border border-line bg-surface shadow-pop p-1.5 animate-fade-in">
          <div className="px-3 py-2">
            <div className="truncate text-sm font-medium">{me.data.email}</div>
            <div className="text-xs text-ink-3 capitalize">{me.data.role}</div>
          </div>
          <button className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-subtle"
                  onClick={() => { setOpen(false); setToken(null); qc.clear(); nav("/"); }}>
            <Icon name="logout" size={15} />Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return (
    // overflow-x: clip guards against any stray wide element without breaking sticky positioning.
    <div className="min-h-[100dvh] overflow-x-clip">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md safe-top">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-6 px-4 sm:px-6">
          <Brand />
          <nav aria-label="Main" className="hidden md:flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"}
                       className={({ isActive }) => cx("h-8 px-3 grid place-items-center rounded-full text-sm font-medium transition-colors",
                                                       isActive ? "bg-subtle text-ink" : "text-ink-3 hover:text-ink")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <NavLink to="/settings" aria-label="Settings"
                     className={({ isActive }) => cx("btn btn-ghost btn-icon btn-sm", isActive && "bg-subtle text-ink")}>
              <Icon name="sliders" size={17} />
            </NavLink>
            <Account />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 sm:px-6 pt-6 sm:pt-10 pb-28 md:pb-16">
        <Outlet />
        <footer className="mt-16 border-t border-line pt-6 text-xs text-ink-4">
          Predictions are statistical estimates, never guarantees. Matchline does not place bets.
          If gambling stops being fun, get free help at{" "}
          <a className="underline underline-offset-2 hover:text-ink-2" href="https://www.begambleaware.org" target="_blank" rel="noreferrer">BeGambleAware</a>.
        </footer>
      </main>

      <nav aria-label="Main" className="md:hidden fixed bottom-0 inset-x-0 z-30 border-t border-line bg-bg/90 backdrop-blur-md safe-bottom">
        <div className="grid grid-cols-4">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
                     className={({ isActive }) => cx("flex flex-col items-center justify-center gap-1 h-14 text-[11px] font-medium transition-colors",
                                                     isActive ? "text-ink" : "text-ink-4")}>
              <Icon name={n.icon} size={20} />{n.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
