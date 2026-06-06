/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // GitHub-inspired dark palette
        canvas: {
          DEFAULT: '#0d1117',
          subtle: '#161b22',
          inset: '#010409',
        },
        border: {
          DEFAULT: '#30363d',
          muted: '#21262d',
        },
        fg: {
          DEFAULT: '#c9d1d9',
          muted: '#8b949e',
          subtle: '#6e7681',
        },
        accent: {
          DEFAULT: '#58a6ff',
          emphasis: '#1f6feb',
        },
        success: {
          DEFAULT: '#3fb950',
          subtle: '#1b4721',
        },
        danger: {
          DEFAULT: '#f85149',
          subtle: '#3d1f1f',
        },
        warning: {
          DEFAULT: '#f97316',
          subtle: '#3d1a00',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['SFMono-Regular', 'Consolas', 'Liberation Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
