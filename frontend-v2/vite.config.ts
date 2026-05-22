import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import path from 'node:path';

// CARA PWA v2 — Vite config.
// Backend già esistente su https://192.168.1.23:8455/api. In dev usiamo
// proxy verso quello stesso host; in prod il container nginx serve i
// file statici e proxa /api allo stesso cara-backend.

export default defineConfig({
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': {
        target: 'https://192.168.1.23:8455',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
    },
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,webp,woff2,ico,json}'],
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
      },
      manifest: {
        name: 'CARA — Casa Pedoto',
        short_name: 'CARA',
        description: 'Assistente AI domestica della famiglia Pedoto',
        lang: 'it',
        theme_color: '#FFFFFF',
        background_color: '#FFFFFF',
        display: 'standalone',
        orientation: 'any',
        start_url: '/?source=pwa',
        scope: '/',
        icons: [
          { src: '/icons/cara-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/cara-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/cara-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
        shortcuts: [
          { name: 'Parla con CARA', short_name: 'Voce', url: '/?action=voice' },
          { name: 'Nuova task', short_name: 'Task', url: '/list/tasks?new=1' },
          { name: 'Spesa', short_name: 'Spesa', url: '/list/shopping' },
          { name: 'Promemoria', short_name: 'Ricordi', url: '/list/reminders' },
        ],
      },
      devOptions: {
        enabled: false,  // niente SW in dev — solo prod build
      },
    }),
  ],
  build: {
    target: 'es2022',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          motion: ['framer-motion'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
});
