import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // All /api/* calls forwarded to Django — no CORS in dev
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Django auth (GitHub OAuth callback lives here)
      '/accounts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // WebSocket pipeline progress
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    // Output to backend/static/frontend/ so Django can serve it via WhiteNoise
    outDir: '../backend/static/frontend',
    emptyOutDir: true,
  },
})
