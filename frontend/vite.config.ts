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
      '/sessions': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (req.headers.accept && req.headers.accept.includes('text/event-stream')) {
              proxyReq.setHeader('Connection', 'keep-alive');
            }
          });
          proxy.on('proxyRes', (proxyRes) => {
            const ct = proxyRes.headers['content-type'];
            if (ct && ct.includes('text/event-stream')) {
              proxyRes.socket?.setTimeout(0);
              proxyRes.socket?.setNoDelay(true);
              proxyRes.socket?.setKeepAlive(true);
            }
          });
        },
      },
      '/files': 'http://127.0.0.1:8000',
      '/run': 'http://127.0.0.1:8000',
      '/llm': 'http://127.0.0.1:8000',
      '/audit': 'http://127.0.0.1:8000',
      '/preview': 'http://127.0.0.1:8000',
      '/approvals': 'http://127.0.0.1:8000',
      '/workspace': 'http://127.0.0.1:8000',
      '/internal': 'http://127.0.0.1:8000',
    },
  },
  build: {
    target: 'esnext',
    cssCodeSplit: true,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) return 'vendor-react'
        },
      },
    },
  },
})
