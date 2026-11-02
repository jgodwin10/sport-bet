import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, getToken, setToken } from "../api/client";
import { useCompetitions, useMe } from "../api/hooks";
import { LeagueProvider, useLeague } from "../lib/league";
import { Icon, type IconName } from "./icons";
import { Logo } from "./Logo";
import { cx, Sheet, TeamLogo } from "./ui";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Matches", icon: "dashboard" },
  { to: "/top", label: "Top picks", icon: "star" },
  { to: "/two-odds", label: "2 odds", icon: "target" },
  { to: "/teams", label: "Teams", icon: "shield" },
  { to: "/performance", label: "Record", icon: "chart" },
  { to: "/settings", label: "Settings", icon: "sliders" },
];
// Pages whose content follows the league chosen in the header.
const LEAGUE_PAGES = ["/", "/top", "/teams"];

function useSignOut() {
  const qc = useQueryClient();
  const nav = useNavigate();
  return () => { setToken(null); qc.clear(); nav("/"); };
}

/** The league tab bar. A pill track on desktop, a scrolling chip row on phones. */
function LeagueTabs({ className }: { className?: string }) {
  const comps = useCompetitions();
  const { league, setLeague } = useLeague();
  const options = [{ code: "all", name: "All leagues" }, ...(comps.data ?? []).map((c) => ({ code: c.code, name: c.name }))];
  return (
    <div role="tablist" aria-label="League" className={cx("flex gap-1 scroll-x", className)}>
      {options.map((o) => (
        <button key={o.code} role="tab" aria-selected={league === o.code} onClick={() => setLeague(o.code)}
                className={cx("h-10 shrink-0 rounded-full px-5 text-sm font-semibold whitespace-nowrap transition-all",
                              league === o.code ? "bg-gradient-to-b from-brand-2 to-brand text-white glow-blue" : "text-ink-3 hover:text-ink")}>
          {o.name}
        </button>
      ))}
    </div>
  );
}

function TeamSearch() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const results = useQuery({
    queryKey: ["team-search", q],
    queryFn: () => api<{ id: number; name: string; logo_url: string | null }[]>("/teams", { query: { search: q, limit: 8 } }),
    enabled: open && q.trim().length >= 2,
  });
  const close = () => { setOpen(false); setQ(""); };
  return (
    <>
      <button className="icon-btn" aria-label="Search teams" onClick={() => setOpen(true)}><Icon name="search" size={18} /></button>
      <Sheet open={open} onClose={close} title="Find a team">
        <input autoFocus className="input" placeholder="Type a team name" aria-label="Team name" value={q} onChange={(e) => setQ(e.target.value)} />
        <ul className="mt-3 min-h-[120px]">
          {q.trim().length < 2 ? <li className="py-6 text-center text-sm text-ink-4">Type at least two letters</li>
            : results.data?.length === 0 ? <li className="py-6 text-center text-sm text-ink-4">No team matches “{q}”</li>
            : results.data?.map((t) => (
              <li key={t.id}>
                <button className="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-left hover:bg-white/[0.05]"
                        onClick={() => { close(); nav(`/teams?team=${t.id}`); }}>
                  <TeamLogo name={t.name} src={t.logo_url} size={28} />
                  <span className="min-w-0 truncate text-sm font-semibold">{t.name}</span>
                  <Icon name="chevronRight" size={15} className="ml-auto shrink-0 text-ink-4" />
                </button>
              </li>
            ))}
        </ul>
      </Sheet>
    </>
  );
}

/** Avatar button with a small account menu. `side` sets where the menu opens. */
function Account({ side = "below" }: { side?: "below" | "right" }) {
  const me = useMe(!!getToken());
  const signOut = useSignOut();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!me.data) {
    return side === "right"
      ? <NavLink to="/login" className="icon-btn" aria-label="Sign in"><Icon name="login" size={18} /></NavLink>
      : <NavLink to="/login" className="btn btn-sm">Sign in</NavLink>;
  }
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-label={`Account ${me.data.email}`} aria-expanded={open}
              className="grid place-items-center h-11 w-11 rounded-full bg-gradient-to-b from-brand-2 to-brand text-sm font-bold text-white ring-2 ring-white/10 glow-blue">
        {me.data.email[0].toUpperCase()}
      </button>
      {open && (
        <div className={cx("absolute z-40 w-64 max-w-[calc(100vw-2rem)] rounded-2xl border border-white/[0.08] bg-surface shadow-pop p-1.5 animate-fade-in",
                           side === "right" ? "left-full bottom-0 ml-3" : "right-0 top-full mt-2")}>
          <div className="px-3 py-2.5">
            <div className="truncate text-sm font-semibold">{me.data.email}</div>
            <div className="text-xs text-ink-3 capitalize">{me.data.role}</div>
          </div>
          <div className="h-px bg-white/[0.06] mx-1.5" />
          <button className="mt-1 w-full flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink-2 hover:bg-white/[0.05]"
                  onClick={() => { setOpen(false); signOut(); }}>
            <Icon name="logout" size={15} />Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function Rail() {
  const me = useMe(!!getToken());
  const signOut = useSignOut();
  return (
    <aside className="hidden lg:flex fixed left-5 top-[100px] bottom-5 z-20 w-[60px] flex-col items-center justify-between">
      <nav aria-label="Main" className="card flex flex-col items-center gap-2 !rounded-full p-2">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} aria-label={n.label}
                   className={({ isActive }) => cx("group relative grid place-items-center h-11 w-11 rounded-full transition-all",
                                                   isActive ? "bg-gradient-to-b from-brand-2 to-brand text-white glow-blue" : "text-ink-3 hover:text-ink hover:bg-white/[0.05]")}>
            <Icon name={n.icon} size={19} />
            <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-white/[0.08] bg-surface px-2.5 py-1 text-xs font-semibold text-ink opacity-0 shadow-pop transition-opacity group-hover:opacity-100">
              {n.label}
            </span>
          </NavLink>
        ))}
      </nav>
      <div className="flex flex-col items-center gap-3">
        <Account side="right" />
        {me.data && <button className="icon-btn" aria-label="Sign out" onClick={signOut}><Icon name="logout" size={18} /></button>}
      </div>
    </aside>
  );
}

function Shell() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  const leaguePage = LEAGUE_PAGES.includes(pathname);
  return (
    // overflow-x: clip guards against any stray wide element without breaking sticky positioning.
    <div className="min-h-[100dvh] overflow-x-clip">
      <header className="sticky top-0 z-30 bg-bg/70 backdrop-blur-xl safe-top">
        <div className="mx-auto flex h-[76px] max-w-[1440px] items-center gap-4 px-4 sm:px-5">
          <Link to="/" aria-label="Oddsmith home" className="card !rounded-full shrink-0 py-2 pl-2 pr-4 lg:pr-5"><Logo /></Link>
          <div className="hidden lg:flex flex-1 justify-center min-w-0">
            {leaguePage && <LeagueTabs className="card !rounded-full p-1.5 max-w-full" />}
          </div>
          <div className="ml-auto lg:ml-0 flex items-center gap-2 shrink-0">
            <TeamSearch />
            <div className="lg:hidden"><Account /></div>
          </div>
        </div>
        {leaguePage && <LeagueTabs className="lg:hidden px-4 pb-3 -mt-1" />}
      </header>

      <Rail />

      <main className="mx-auto w-full max-w-[1440px] px-4 sm:px-5 lg:pl-[104px] pt-3 sm:pt-5 pb-32 lg:pb-12">
        <Outlet />
        <footer className="mt-14 flex flex-col gap-4 border-t border-white/[0.06] pt-6 sm:flex-row sm:items-start sm:justify-between">
          <Logo compact />
          <p className="max-w-lg text-xs text-ink-4 sm:text-right">
            Statistical estimates, never guarantees. Oddsmith does not place bets. If gambling stops being fun, get free help at{" "}
            <a className="text-ink-3 underline underline-offset-2 hover:text-ink" href="https://www.begambleaware.org" target="_blank" rel="noreferrer">BeGambleAware</a>.
          </p>
        </footer>
      </main>

      <nav aria-label="Main" className="lg:hidden fixed inset-x-3 bottom-[max(12px,env(safe-area-inset-bottom))] z-30">
        <div className="card !rounded-full grid grid-cols-6 p-1.5 backdrop-blur-xl">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
                     className={({ isActive }) => cx("flex flex-col items-center justify-center gap-0.5 h-14 rounded-full text-[10.5px] font-semibold transition-all",
                                                     isActive ? "bg-gradient-to-b from-brand-2 to-brand text-white glow-blue" : "text-ink-3")}>
              <Icon name={n.icon} size={19} />{n.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

export default function Layout() {
  return <LeagueProvider><Shell /></LeagueProvider>;
}
