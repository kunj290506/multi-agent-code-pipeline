import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/models': 'http://127.0.0.1:8000',
      '/sessions': 'http://127.0.0.1:8000',
      '/files': 'http://127.0.0.1:8000',
      '/run': 'http://127.0.0.1:8000',
      '/llm': 'http://127.0.0.1:8000',
      '/audit': 'http://127.0.0.1:8000',
      '/preview': 'http://127.0.0.1:8000',
    },
  },
  build: {
    target: 'esnext',
    cssCodeSplit: true,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules/three')) return 'vendor-three'
          if (id.includes('node_modules/gsap')) return 'vendor-gsap'
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom') || id.includes('node_modules/react-router-dom')) return 'vendor-react'
          if (id.includes('node_modules/lucide-react') || id.includes('node_modules/prismjs') || id.includes('node_modules/lenis')) return 'vendor-ui'
        },
      },
    },
  },
})
