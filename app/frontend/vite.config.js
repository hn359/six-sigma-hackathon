import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// base './' makes every asset path relative, so the built dist/ works at any
// URL - including a Posit Connect content path like /content/<guid>/.
export default defineConfig({
  plugins: [react()],
  base: './',
  // two pages: the dispatch console (index.html) and Jim's map preview (map.html)
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
        map: fileURLToPath(new URL('./map.html', import.meta.url)),
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
  },
})
