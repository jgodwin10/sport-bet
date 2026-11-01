/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see index.css) so one set of class names serves light and dark mode.
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
        pos: token("pos"),
        neg: token("neg"),
        warn: token("warn"),
        home: token("home"),
        draw: token("draw"),
        away: token("away"),
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      boxShadow: {
        pop: "0 1px 2px rgb(0 0 0 / 0.06), 0 12px 32px -8px rgb(0 0 0 / 0.18)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        "sheet-in": { from: { transform: "translateY(100%)" }, to: { transform: "translateY(0)" } },
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        "sheet-in": "sheet-in 240ms cubic-bezier(.2,.9,.25,1)",
        "fade-in": "fade-in 160ms ease-out",
      },
    },
  },
  plugins: [],
};
