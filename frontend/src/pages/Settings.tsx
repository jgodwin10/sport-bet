import { useEffect, useMemo, useState, type ReactNode } from "react";
import { z } from "zod";
import { getToken } from "../api/client";
import { useAdminAction, useDataQuality, useMe, useSettings } from "../api/hooks";
import { providerName } from "../lib/language";
import { Icon } from "../components/icons";
import { Card, cx, ErrorState, Field, Loading, PageHeader, Pill } from "../components/ui";
import { fmtDateTime, getTimezone, setTimezone } from "../lib/format";

const Rules = z.object({
  min_probability: z.number().min(0).max(1), min_edge: z.number().min(-1).max(1), min_ev: z.number().min(-1).max(5),
  min_odds: z.number().min(1.01), max_odds: z.number().min(1.01), min_reliability: z.number().min(0).max(100),
  max_odds_age_hours: z.number().min(0).max(168), max_disagreement: z.number().min(0).max(1),
  require_lower_bound_ev_positive: z.boolean(),
}).refine((r) => r.max_odds > r.min_odds, { message: "Maximum odds must be higher than minimum odds" });

const RULE_FIELDS: { key: string; label: string; hint: string; step: string; unit: string }[] = [
  { key: "min_ev", label: "Minimum value", hint: "How much better the price must be than our estimate", step: "0.01", unit: "0.03 = 3%" },
  { key: "min_edge", label: "Minimum edge", hint: "Our chance minus the bookmaker's", step: "0.01", unit: "0.02 = 2 pts" },
  { key: "min_probability", label: "Minimum chance", hint: "Skip long shots below this", step: "0.01", unit: "0–1" },
  { key: "min_reliability", label: "Minimum data confidence", hint: "Skip matches with weak data", step: "1", unit: "0–100" },
  { key: "min_odds", label: "Lowest odds", hint: "Ignore very short prices", step: "0.05", unit: "decimal" },
  { key: "max_odds", label: "Highest odds", hint: "Ignore very long prices", step: "0.1", unit: "decimal" },
  { key: "max_odds_age_hours", label: "Oldest odds allowed", hint: "Prices older than this are ignored", step: "1", unit: "hours" },
  { key: "max_disagreement", label: "Max model disagreement", hint: "Skip when our models disagree", step: "0.01", unit: "0–1" },
];
const MARKETS: [string, string][] = [["1x2", "Match result"], ["totals_1.5", "Over/under 1.5"], ["totals_2.5", "Over/under 2.5"],
  ["totals_3.5", "Over/under 3.5"], ["asian_handicap", "Asian handicap"]];

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <Card title={title} subtitle={description}>
      {children}
    </Card>
  );
}

function Toggle({ checked, onChange, disabled, label, hint }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string; hint?: string }) {
  return (
    <div className={cx("flex items-start justify-between gap-4 py-3", disabled && "opacity-60")}>
      <span className="min-w-0"><span className="block text-sm font-medium">{label}</span>{hint && <span className="block text-xs text-ink-3 mt-0.5">{hint}</span>}</span>
      <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
              className={cx("relative h-6 w-10 shrink-0 rounded-full transition-colors", checked ? "bg-gradient-to-r from-brand to-brand-2" : "bg-line-strong")}>
        <span className={cx("absolute left-0 top-0.5 h-5 w-5 rounded-full bg-bg shadow-sm transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
      </button>
    </div>
  );
}

function ChipToggle({ on, disabled, onClick, children }: { on: boolean; disabled: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button disabled={disabled} aria-pressed={on} onClick={onClick} className="chip border border-line disabled:opacity-60">
      {on && <Icon name="check" size={13} />}{children}
    </button>
  );
}

export default function Settings() {
  const s = useSettings();
  const me = useMe(!!getToken());
  const dq = useDataQuality();
  const action = useAdminAction();
  const [rules, setRules] = useState<Record<string, any> | null>(null);
  const [options, setOptions] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tz, setTz] = useState(getTimezone());
  const [tzSaved, setTzSaved] = useState(false);
  useEffect(() => { if (s.data) { setRules(s.data.rules); setOptions(s.data.options); } }, [s.data]);
  const isAdmin = me.data?.role === "admin";
  const dirty = useMemo(() => !!s.data && !!rules && !!options &&
    (JSON.stringify(rules) !== JSON.stringify(s.data.rules) || JSON.stringify(options) !== JSON.stringify(s.data.options)), [s.data, rules, options]);

  if (s.isError) return <ErrorState error={s.error} onRetry={s.refetch} />;
  if (s.isLoading || !rules || !options) return <Card><Loading rows={5} /></Card>;
  const server = s.data!.server;
  const save = () => {
    const parsed = Rules.safeParse(rules);
    if (!parsed.success) { setError(parsed.error.issues[0].message); return; }
    setError(null);
    action.mutate({ path: "/settings", method: "PUT", body: { rules: parsed.data, options } });
  };
  const toggleIn = (key: string, value: string) =>
    setOptions({ ...options, [key]: options[key].includes(value) ? options[key].filter((x: string) => x !== value) : [...options[key], value] });

  return (
    <>
      <PageHeader title="Settings" description="When a bet counts as a recommendation. API keys stay on the server and never appear here." />
      {!isAdmin && (
        <p className="mb-6 text-sm text-ink-3">Read-only. Sign in as an administrator to change these.</p>
      )}

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <Section title="When to recommend a bet" description="Every rule must pass. Stricter rules mean fewer, safer picks.">
          <div className="grid gap-4 sm:grid-cols-2">
            {RULE_FIELDS.map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint}>
                <div className="relative">
                  <input className="input pr-20" type="number" inputMode="decimal" step={f.step} disabled={!isAdmin} value={rules[f.key]}
                         onChange={(e) => setRules({ ...rules, [f.key]: Number(e.target.value) })} />
                  <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-xs text-ink-4">{f.unit}</span>
                </div>
              </Field>
            ))}
          </div>
          <div className="mt-3 border-t border-line">
            <Toggle label="Extra safety margin" hint="Only recommend when the value survives the model's uncertainty range" checked={rules.require_lower_bound_ev_positive}
                    disabled={!isAdmin} onChange={(v) => setRules({ ...rules, require_lower_bound_ev_positive: v })} />
          </div>
        </Section>

        <div className="space-y-6 min-w-0">
          <Section title="Markets & leagues" description="Which bets can be recommended, and your favourite leagues.">
            <div className="label mb-2">Markets</div>
            <div className="flex flex-wrap gap-1.5">
              {MARKETS.map(([k, label]) => <ChipToggle key={k} on={options.enabled_markets.includes(k)} disabled={!isAdmin} onClick={() => toggleIn("enabled_markets", k)}>{label}</ChipToggle>)}
            </div>
            <div className="label mt-5 mb-2">Favourite leagues</div>
            <div className="flex flex-wrap gap-1.5">
              {server.available_competitions.filter((c: any) => server.tracked_competitions.includes(c.code)).map((c: any) => (
                <ChipToggle key={c.code} on={options.preferred_competitions.includes(c.code)} disabled={!isAdmin} onClick={() => toggleIn("preferred_competitions", c.code)}>{c.name}</ChipToggle>
              ))}
            </div>
          </Section>

          <Section title="Play it safe" description="Notifications are off unless you switch them on. Limits never rise automatically.">
            <div className="divide-soft">
              <Toggle label="Betting notifications" hint="Alerts when a value pick appears" checked={options.notifications_enabled} disabled={!isAdmin}
                      onChange={(v) => setOptions({ ...options, notifications_enabled: v })} />
              <Toggle label="Stake tracking" hint="Keep a private record — nothing is ever placed" checked={options.stake_tracking_enabled} disabled={!isAdmin}
                      onChange={(v) => setOptions({ ...options, stake_tracking_enabled: v })} />
            </div>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label="Max stake per bet"><input className="input" type="number" inputMode="decimal" disabled={!isAdmin} value={options.max_stake_per_selection} onChange={(e) => setOptions({ ...options, max_stake_per_selection: Number(e.target.value) })} /></Field>
              <Field label="Max stake per day"><input className="input" type="number" inputMode="decimal" disabled={!isAdmin} value={options.max_daily_stake} onChange={(e) => setOptions({ ...options, max_daily_stake: Number(e.target.value) })} /></Field>
            </div>
          </Section>

          <Section title="Display" description="Saved in this browser. Times are stored in UTC.">
            <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
              <Field label="Timezone" className="flex-1"><input className="input" value={tz} onChange={(e) => { setTz(e.target.value); setTzSaved(false); }} placeholder="e.g. Europe/London" /></Field>
              <button className="btn" onClick={() => {
                try { new Intl.DateTimeFormat(undefined, { timeZone: tz }); setTimezone(tz); setTzSaved(true); setError(null); }
                catch { setError(`“${tz}” isn't a timezone we recognise`); }
              }}>{tzSaved ? <><Icon name="check" size={14} />Saved — reload to apply</> : "Apply"}</button>
            </div>
          </Section>
        </div>

        <Section title="Data sources" description={`Fixtures refresh every ${server.update_intervals_minutes.fixtures} min, odds every ${server.update_intervals_minutes.odds} min, lineups every ${server.update_intervals_minutes.lineups} min.`}>
          <ul className="divide-soft -my-3">
            {server.providers.map((p: any) => (
              <li key={p.name} className="flex items-center justify-between gap-3 py-3">
                <span className="flex items-center gap-3 min-w-0">
                  <span className={cx("h-2 w-2 rounded-full shrink-0", p.configured ? "bg-pos" : "bg-line-strong")} />
                  <span className="min-w-0"><span className="block text-sm font-medium truncate">{providerName(p.name)}</span>
                    <span className="block text-xs text-ink-4 truncate">{Object.keys(p.capabilities).filter((k) => !["competitions", "requires_key", "rate_limit", "note", "cost"].includes(k) && p.capabilities[k]).join(" · ").replace(/_/g, " ")}</span></span>
                </span>
                <Pill tone={p.configured ? "pos" : "neutral"}>{p.configured ? "Active" : "Needs key"}</Pill>
              </li>
            ))}
            {server.ai && (
              <li className="flex items-center justify-between gap-3 py-3">
                <span className="flex items-center gap-3 min-w-0">
                  <span className={cx("h-2 w-2 rounded-full shrink-0", server.ai.configured ? "bg-pos" : "bg-line-strong")} />
                  <span className="min-w-0"><span className="block text-sm font-medium truncate">AI analysis</span>
                    <span className="block text-xs text-ink-4 truncate">
                      {server.ai.configured
                        ? `${server.ai.keys.filter((k: any) => k.available).length} of ${server.ai.keys.length} keys ready · ${server.ai.models[0]}`
                        : "match write-ups · team news via web search"}
                    </span></span>
                </span>
                <Pill tone={server.ai.configured ? "pos" : "neutral"}>{server.ai.configured ? "Active" : "Needs key"}</Pill>
              </li>
            )}
          </ul>
          {isAdmin && (
            <div className="mt-5">
              <div className="label mb-2">Run now</div>
              <div className="flex flex-wrap gap-2">
                {[["upcoming", "Fetch fixtures"], ["odds", "Refresh odds"], ["predict", "Update predictions"], ["settle", "Settle results"], ["logos", "Refresh crests"], ["ai_analysis", "AI analysis"], ["history", "Reload history"]].map(([k, label]) => (
                  <button key={k} className="btn btn-sm" onClick={() => action.mutate({ path: "/admin/ingest", body: { kind: k } })}><Icon name="refresh" size={13} />{label}</button>
                ))}
              </div>
            </div>
          )}
        </Section>

        <Section title="Data health" description="Problems the system found and how it handled them.">
          {dq.isLoading ? <Loading rows={2} /> : dq.isError ? <ErrorState error={dq.error} /> : (
            <div className="space-y-3">
              {[
                ["Unresolved data conflicts", dq.data!.unresolved_conflicts.length, "Sources that disagree about a team, kickoff or score"],
                ["Finished matches without a result", dq.data!.fixtures_missing_results.length, "Results arrive with the next data refresh"],
              ].map(([label, n, hint]) => (
                <div key={String(label)} className="flex items-center justify-between gap-3 py-1">
                  <span className="min-w-0"><span className="block text-sm font-medium">{label}</span><span className="block text-xs text-ink-3">{hint}</span></span>
                  <Pill tone={Number(n) ? "warn" : "pos"}>{Number(n) ? n : "All clear"}</Pill>
                </div>
              ))}
              {dq.data!.fixtures_missing_results.slice(0, 4).map((f: any) => <p key={f.fixture_id} className="text-xs text-ink-4">Match #{f.fixture_id} · kicked off {fmtDateTime(f.kickoff_utc)}</p>)}
            </div>
          )}
        </Section>
      </div>

      {isAdmin && (dirty || error || action.isSuccess || action.isError) && (
        <div className="sticky bottom-20 md:bottom-6 z-20 mt-6 flex justify-center">
          <div className="flex flex-wrap items-center gap-2 rounded-full border border-line bg-surface shadow-pop pl-4 pr-1.5 py-1.5 max-w-full">
            <span className={cx("text-[13px] font-medium", error || action.isError ? "text-neg" : action.isSuccess && !dirty ? "text-pos" : "text-ink-2")}>
              {error ?? (action.isError ? (action.error as Error).message : action.isSuccess && !dirty ? "Saved" : "Unsaved changes")}
            </span>
            {dirty && <button className="btn btn-sm" onClick={() => { setRules(s.data!.rules); setOptions(s.data!.options); setError(null); }}>Discard</button>}
            {dirty && <button className="btn btn-sm btn-primary" onClick={save} disabled={action.isPending}>{action.isPending ? "Saving…" : "Save"}</button>}
          </div>
        </div>
      )}
    </>
  );
}
