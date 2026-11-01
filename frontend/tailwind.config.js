/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see index.css) so the palette lives in one place.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        subtle: token("subtle"),
        line: { DEFAULT: token("line"), strong: token("line-strong") },
        ink: { DEFAULT: token("ink"), 2: token("ink-2"), 3: token("ink-3"), 4: token("ink-4") },
        brand: { DEFAULT: token("brand"), 2: token("brand-2"), ink: token("brand-ink") },
        pos: token("pos"),
        neg: token("neg"),
        warn: token("warn"),
        home: token("home"),
        draw: token("draw"),
        away: token("away"),
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      boxShadow: {
        card: "inset 0 1px 0 0 rgb(255 255 255 / 0.04), 0 1px 2px 0 rgb(0 0 0 / 0.3)",
        pop: "inset 0 1px 0 0 rgb(255 255 255 / 0.06), 0 20px 48px -12px rgb(0 0 0 / 0.7)",
        glow: "0 8px 24px -8px rgb(var(--brand) / 0.55)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        "sheet-in": { from: { transform: "translateY(100%)" }, to: { transform: "translateY(0)" } },
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "rise": { from: { opacity: 0, transform: "translateY(6px)" }, to: { opacity: 1, transform: "translateY(0)" } },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        "sheet-in": "sheet-in 240ms cubic-bezier(.2,.9,.25,1)",
        "fade-in": "fade-in 160ms ease-out",
        rise: "rise 320ms cubic-bezier(.2,.9,.25,1) both",
      },
    },
  },
  plugins: [],
};
