import { createContext, useContext, useState, type ReactNode } from "react";

const KEY = "oddsmith.league";
const LeagueContext = createContext<{ league: string; setLeague: (code: string) => void }>({ league: "all", setLeague: () => {} });

/** The league chosen in the header's pill bar, shared by Matches, Top picks and Teams and remembered per browser. */
export function LeagueProvider({ children }: { children: ReactNode }) {
  const [league, set] = useState(() => {
    try { return localStorage.getItem(KEY) || "all"; } catch { return "all"; }
  });
  const setLeague = (code: string) => {
    set(code);
    try { localStorage.setItem(KEY, code); } catch { /* storage unavailable: session only */ }
  };
  return <LeagueContext.Provider value={{ league, setLeague }}>{children}</LeagueContext.Provider>;
}

export const useLeague = () => useContext(LeagueContext);

/** Picks in one league, re-ranked 1..n. "all" keeps the list as ranked. */
export function inLeague<T extends { competition: string; rank: number }>(items: T[], league: string, n = 10): T[] {
  return (league === "all" ? items : items.filter((t) => t.competition === league)).slice(0, n).map((t, i) => ({ ...t, rank: i + 1 }));
}
