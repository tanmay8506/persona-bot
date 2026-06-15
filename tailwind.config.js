/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        charcoal: {
          900: "#121212",
          800: "#1a1a1a",
          700: "#2d2d2d",
          600: "#3d3d3d",
        },
      },
    },
  },
  plugins: [],
}
