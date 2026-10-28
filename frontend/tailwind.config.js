/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces: page, card, raised (solid, no blur)
        night: { DEFAULT: "#0a0c0f", 2: "#121519", 3: "#191d23" },
        line: { DEFAULT: "#23282f", strong: "#2f353e" },
        // Text
        ink: { DEFAULT: "#f3f5f7", 2: "#b4bcc8", 3: "#808a98", 4: "#5a6370" },
        // Brand: scoreboard lime
        brand: { DEFAULT: "#c6f135", strong: "#d7ff4f", deep: "#8fb31a", soft: "rgba(198,241,53,0.12)", ink: "#0a0c0f" },
        pos: { DEFAULT: "#3ddc97", soft: "rgba(61,220,151,0.12)" },
        neg: { DEFAULT: "#ff6b7a", soft: "rgba(255,107,122,0.12)" },
        warn: { DEFAULT: "#ffb84d", soft: "rgba(255,184,77,0.12)" },
        // Outcome data colours (validated for colour-vision separation on dark surfaces)
        home: "#3d8bfd",
        away: "#f0763a",
        draw: "#8b95a5",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ["'Barlow Condensed'", "Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      borderRadius: { "4xl": "28px" },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.03) inset",
        pop: "0 1px 0 0 rgba(255,255,255,0.05) inset, 0 18px 40px -12px rgba(0,0,0,0.7)",
        glow: "0 6px 20px -6px rgba(198,241,53,0.45)",
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
        "fade-up": "fade-up 280ms cubic-bezier(.2,.9,.25,1) both",
        "fade-in": "fade-in 160ms ease-out",
      },
    },
  },
  plugins: [],
};
