import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // dev: proxy API to the FastAPI instance (single-port in prod)
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
