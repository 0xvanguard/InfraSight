import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "rgb(15 17 22)",
        surface: "rgb(24 27 33)",
        border: "rgb(45 50 60)",
        foreground: "rgb(229 231 235)",
        muted: "rgb(148 163 184)",
        accent: "rgb(99 179 237)",
        ok: "rgb(34 197 94)",
        warn: "rgb(234 179 8)",
        bad: "rgb(239 68 68)",
      },
    },
  },
  plugins: [],
};

export default config;
