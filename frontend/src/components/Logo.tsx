import { useId } from "react";

/** Oddsmith mark: an "O" ring with a rising trend line breaking out through its gap. Same geometry as the favicon. */
export function LogoMark({ size = 30, className }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden className={className}>
      <defs>
        <linearGradient id={`om-${id}`} x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#8EC5FF" /><stop offset="1" stopColor="#3F7CEB" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="16" fill={`url(#om-${id})`} />
      <g stroke="#FFFFFF" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16.7 8.03A8 8 0 1 0 23.97 16.7" />
        <path d="M10.5 19l3.2-3.2 3 3L25 10.5" />
        <path d="M21.8 10.5H25v3.2" />
      </g>
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark size={compact ? 28 : 30} />
      <span className="text-[17px] font-extrabold tracking-[-0.03em] leading-none">
        Odd<span className="text-gradient">smith</span>
      </span>
    </span>
  );
}
