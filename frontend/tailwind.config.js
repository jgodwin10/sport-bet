/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        night: { DEFAULT: "#060b18", 2: "#0a1224", 3: "#0f1a33" },
        // Text
        ink: { DEFAULT: "#f1f5fb", 2: "#b3bfd3", 3: "#7d8aa3", 4: "#56627a" },
        // Brand: pitch green
        brand: { DEFAULT: "#22c55e", strong: "#4ade80", deep: "#15803d", soft: "rgba(34,197,94,0.14)" },
        pos: { DEFAULT: "#34d399", soft: "rgba(52,211,153,0.14)" },
        neg: { DEFAULT: "#fb7185", soft: "rgba(251,113,133,0.14)" },
        warn: { DEFAULT: "#fbbf24", soft: "rgba(251,191,36,0.14)" },
        // Outcome data colours (validated for colour-vision separation on dark surfaces)
        home: "#3987e5",
        away: "#d95926",
        draw: "#8592a8",
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      borderRadius: { "4xl": "28px" },
      boxShadow: {
        glass: "inset 0 1px 0 0 rgba(255,255,255,0.07), 0 10px 30px -12px rgba(0,0,0,0.55)",
        lift: "inset 0 1px 0 0 rgba(255,255,255,0.09), 0 24px 48px -16px rgba(0,0,0,0.7)",
        glow: "0 0 0 1px rgba(34,197,94,0.35), 0 8px 24px -6px rgba(34,197,94,0.45)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        "sheet-in": { from: { transform: "translateY(100%)" }, to: { transform: "translateY(0)" } },
        "fade-up": { from: { opacity: 0, transform: "translateY(6px)" }, to: { opacity: 1, transform: "translateY(0)" } },
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        "sheet-in": "sheet-in 260ms cubic-bezier(.2,.9,.25,1)",
        "fade-up": "fade-up 320ms cubic-bezier(.2,.9,.25,1) both",
        "fade-in": "fade-in 180ms ease-out",
      },
    },
  },
  plugins: [],
};
