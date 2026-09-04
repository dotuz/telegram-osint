import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e14",
        panel: "#141922",
        border: "#232a36",
        muted: "#8b95a5",
        accent: "#4c8dff",
      },
    },
  },
  plugins: [],
};
export default config;
