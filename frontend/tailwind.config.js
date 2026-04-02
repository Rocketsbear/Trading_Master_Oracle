/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          50: '#1a1a2e',
          100: '#16213e',
          200: '#0f3460',
          300: '#1a1a2e',
          800: '#0f0f1a',
          900: '#050510',
        },
        accent: {
          500: '#e94560',
          600: '#d63850',
        }
      }
    },
  },
  plugins: [],
}
