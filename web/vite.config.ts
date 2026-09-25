import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: the React app runs on :5173 and proxies /api + /jobs (SSE) to the
// FastAPI backend on :8000, so the UI can call same-origin `/api/...`.
// Prod: `vite build` emits web/dist, which FastAPI serves at `/` — same
// origin, no proxy needed.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
