import { useAiAnalysis } from "../api/hooks";
import type { Analysis, PredictedLineup } from "../api/types";
import { fmtDateTime } from "../lib/format";
import { Icon } from "./icons";
import { Card, Loading, OUTCOME_COLORS, Pill, TeamLogo } from "./ui";

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
    <Card title={<><Icon name="users" size={16} />Lineups</>}
          subtitle="Official team sheets when published, otherwise the AI's predicted XI from previews and recent lineups">
      {ai.isLoading ? <Loading rows={3} /> : (
        <div className="grid gap-6 md:grid-cols-2">
          {(["home", "away"] as const).map((side) => (
            <TeamPanel key={side} side={side} team={f[`${side}_team`]} lineup={lineupFor(side)}
                       aiConfigured={!!ai.data?.configured} />
          ))}
        </div>
      )}
    </Card>
  );
}

function TeamPanel({ side, team, lineup, aiConfigured }: {
  side: "home" | "away"; team: { name: string; logo_url?: string | null }; lineup: TeamLineup | null; aiConfigured: boolean;
}) {
  const grouped = lineup && lines(lineup.starters, lineup.formation);
  return (
    <section aria-label={`${team.name} lineup`} className="min-w-0">
      <div className="flex items-center gap-2.5 flex-wrap">
        <TeamLogo name={team.name} src={team.logo_url} size={26} />
        <span className="font-bold text-[14.5px] truncate">{team.name}</span>
        {lineup?.formation && <span className="num text-[13px] font-bold text-ink-2">{lineup.formation}</span>}
        {lineup && (lineup.kind === "confirmed"
          ? <Pill tone="pos" icon="check">Confirmed</Pill>
          : <Pill tone="brand" icon="sparkle">Predicted</Pill>)}
      </div>

      {!lineup ? (
        <div className="mt-3 glass-inset p-4 text-[13px] text-ink-3 leading-relaxed">
          No lineup yet. {aiConfigured
            ? "Predicted XIs come from the AI's web search, usually a day or two before kickoff."
            : "Predicted XIs need the AI analysis, which is not set up on this server."}
          {" "}Official lineups appear about 30 minutes before kickoff.
        </div>
      ) : grouped ? (
        <Pitch rows={grouped} color={OUTCOME_COLORS[side]} />
      ) : (
        <ol className="mt-3 space-y-1 text-[13px]">
          {lineup.starters.map((p) => <li key={p.name} className="flex gap-2"><span className="num text-ink-4 w-6 text-right">{p.number ?? p.position ?? ""}</span>{p.name}</li>)}
        </ol>
      )}

      {lineup && <p className="mt-2 text-2xs text-ink-4 leading-snug">{lineup.note}</p>}
      {lineup && lineup.bench.length > 0 && (
        <p className="mt-2 text-xs text-ink-3 leading-relaxed"><span className="font-semibold text-ink-2">Bench: </span>
          {lineup.bench.map((p) => p.name).join(", ")}</p>
      )}
    </section>
  );
}

/** Vertical half-pitch-style view, team attacking upwards; each line is listed right side first. */
function Pitch({ rows, color }: { rows: Player[][]; color: string }) {
  return (
    <div className="relative mt-3 overflow-hidden rounded-xl border border-line bg-[repeating-linear-gradient(180deg,#14301f_0,#14301f_36px,#173823_36px,#173823_72px)]">
      <div aria-hidden className="absolute inset-3 rounded-lg border border-white/[0.18]" />
      <div aria-hidden className="absolute left-3 right-3 top-1/2 border-t border-white/[0.18]" />
      <div aria-hidden className="absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/[0.18]" />
      <div aria-hidden className="absolute bottom-3 left-1/2 h-10 w-36 -translate-x-1/2 border border-b-0 border-white/[0.18]" />
      <div aria-hidden className="absolute top-3 left-1/2 h-10 w-36 -translate-x-1/2 border border-t-0 border-white/[0.18]" />
      <ol className="relative flex flex-col-reverse gap-4 px-2 py-5">
        {rows.map((row, i) => (
          <li key={i} className="flex flex-row-reverse justify-around gap-1">
            {row.map((p) => (
              <div key={p.name} className="flex w-[19%] min-w-0 flex-col items-center gap-1 text-center" title={p.name}>
                <span className="num grid h-8 w-8 place-items-center rounded-full text-[11px] font-extrabold text-white ring-2 ring-white/30 shadow"
                      style={{ background: i === 0 ? "#3f4a5e" : color }}>
                  {p.number ?? initials(p.name)}
                </span>
                <span className="w-full truncate text-[11px] font-semibold leading-tight text-ink">{shortName(p.name)}</span>
              </div>
            ))}
          </li>
        ))}
      </ol>
    </div>
  );
}
