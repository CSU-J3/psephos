// Tailwind v4 is CSS-first: the PostCSS plugin is the whole config. No
// tailwind.config.ts, no content globs -- utilities are discovered from source.
export default {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
