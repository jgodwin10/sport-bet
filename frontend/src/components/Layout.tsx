import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { getToken, setToken } from "../api/client";
import { useMe } from "../api/hooks";
import { Icon, type IconName } from "./icons";
import { Logo } from "./Logo";
import { cx } from "./ui";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Matches", icon: "dashboard" },
  { to: "/top", label: "Top picks", icon: "star" },
  { to: "/teams", label: "Teams", icon: "shield" },
  { to: "/performance", label: "Record", icon: "chart" },
];

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
              className="grid place-items-center h-8 w-8 rounded-full bg-gradient-to-br from-brand to-brand-2 text-xs font-bold text-brand-ink ring-2 ring-bg">
        {me.data.email[0].toUpperCase()}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 z-40 w-64 max-w-[calc(100vw-2rem)] rounded-2xl border border-line bg-surface shadow-pop p-1.5 animate-fade-in">
          <div className="px-3 py-2.5">
            <div className="truncate text-sm font-semibold">{me.data.email}</div>
            <div className="text-xs text-ink-3 capitalize">{me.data.role}</div>
          </div>
          <div className="h-px bg-line mx-1.5" />
          <button className="mt-1 w-full flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink-2 hover:bg-subtle"
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
      <header className="sticky top-0 z-30 border-b border-line/70 bg-bg/75 backdrop-blur-xl safe-top">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-4 sm:px-6">
          <NavLink to="/" aria-label="Oddsmith home" className="shrink-0"><Logo /></NavLink>
          <nav aria-label="Main" className="hidden md:flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"}
                       className={({ isActive }) => cx("h-9 px-3.5 flex items-center gap-2 rounded-xl text-sm font-semibold transition-colors",
                                                       isActive ? "bg-brand/10 text-brand" : "text-ink-3 hover:text-ink hover:bg-subtle")}>
                <Icon name={n.icon} size={16} />{n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <NavLink to="/settings" aria-label="Settings"
                     className={({ isActive }) => cx("btn btn-ghost btn-icon btn-sm", isActive && "!bg-brand/10 !text-brand")}>
              <Icon name="sliders" size={17} />
            </NavLink>
            <Account />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 sm:px-6 pt-6 sm:pt-10 pb-28 md:pb-16">
        <Outlet />
        <footer className="mt-16 flex flex-col gap-4 border-t border-line pt-6 sm:flex-row sm:items-start sm:justify-between">
          <Logo compact />
          <p className="max-w-lg text-xs text-ink-4 sm:text-right">
            Statistical estimates, never guarantees. Oddsmith does not place bets. If gambling stops being fun, get free help at{" "}
            <a className="text-ink-3 underline underline-offset-2 hover:text-ink" href="https://www.begambleaware.org" target="_blank" rel="noreferrer">BeGambleAware</a>.
          </p>
        </footer>
      </main>

      <nav aria-label="Main" className="md:hidden fixed bottom-0 inset-x-0 z-30 border-t border-line/70 bg-bg/85 backdrop-blur-xl safe-bottom">
        <div className="grid grid-cols-4">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
                     className={({ isActive }) => cx("relative flex flex-col items-center justify-center gap-1 h-16 text-[11px] font-semibold transition-colors",
                                                     isActive ? "text-brand" : "text-ink-4")}>
              {({ isActive }) => (
                <>
                  {isActive && <span aria-hidden className="absolute top-0 h-0.5 w-10 rounded-full bg-gradient-to-r from-brand to-brand-2" />}
                  <Icon name={n.icon} size={21} />{n.label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
