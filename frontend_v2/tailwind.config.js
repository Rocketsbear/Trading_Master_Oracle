/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      colors: {
        brand: {
          green: '#00e887',
          blue: '#00b4ff',
          purple: '#a855f7',
          cyan: '#06d6a0',
        },
        bull: '#00e887',
        bear: '#ff4757',
        surface: {
          0: '#08090c',
          1: '#0d0f14',
          2: '#12151c',
          3: '#181c25',
          4: '#1e2330',
        },
        dark: {
          600: '#525252',
          700: '#404040',
          800: '#262626',
          900: '#171717',
        }
      },
      borderColor: {
        glass: 'rgba(255, 255, 255, 0.08)',
      },
      backgroundColor: {
        glass: 'rgba(18, 21, 28, 0.7)',
      },
      backdropBlur: {
        glass: '20px',
      },
      boxShadow: {
        'glow-green': '0 0 20px rgba(0, 232, 135, 0.15), 0 0 60px rgba(0, 232, 135, 0.05)',
        'glow-blue': '0 0 20px rgba(0, 180, 255, 0.15), 0 0 60px rgba(0, 180, 255, 0.05)',
        'glow-red': '0 0 20px rgba(255, 71, 87, 0.15), 0 0 60px rgba(255, 71, 87, 0.05)',
        'card': '0 4px 24px rgba(0, 0, 0, 0.2)',
        'card-hover': '0 8px 40px rgba(0, 0, 0, 0.35)',
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'float': 'float 3s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
