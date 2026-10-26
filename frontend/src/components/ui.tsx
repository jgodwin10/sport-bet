import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { age, pct } from "../lib/format";
import { CONFIDENCE, verdict, type Tone } from "../lib/language";
import { Icon, type IconName } from "./icons";

/** Chart palette — validated for colour-vision separation and ≥3:1 contrast on the glass surface. */
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"] as const;
export const OUTCOME_COLORS = { home: "#3987e5", draw: "#8592a8", away: "#d95926" } as const;
export const AXIS = { stroke: "#56627a", grid: "rgba(255,255,255,0.06)", fontSize: 11 } as const;

export function cx(...parts: (string | number | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ layout */
export function PageHeader({ title, description, actions, eyebrow }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode;
}) {
  return (
    <header className="mb-6 sm:mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between animate-fade-up">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-2 text-brand-strong">{eyebrow}</div>}
        <h1 className="h-page">{title}</h1>
        {description && <p className="mt-2 text-[14.5px] text-ink-2 max-w-2xl leading-relaxed">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, subtitle, action, children, className, bodyClassName, flush, info }: {
  title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
  bodyClassName?: string; flush?: boolean; info?: string;
}) {
  return (
    <section className={cx("card min-w-0", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 px-5 sm:px-6 pt-5 sm:pt-6">
          <div className="min-w-0">
            {title && (
              <h2 className="h-section flex items-center gap-1.5">
                {title}{info && <InfoTip text={info} />}
              </h2>
            )}
            {subtitle && <p className="mt-1 text-[13px] text-ink-3 leading-snug">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={cx(flush ? "pt-4" : "p-5 sm:p-6", title && !flush && "pt-4 sm:pt-5", bodyClassName)}>{children}</div>
    </section>
  );
}

export function StatTile({ label, value, hint, tone, icon, info }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: Tone; icon?: IconName; info?: string;
}) {
  const color = tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : tone === "warn" ? "text-warn" : tone === "brand" ? "text-brand-strong" : "text-ink";
  return (
    <div className="card px-4 py-4 sm:px-5 min-w-0">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-ink-3">
        {icon && <Icon name={icon} size={14} />}<span className="truncate">{label}</span>{info && <InfoTip text={info} />}
      </div>
      <div className={cx("mt-2 text-[22px] sm:text-[28px] leading-none font-extrabold num tracking-[-0.03em]", color)}>{value}</div>
      {hint && <div className="mt-2 text-xs text-ink-3 leading-snug">{hint}</div>}
    </div>
  );
}
/** Back-compat alias. */
export const StatCard = StatTile;

/* ------------------------------------------------------------------ states */
export function Loading({ label = "Loading", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-4 py-1">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="skeleton h-10 w-10 rounded-full shrink-0" />
          <div className="flex-1 space-y-2">
            <div className="skeleton h-3.5" style={{ width: `${72 - i * 9}%` }} />
            <div className="skeleton h-3 w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Unknown error";
  return (
    <div role="alert" className="flex gap-3 rounded-2xl border border-neg/25 bg-neg-soft px-4 py-4">
      <Icon name="alert" size={18} className="text-neg shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-semibold text-ink">Something went wrong loading this</p>
        <p className="mt-0.5 text-[13px] text-ink-2 break-words">{msg}</p>
        {onRetry && <button className="btn btn-sm mt-3" onClick={onRetry}><Icon name="refresh" size={13} />Retry</button>}
      </div>
    </div>
  );
}

export function Empty({ title, children, icon = "info", action }: { title: string; children?: ReactNode; icon?: IconName; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center py-12 px-6">
      <div className="grid place-items-center h-14 w-14 rounded-2xl bg-white/[0.06] border border-white/[0.08] text-ink-2 mb-4">
        <Icon name={icon} size={24} />
      </div>
      <p className="text-[16px] font-bold text-ink">{title}</p>
      {children && <div className="mt-2 text-[14px] text-ink-3 max-w-sm leading-relaxed">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ pills */
const TONES: Record<Tone, string> = {
  neutral: "bg-white/[0.07] text-ink-2 ring-1 ring-inset ring-white/[0.1]",
  pos: "bg-pos-soft text-pos ring-1 ring-inset ring-pos/25",
  neg: "bg-neg-soft text-neg ring-1 ring-inset ring-neg/25",
  warn: "bg-warn-soft text-warn ring-1 ring-inset ring-warn/25",
  brand: "bg-brand-soft text-brand-strong ring-1 ring-inset ring-brand/30",
};

export function Pill({ tone = "neutral", icon, children, className, title }: { tone?: Tone; icon?: IconName; children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={cx("pill", TONES[tone], className)}>{icon && <Icon name={icon} size={12} />}{children}</span>;
}
export const Badge = Pill;

const VERDICT_ICON: Record<string, IconName> = { consider: "sparkle", no_bet: "ban", high_uncertainty: "alert" };

/** Match verdict in plain language (never colour alone: icon + words). */
export function ClassificationBadge({ value, short = false }: { value: string; short?: boolean }) {
  const v = verdict(value);
  return <Pill tone={v.tone} icon={VERDICT_ICON[value] ?? "info"} title={v.explain}>{short ? v.short : v.label}</Pill>;
}
export const VerdictPill = ClassificationBadge;

/** Data confidence (prediction reliability) — separate from the outcome probability. */
export function ReliabilityBadge({ score, label, compact = false }: { score: number; label: string; compact?: boolean }) {
  const c = CONFIDENCE[label] ?? { label, tone: "neutral" as Tone };
  const color = c.tone === "pos" ? "bg-pos" : c.tone === "warn" ? "bg-warn" : "bg-neg";
  const filled = Math.max(1, Math.min(4, Math.ceil(score / 25)));
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2" title={`Data confidence ${Math.round(score)}/100 (${label})`}>
      <span className="flex items-end gap-[2px]" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={cx("w-[3px] rounded-full", i < filled ? color : "bg-white/15")} style={{ height: 5 + i * 2.5 }} />
        ))}
      </span>
      {!compact && <span className="font-semibold">{c.label}</span>}
      <span className="sr-only">{label}</span>
      <span className="num text-ink-4">{Math.round(score)}</span>
    </span>
  );
}

export function Freshness({ hours, staleAfter = 12, label = "Odds" }: { hours: number | null | undefined; staleAfter?: number; label?: string }) {
  const stale = hours === null || hours === undefined || hours > staleAfter;
  return (
    <span className={cx("inline-flex items-center gap-1 text-xs whitespace-nowrap", stale ? "text-warn" : "text-ink-3")}
          title={stale ? "This data may be out of date" : undefined}>
      <Icon name={stale ? "alert" : "clock"} size={12} />
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
      {/* Initials badge doubles as the loading placeholder, so a crest never leaves an empty gap. */}
      <span className={cx("absolute inset-0 grid place-items-center rounded-full bg-gradient-to-br from-white/[0.14] to-white/[0.04] ring-1 ring-white/[0.12] text-ink-2 font-bold transition-opacity duration-300",
                          showImg && loaded ? "opacity-0" : "opacity-100")}
            style={{ fontSize: Math.max(9, size * 0.34) }}>
        {initials || "?"}
      </span>
      {showImg && (
        <img src={url!} alt="" width={size} height={size} loading="lazy" decoding="async"
             onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
             className={cx("relative object-contain drop-shadow-[0_2px_6px_rgba(0,0,0,0.45)] transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0")}
             style={{ width: size, height: size }} />
      )}
    </span>
  );
}
/** Back-compat alias used by older call sites. */
export const TeamMark = TeamLogo;

/* --------------------------------------------------------------- data viz */
/** Home/draw/away split with labels in text colour. */
export function OutcomeBar({ p, labels, size = "sm" }: {
  p: { home?: number; draw?: number; away?: number }; labels?: [string, string, string]; size?: "sm" | "lg";
}) {
  const parts = [
    { k: "home", v: p.home ?? 0, c: OUTCOME_COLORS.home, l: labels?.[0] ?? "1" },
    { k: "draw", v: p.draw ?? 0, c: OUTCOME_COLORS.draw, l: labels?.[1] ?? "X" },
    { k: "away", v: p.away ?? 0, c: OUTCOME_COLORS.away, l: labels?.[2] ?? "2" },
  ];
  const lead = parts.reduce((a, b) => (b.v > a.v ? b : a));
  return (
    <div className="w-full min-w-0">
      <div className={cx("flex gap-1 overflow-hidden", size === "lg" ? "h-3 rounded-full" : "h-1.5 rounded-full")} role="img"
           aria-label={parts.map((x) => `${x.l} ${pct(x.v, 0)}`).join(", ")}>
        {parts.map((x) => <div key={x.k} className="rounded-full" style={{ width: `${x.v * 100}%`, background: x.c, opacity: x === lead ? 1 : 0.55 }} />)}
      </div>
      <div className={cx("mt-2 grid grid-cols-3 num", size === "lg" ? "text-[13.5px]" : "text-2xs")}>
        {parts.map((x, i) => (
          <span key={x.k} className={cx("truncate", i === 1 ? "text-center" : i === 2 ? "text-right" : "",
                                         x === lead ? "text-ink font-bold" : "text-ink-3")}>
            {`${x.l} ${pct(x.v, 0)}`}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Three compact probability chips (1 / X / 2) — the most likely outcome is highlighted. */
export function ProbChips({ p }: { p: { home?: number; draw?: number; away?: number } }) {
  const items = [["1", p.home ?? 0], ["X", p.draw ?? 0], ["2", p.away ?? 0]] as const;
  const max = Math.max(...items.map(([, v]) => v));
  return (
    <div className="grid grid-cols-3 gap-1.5" role="img" aria-label={items.map(([k, v]) => `${k} ${pct(v, 0)}`).join(", ")}>
      {items.map(([k, v]) => (
        <span key={k} className={cx("flex flex-col items-center justify-center rounded-xl py-1.5 min-w-[46px]",
                                    v === max ? "bg-white text-night" : "bg-white/[0.06] text-ink-2")}>
          <span className={cx("text-[10px] font-bold leading-none", v === max ? "text-night/60" : "text-ink-4")}>{k}</span>
          <span className="mt-1 text-[13px] font-extrabold num leading-none">{pct(v, 0)}</span>
        </span>
      ))}
    </div>
  );
}

export function FormPills({ seq, max = 5, size = 20 }: { seq: string; max?: number; size?: number }) {
  return (
    <span className="inline-flex gap-1" aria-label={`Last results: ${seq.slice(0, max)}`}>
      {seq.split("").slice(0, max).map((r, i) => (
        <span key={i} style={{ width: size, height: size }}
              className={cx("grid place-items-center rounded-md text-[10px] font-extrabold",
                r === "W" ? "bg-pos/20 text-pos" : r === "L" ? "bg-neg/20 text-neg" : "bg-white/10 text-ink-2")}>{r}</span>
      ))}
    </span>
  );
}

export function ChartTooltip({ active, payload, label, fmt }: { active?: boolean; payload?: any[]; label?: any; fmt?: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass-strong rounded-xl px-3 py-2 text-xs">
      {label !== undefined && <div className="mb-1 text-ink-3">{label}</div>}
      {payload.map((p) => (
        <div key={String(p.dataKey) + p.name} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color ?? p.payload?.fill }} />
          <span className="text-ink-2">{p.name}</span>
          <span className="num ml-auto pl-3 text-ink font-bold">{fmt ? fmt(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- controls */
/** Tabs / segmented control. Scrolls horizontally on small screens. */
export function Segmented<T extends string>({ value, options, onChange, label, className, variant = "pill", fill = false }: {
  value: T; options: { value: T; label: ReactNode; count?: number }[]; onChange: (v: T) => void; label: string;
  className?: string; variant?: "pill" | "chips"; fill?: boolean;
}) {
  if (variant === "chips") {
    return (
      <div role="tablist" aria-label={label} className={cx("flex gap-2 scroll-x no-scrollbar", className)}>
        {options.map((o) => (
          <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)} className="chip-btn">
            {o.label}{o.count !== undefined && <span className={cx("num text-[11px]", value === o.value ? "text-night/60" : "text-ink-4")}>{o.count}</span>}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div role="tablist" aria-label={label}
         className={cx("glass max-w-full rounded-full p-1 gap-1", fill ? "grid w-full sm:w-auto sm:inline-flex" : "inline-flex scroll-x no-scrollbar", className)}
         style={fill ? { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` } : undefined}>
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
                className={cx("h-9 shrink-0 rounded-full text-[13.5px] font-semibold transition-all whitespace-nowrap", fill ? "px-2 sm:px-4 text-[13px] sm:text-[13.5px]" : "px-4",
                              value === o.value ? "bg-white text-night shadow-sm" : "text-ink-2 hover:text-ink hover:bg-white/[0.06]")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, className, hint }: { label: string; children: ReactNode; className?: string; hint?: string }) {
  return (
    <label className={cx("field", className)}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="text-2xs text-ink-4">{hint}</span>}
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
      <span className="num text-ink-2">Page {page} of {pages}</span>
      <button className="btn btn-sm btn-icon" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        <Icon name="chevronRight" size={15} />
      </button>
    </div>
  );
}

/** Small ⓘ button that explains a term in plain language. Works with tap and keyboard. */
export function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <span ref={ref} className="relative inline-flex align-middle">
      <button type="button" aria-label="What does this mean?" aria-expanded={open} aria-describedby={open ? id : undefined}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}
              className="grid place-items-center h-5 w-5 rounded-full text-ink-4 hover:text-ink-2 hover:bg-white/10 transition-colors">
        <Icon name="info" size={13} />
      </button>
      {open && (
        <span id={id} role="tooltip"
              className="glass-strong absolute left-1/2 top-full z-40 mt-2 w-64 -translate-x-1/2 rounded-2xl p-3 text-xs font-normal normal-case tracking-normal text-ink-2 leading-relaxed animate-fade-in">
          {text}
        </span>
      )}
    </span>
  );
}

/** Bottom sheet on mobile, centred dialog on larger screens. */
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
      <button className="absolute inset-0 bg-black/55 backdrop-blur-sm animate-fade-in" aria-label="Close" onClick={onClose} />
      <div className="glass-strong relative w-full sm:max-w-lg max-h-[88dvh] flex flex-col rounded-t-[28px] sm:rounded-[28px] animate-sheet-in sm:animate-fade-up">
        <div className="sm:hidden mx-auto mt-2.5 h-1.5 w-11 rounded-full bg-white/20" aria-hidden />
        <div className="flex items-center justify-between px-6 pt-4 pb-3">
          <h2 className="text-[17px] font-bold">{title}</h2>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="px-6 pb-5 overflow-y-auto">{children}</div>
        {footer && <div className="px-6 py-4 border-t border-white/[0.07] safe-bottom">{footer}</div>}
      </div>
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-soft">
      {items.map(([k, v], i) => (
        <div key={i} className="flex items-center justify-between gap-4 py-3 text-[13.5px]">
          <dt className="text-ink-2 min-w-0">{k}</dt>
          <dd className="num text-ink font-semibold text-right shrink-0">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Disclosure({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card overflow-hidden">
      <button className="w-full flex items-center justify-between gap-3 px-5 sm:px-6 py-4 text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="h-section">{title}</span>
        <Icon name="chevronDown" size={18} className={cx("text-ink-3 transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="px-5 sm:px-6 pb-6 animate-fade-in">{children}</div>}
    </div>
  );
}
