import { useAiAnalysis } from "../api/hooks";
import type { Analysis, PredictedLineup } from "../api/types";
import { fmtDateTime } from "../lib/format";
import { Card, Loading, Pill, TeamLogo } from "./ui";

type Player = { name: string; number?: number | null; position?: string | null };
type TeamLineup = { kind: "confirmed" | "predicted"; formation: string | null; starters: Player[]; bench: Player[];
  note: string };

// API-Football uses single letters; the AI uses two.
const POSITION: Record<string, string> = { G: "GK", D: "DF", M: "MF", F: "FW", GK: "GK", DF: "DF", MF: "MF", FW: "FW" };
const LINE_ORDER = ["GK", "DF", "MF", "FW"];

/** Starters split into lines from goalkeeper to attack: by the formation when it adds up, else by position. */
export function lines(starters: Player[], formation: string | null): Player[][] | null {
  const counts = formation ? [1, ...formation.split("-").map(Number)] : null;
  if (counts && counts.reduce((x, y) => x + y, 0) === starters.length) {
    let i = 0;
    return counts.map((n) => starters.slice(i, (i += n)));
  }
  const pos = starters.map((p) => POSITION[p.position ?? ""]);
  if (pos.some((x) => !x)) return null;
  return LINE_ORDER.map((l) => starters.filter((_, i) => pos[i] === l)).filter((l) => l.length);
}

const shortName = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? parts.slice(1).join(" ") : name;
};
const initials = (name: string) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

export default function Lineups({ a }: { a: Analysis }) {
  const f = a.fixture;
  const ai = useAiAnalysis(f.id);
  const analysis = ai.data?.analysis?.status === "ok" ? ai.data.analysis : null;
  const predicted = analysis?.content?.predicted_lineups ?? null;

  const lineupFor = (side: "home" | "away"): TeamLineup | null => {
    const team = f[`${side}_team`];
    const official = a.lineups.find((l) => l.team_id === team.id || l.team === team.name);
    if (official?.players.length) {
      return { kind: "confirmed", formation: official.formation, starters: official.players.filter((p) => p.starter),
               bench: official.players.filter((p) => !p.starter), note: `Official team sheet · ${fmtDateTime(official.retrieved_at)}` };
    }
    const p: PredictedLineup | null | undefined = predicted?.[side];
    if (!p) return null;
    return { kind: "predicted", formation: p.formation, starters: p.players, bench: [],
             note: [p.source, analysis && `AI search ${fmtDateTime(analysis.created_at)}`].filter(Boolean).join(" · ") };
  };

  return (
    <Card title="Lineups" subtitle="Official team sheets when published, otherwise the AI's predicted XI">
      {ai.isLoading ? <Loading rows={3} /> : (
        <div className="grid gap-6 md:grid-cols-2">
          {(["home", "away"] as const).map((side) => (
            <TeamPanel key={side} team={f[`${side}_team`]} lineup={lineupFor(side)}
                       aiConfigured={!!ai.data?.configured} />
          ))}
        </div>
      )}
    </Card>
  );
}

function TeamPanel({ team, lineup, aiConfigured }: {
  team: { name: string; logo_url?: string | null }; lineup: TeamLineup | null; aiConfigured: boolean;
}) {
  const grouped = lineup && lines(lineup.starters, lineup.formation);
  return (
    <section aria-label={`${team.name} lineup`} className="min-w-0">
      <div className="flex items-center gap-2 flex-wrap min-w-0">
        <TeamLogo name={team.name} src={team.logo_url} size={22} />
        <span className="font-medium text-sm truncate min-w-0">{team.name}</span>
        {lineup?.formation && <span className="num text-[13px] text-ink-3">{lineup.formation}</span>}
        {lineup && (lineup.kind === "confirmed" ? <Pill tone="pos">Confirmed</Pill> : <Pill>Predicted</Pill>)}
      </div>

      {!lineup ? (
        <div className="mt-3 rounded-xl bg-subtle p-4 text-[13px] text-ink-3">
          No lineup yet. {aiConfigured
            ? "Predicted XIs come from the AI's web search, usually a day or two before kickoff."
            : "Predicted XIs need the AI analysis, which is not set up on this server."}
          {" "}Official lineups appear about 30 minutes before kickoff.
        </div>
      ) : grouped ? (
        <Pitch rows={grouped} />
      ) : (
        <ol className="mt-3 space-y-1 text-[13px]">
          {lineup.starters.map((p) => <li key={p.name} className="flex gap-2 min-w-0"><span className="num text-ink-4 w-6 text-right shrink-0">{p.number ?? p.position ?? ""}</span><span className="truncate">{p.name}</span></li>)}
        </ol>
      )}

      {lineup && <p className="mt-2 text-xs text-ink-4">{lineup.note}</p>}
      {lineup && lineup.bench.length > 0 && (
        <p className="mt-2 text-xs text-ink-3"><span className="font-medium text-ink-2">Bench: </span>
          {lineup.bench.map((p) => p.name).join(", ")}</p>
      )}
    </section>
  );
}

/** Simple pitch, team attacking upwards; each line is listed right side first. */
function Pitch({ rows }: { rows: Player[][] }) {
  return (
    <div className="relative mt-3 overflow-hidden rounded-xl bg-pos/[0.07] border border-pos/15">
      <div aria-hidden className="absolute inset-x-3 top-1/2 border-t border-pos/20" />
      <div aria-hidden className="absolute left-1/2 top-1/2 h-14 w-14 -translate-x-1/2 -translate-y-1/2 rounded-full border border-pos/20" />
      <ol className="relative flex flex-col-reverse gap-4 px-1 py-5">
        {rows.map((row, i) => (
          <li key={i} className="flex flex-row-reverse justify-around gap-1">
            {row.map((p) => (
              <div key={p.name} className="flex w-[19%] min-w-0 flex-col items-center gap-1 text-center" title={p.name}>
                <span className={`num grid h-7 w-7 place-items-center rounded-full text-[11px] font-semibold ${i === 0 ? "bg-ink-3 text-bg" : "bg-surface text-ink border border-line-strong"}`}>
                  {p.number ?? initials(p.name)}
                </span>
                <span className="w-full truncate text-[11px] leading-tight text-ink-2">{shortName(p.name)}</span>
              </div>
            ))}
          </li>
        ))}
      </ol>
    </div>
  );
}
