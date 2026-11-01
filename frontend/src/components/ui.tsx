import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { age, fmtDate, pct } from "../lib/format";
import { CONFIDENCE, verdict, type Tone } from "../lib/language";
import { Icon, type IconName } from "./icons";

export function cx(...parts: (string | number | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ colour */
const FALLBACK: Record<string, string> = {
  home: "96 165 250", draw: "148 163 184", away: "251 146 60", pos: "52 211 153", neg: "248 113 113", brand: "52 211 153",
  "ink-3": "148 163 184", "ink-4": "100 116 139", line: "29 38 58",
};
/** Theme colour as an rgb() string. Charts draw SVG attributes, which cannot resolve CSS variables. */
export function color(name: string, alpha = 1): string {
  let v = "";
  if (typeof window !== "undefined") v = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return `rgb(${(v || FALLBACK[name] || "128 128 128").split(" ").join(", ")}${alpha < 1 ? `, ${alpha}` : ""})`;
}
export const chart = () => ({
  axis: color("ink-4"), grid: color("line"), fontSize: 11,
  series: [color("home"), color("away"), color("brand")],
  outcome: { home: color("home"), draw: color("draw"), away: color("away") },
});

/* ------------------------------------------------------------------ layout */
export function PageHeader({ title, description, actions, eyebrow }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode;
}) {
  return (
    <header className="mb-6 sm:mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between animate-rise">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-2 !text-brand">{eyebrow}</div>}
        <h1 className="text-[28px] sm:text-[36px] font-extrabold leading-[1.1]">{title}</h1>
        {description && <p className="mt-2 text-[15px] text-ink-3 max-w-xl">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 min-w-0">{actions}</div>}
    </header>
  );
}

export function Card({ title, subtitle, action, children, className, flush, info }: {
  title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
  flush?: boolean; info?: string;
}) {
  return (
    <section className={cx("card", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 px-4 sm:px-5 pt-4 sm:pt-5">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-bold flex items-center gap-1.5">{title}{info && <InfoTip text={info} />}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] text-ink-3">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={cx(flush ? "pt-2" : "p-4 sm:p-5", title && !flush && "pt-3 sm:pt-4")}>{children}</div>
    </section>
  );
}

/** A section heading outside a card. */
export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-base font-bold">{children}</h2>
      {action}
    </div>
  );
}

const TONE_TEXT: Record<Tone, string> = { neutral: "text-ink", pos: "text-pos", neg: "text-neg", warn: "text-warn", brand: "text-ink" };

export function StatTile({ label, value, hint, tone, info }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone; info?: string }) {
  return (
    <div className="card px-4 py-3.5 sm:px-5 sm:py-4">
      <div className="label flex items-center gap-1 min-w-0"><span className="truncate">{label}</span>{info && <InfoTip text={info} />}</div>
      <div className={cx("mt-1.5 text-[22px] sm:text-[26px] font-extrabold num tracking-[-0.02em] leading-tight break-words", TONE_TEXT[tone ?? "neutral"])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

/** Label / value pairs in a row, e.g. "Our chance 54%". */
export function Figures({ items, className }: { items: [string, ReactNode, Tone?, string?][]; className?: string }) {
  return (
    <dl className={cx("grid gap-3", className)} style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      {items.map(([label, value, tone, info]) => (
        <div key={label} className="min-w-0">
          <dt className="label flex items-center gap-0.5"><span className="truncate">{label}</span>{info && <InfoTip text={info} />}</dt>
          <dd className={cx("mt-0.5 text-[15px] font-bold num", TONE_TEXT[tone ?? "neutral"])}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ states */
export function Loading({ label = "Loading", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-4 py-1">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="space-y-2">
          <div className="skeleton h-3.5" style={{ width: `${78 - i * 9}%` }} />
          <div className="skeleton h-3 w-1/3" />
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Unknown error";
  return (
    <div role="alert" className="card flex gap-3 px-4 py-4">
      <Icon name="alert" size={18} className="text-neg shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Something went wrong loading this</p>
        <p className="mt-0.5 text-[13px] text-ink-3 break-words">{msg}</p>
        {onRetry && <button className="btn btn-sm mt-3" onClick={onRetry}><Icon name="refresh" size={13} />Retry</button>}
      </div>
    </div>
  );
}

export function Empty({ title, children, icon = "info", action }: { title: string; children?: ReactNode; icon?: IconName; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center py-10 px-4">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-brand/10 text-brand ring-1 ring-inset ring-brand/20"><Icon name={icon} size={22} /></span>
      <p className="text-base font-bold">{title}</p>
      {children && <div className="mt-1.5 text-sm text-ink-3 max-w-sm">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ pills */
const TONES: Record<Tone, string> = {
  neutral: "bg-subtle text-ink-2",
  pos: "bg-pos/10 text-pos",
  neg: "bg-neg/10 text-neg",
  warn: "bg-warn/10 text-warn",
  brand: "bg-brand/15 text-brand",
};

export function Pill({ tone = "neutral", icon, children, className, title }: { tone?: Tone; icon?: IconName; children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={cx("pill", TONES[tone], className)}>{icon && <Icon name={icon} size={12} />}{children}</span>;
}

/** Match verdict in plain language (words, not colour alone). */
export function ClassificationBadge({ value, short = false }: { value: string; short?: boolean }) {
  const v = verdict(value);
  return <Pill tone={v.tone} title={v.explain}>{short ? v.short : v.label}</Pill>;
}

/** Data confidence (prediction reliability), separate from the outcome probability. */
export function ReliabilityBadge({ score, label, compact = false }: { score: number; label: string; compact?: boolean }) {
  const c = CONFIDENCE[label] ?? { label, tone: "neutral" as Tone };
  const dot = c.tone === "pos" ? "bg-pos" : c.tone === "warn" ? "bg-warn" : "bg-neg";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-3 whitespace-nowrap" title={`Data confidence ${Math.round(score)}/100 (${label})`}>
      <span aria-hidden className={cx("h-1.5 w-1.5 rounded-full", dot)} />
      {!compact && <span>{c.label}</span>}
      <span className="sr-only">{label}</span>
      <span className="num">{Math.round(score)}</span>
    </span>
  );
}

export function Freshness({ hours, staleAfter = 12, label = "Odds" }: { hours: number | null | undefined; staleAfter?: number; label?: string }) {
  const stale = hours === null || hours === undefined || hours > staleAfter;
  return (
    <span className={cx("inline-flex items-center gap-1 text-xs whitespace-nowrap", stale ? "text-warn" : "text-ink-3")}
          title={stale ? "This data may be out of date" : undefined}>
      {label ? `${label} ` : ""}{age(hours)}
    </span>
  );
}

/* ---------------------------------------------------------------- team crest */
export function TeamLogo({ name, src, size = 32, className }: { name: string; src?: string | null; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const initials = name.replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  // Our crest endpoint serves 100px (tiny) and 200px (small) renditions; pick by display size for sharp 2x output.
  const url = src && src.startsWith("/api/") && size > 48 ? `${src}?size=small` : src;
  const showImg = !!url && !failed;
  return (
    <span className={cx("relative grid place-items-center shrink-0", className)} style={{ width: size, height: size }} aria-hidden>
      {/* Initials double as the loading placeholder, so a crest never leaves an empty gap. */}
      <span className={cx("absolute inset-0 grid place-items-center rounded-full bg-subtle text-ink-3 font-semibold transition-opacity duration-300",
                          showImg && loaded ? "opacity-0" : "opacity-100")}
            style={{ fontSize: Math.max(9, size * 0.34) }}>
        {initials || "?"}
      </span>
      {showImg && (
        <img src={url!} alt="" width={size} height={size} loading="lazy" decoding="async"
             onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
             className={cx("relative object-contain transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0")}
             style={{ width: size, height: size }} />
      )}
    </span>
  );
}

/* --------------------------------------------------------------- data viz */
const OUTCOME_BG = { home: "bg-home", draw: "bg-draw", away: "bg-away" } as const;

/** Home/draw/away split as one bar with labels underneath. */
export function OutcomeBar({ p, labels, size = "sm" }: {
  p: { home?: number; draw?: number; away?: number }; labels?: [string, string, string]; size?: "sm" | "lg";
}) {
  const parts = (["home", "draw", "away"] as const).map((k, i) => ({ k, v: p[k] ?? 0, l: labels?.[i] ?? ["1", "X", "2"][i] }));
  const lead = parts.reduce((a, b) => (b.v > a.v ? b : a));
  return (
    <div className="w-full min-w-0">
      <div className={cx("flex gap-0.5 overflow-hidden rounded-full", size === "lg" ? "h-2" : "h-1.5")} role="img"
           aria-label={parts.map((x) => `${x.l} ${pct(x.v, 0)}`).join(", ")}>
        {parts.map((x) => <div key={x.k} className={OUTCOME_BG[x.k]} style={{ width: `${x.v * 100}%`, opacity: x === lead ? 1 : 0.45 }} />)}
      </div>
      <div className={cx("mt-2 grid grid-cols-3 num", size === "lg" ? "text-sm" : "text-xs")}>
        {parts.map((x, i) => (
          <span key={x.k} className={cx("truncate", i === 1 ? "text-center" : i === 2 ? "text-right" : "",
                                         x === lead ? "text-ink font-semibold" : "text-ink-3")}>
            {`${x.l} ${pct(x.v, 0)}`}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Three compact 1 / X / 2 percentages; the most likely result is emphasised. */
export function ProbChips({ p }: { p: { home?: number; draw?: number; away?: number } }) {
  const items = [["1", p.home ?? 0], ["X", p.draw ?? 0], ["2", p.away ?? 0]] as const;
  const max = Math.max(...items.map(([, v]) => v));
  return (
    <div className="grid grid-cols-3 gap-1" role="img" aria-label={items.map(([k, v]) => `${k} ${pct(v, 0)}`).join(", ")}>
      {items.map(([k, v]) => (
        <span key={k} className={cx("flex flex-col items-center rounded-lg py-1.5 ring-1 ring-inset",
                                    v === max ? "bg-brand/10 text-brand ring-brand/30" : "bg-bg/40 text-ink-3 ring-line")}>
          <span className={cx("text-[10px] font-bold leading-none", v === max ? "text-brand/70" : "text-ink-4")}>{k}</span>
          <span className={cx("mt-1 text-[13px] num leading-none", v === max ? "font-extrabold" : "font-semibold")}>{pct(v, 0)}</span>
        </span>
      ))}
    </div>
  );
}

export function FormPills({ seq, max = 5, size = 20 }: { seq: string; max?: number; size?: number }) {
  return (
    <span className={cx("inline-flex", size < 16 ? "gap-0.5" : "gap-1")} aria-label={`Last results: ${seq.slice(0, max)}`}>
      {seq.split("").slice(0, max).map((r, i) => (
        <span key={i} style={{ width: size, height: size, fontSize: Math.max(9, size * 0.5) }}
              className={cx("grid place-items-center rounded-md font-semibold",
                r === "W" ? "bg-pos/15 text-pos" : r === "L" ? "bg-neg/15 text-neg" : "bg-subtle text-ink-3")}>{r}</span>
      ))}
    </span>
  );
}

export function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
      {items.map(([n, c]) => <span key={n} className="flex items-center gap-1.5 min-w-0"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: c }} /><span className="truncate">{n}</span></span>)}
    </div>
  );
}

export function ResultLine({ m, extra }: { m: { result: string; venue: string; opponent: string; date: string; goals_for: number; goals_against: number }; extra?: string }) {
  return (
    <li className="flex items-center gap-3 px-4 sm:px-5 py-2.5 text-sm">
      <FormPills seq={m.result} max={1} size={20} />
      <span className="min-w-0 flex-1">
        <span className="block truncate">{m.venue === "H" ? "vs" : "at"} {m.opponent}</span>
        <span className="block text-xs text-ink-4">{fmtDate(m.date)}{extra}</span>
      </span>
      <span className="shrink-0 font-semibold num">{m.goals_for}–{m.goals_against}</span>
    </li>
  );
}

export function ChartTooltip({ active, payload, label, fmt }: { active?: boolean; payload?: any[]; label?: any; fmt?: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-line bg-surface shadow-pop px-3 py-2 text-xs">
      {label !== undefined && <div className="mb-1 text-ink-3">{label}</div>}
      {payload.map((p) => (
        <div key={String(p.dataKey) + p.name} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color ?? p.payload?.fill }} />
          <span className="text-ink-2">{p.name}</span>
          <span className="num ml-auto pl-3 font-semibold">{fmt ? fmt(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- controls */
/** Tabs / segmented control / chips. Scrolls inside itself on small screens, never the page. */
export function Segmented<T extends string>({ value, options, onChange, label, className, variant = "pill" }: {
  value: T; options: { value: T; label: ReactNode; count?: number }[]; onChange: (v: T) => void; label: string;
  className?: string; variant?: "pill" | "chips" | "tabs";
}) {
  if (variant === "tabs") {
    return (
      <div role="tablist" aria-label={label} className={cx("flex gap-5 sm:gap-6 border-b border-line scroll-x", className)}>
        {options.map((o) => (
          <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
                  className={cx("relative h-12 shrink-0 text-sm font-semibold whitespace-nowrap transition-colors",
                                value === o.value ? "text-ink" : "text-ink-3 hover:text-ink")}>
            {o.label}
            {value === o.value && <span aria-hidden className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-gradient-to-r from-brand to-brand-2" />}
          </button>
        ))}
      </div>
    );
  }
  if (variant === "chips") {
    return (
      <div role="tablist" aria-label={label} className={cx("flex gap-1 scroll-x", className)}>
        {options.map((o) => (
          <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)} className="chip">
            {o.label}{o.count !== undefined && <span className={cx("num text-xs", value === o.value ? "opacity-60" : "text-ink-4")}>{o.count}</span>}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div role="tablist" aria-label={label} className={cx("inline-flex max-w-full rounded-xl border border-line bg-surface p-1 gap-1 scroll-x", className)}>
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
                className={cx("h-8 shrink-0 rounded-lg px-3.5 text-[13px] font-semibold transition-colors whitespace-nowrap",
                              value === o.value ? "bg-subtle text-ink shadow-card ring-1 ring-inset ring-line-strong" : "text-ink-3 hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder = "Find a team", className }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string;
}) {
  return (
    <div className={cx("relative min-w-0", className)}>
      <Icon name="search" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
      <input className="input pl-9" type="search" placeholder={placeholder} aria-label={placeholder} value={value}
             onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

export function Field({ label, children, className, hint }: { label: string; children: ReactNode; className?: string; hint?: string }) {
  return (
    <label className={cx("field", className)}>
      <span className="text-[13px] font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="text-xs text-ink-4">{hint}</span>}
    </label>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-3 pt-6 text-[13px] text-ink-3">
      <button className="btn btn-sm btn-icon" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        <Icon name="chevronLeft" size={15} />
      </button>
      <span className="num">Page {page} of {pages}</span>
      <button className="btn btn-sm btn-icon" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        <Icon name="chevronRight" size={15} />
      </button>
    </div>
  );
}

/** Small ⓘ button that explains a term. The popover is fixed-positioned and clamped to the screen. */
export function InfoTip({ text }: { text: string }) {
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const id = useId();
  const ref = useRef<HTMLButtonElement>(null);
  const open = pos !== null;
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => { if (!ref.current?.contains(e.target as Node)) setPos(null); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setPos(null);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);
  const toggle = () => {
    if (open) return setPos(null);
    const r = ref.current!.getBoundingClientRect();
    const width = Math.min(256, window.innerWidth - 24);
    setPos({ left: Math.min(Math.max(12, r.left + r.width / 2 - width / 2), window.innerWidth - width - 12), top: r.bottom + 8 });
  };
  return (
    <span className="inline-flex align-middle">
      <button ref={ref} type="button" aria-label="What does this mean?" aria-expanded={open} aria-describedby={open ? id : undefined}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggle(); }}
              className="grid place-items-center h-5 w-5 rounded-full text-ink-4 hover:text-ink-2 transition-colors">
        <Icon name="info" size={13} />
      </button>
      {pos && (
        <span id={id} role="tooltip" style={{ left: pos.left, top: pos.top, width: Math.min(256, window.innerWidth - 24) }}
              className="fixed z-50 rounded-xl border border-line bg-surface shadow-pop p-3 text-xs font-normal text-ink-2 leading-relaxed animate-fade-in">
          {text}
        </span>
      )}
    </span>
  );
}

/** Bottom sheet on phones, centred dialog on larger screens. */
export function Sheet({ open, onClose, title, children, footer }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:p-6" role="dialog" aria-modal="true" aria-label={title}>
      <button className="absolute inset-0 bg-black/40 animate-fade-in" aria-label="Close" onClick={onClose} />
      <div className="relative w-full sm:max-w-lg max-h-[88dvh] flex flex-col rounded-t-2xl sm:rounded-2xl bg-surface shadow-pop animate-sheet-in sm:animate-fade-in">
        <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="px-5 pb-5 overflow-y-auto">{children}</div>
        {footer && <div className="px-5 py-4 border-t border-line safe-bottom">{footer}</div>}
      </div>
    </div>
  );
}

export function KeyValue({ items, className }: { items: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cx("divide-soft", className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 py-2.5 text-sm">
          <dt className="text-ink-3 min-w-0">{k}</dt>
          <dd className="num font-medium text-right shrink-0 whitespace-nowrap">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A collapsible row. Inside a `divide-soft` card they stack as one list. */
export function Disclosure({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="min-w-0">
      <button className="w-full flex items-center justify-between gap-3 px-4 sm:px-5 py-4 text-left text-sm font-semibold hover:bg-subtle/40 transition-colors"
              aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="min-w-0">{title}</span>
        <Icon name="chevronDown" size={16} className={cx("text-ink-4 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="px-4 sm:px-5 pb-5 animate-fade-in">{children}</div>}
    </div>
  );
}
