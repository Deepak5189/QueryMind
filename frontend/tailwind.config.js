/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#0B0E13",
          800: "#12161D",
          700: "#1A2029",
          600: "#242C38",
          500: "#333D4C",
        },
        parchment: {
          100: "#F2EFE7",
          300: "#D9D3C4",
        },
        ledger: {
          gold: "#D4A643",
          goldDim: "#8A6E30",
          teal: "#4FB286",
          tealDim: "#2E5A47",
          clay: "#E2694B",
          clayDim: "#7A362A",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "'Segoe UI'",
          "Inter",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "'SFMono-Regular'",
          "'JetBrains Mono'",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      backgroundImage: {
        "scanline-gold":
          "linear-gradient(90deg, transparent 0%, #D4A643 20%, #D4A643 80%, transparent 100%)",
      },
    },
  },
  plugins: [],
};
