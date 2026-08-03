/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50:  "#fafafa",
          100: "#ededee",
          200: "#cfcfd3",
          250: "#bcbcc2",
          300: "#a3a3af",
          400: "#7e7e8b",
          500: "#5a5a68",
          600: "#3a3a47",
          700: "#262630",
          800: "#1c1c22",
          850: "#15151a",
          900: "#111114",
          950: "#0a0a0b",
        },
        brand: {
          50:  "#f0f9ff",
          100: "#e0f2fe",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          sky: '#38bdf8',
          surface: '#0a0a0b',
          'surface-low': '#131314',
          'surface-bright': '#3a393a',
          text: '#fafafa',
          'text-muted': '#cfcfd3',
          border: 'rgba(255, 255, 255, 0.08)',
        },
        accent: {
          400: "#c084fc",
          500: "#a855f7",
          600: "#9333ea",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      boxShadow: {
        glass:
          "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 32px -8px rgba(0,0,0,0.6)",
        glow: "0 0 0 1px rgba(56,189,248,0.25), 0 0 24px -4px rgba(56,189,248,0.4)",
      },
      backgroundImage: {
        "grid-faint":
          "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
      },
      animation: {
        "pulse-slow": "pulse 3s ease-in-out infinite",
        float: "float 6s ease-in-out infinite",
      },
      keyframes: {
        float: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
      },
    },
  },
  plugins: [],
};