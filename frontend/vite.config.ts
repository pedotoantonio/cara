import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

import pkg from './package.json' with { type: 'json' };

const APP_VERSION = pkg.version;
const BUILD_TIME = new Date().toISOString();

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
    __BUILD_TIME__: JSON.stringify(BUILD_TIME),
  },
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'Cara — la casa che ti parla',
        short_name: 'Cara',
        description:
          'Assistente AI di casa: voce naturale, task, spesa, note, ' +
          'appuntamenti, integrazione Google e Home Assistant.',
        lang: 'it',
        // Day-mode color. The browser picks the right one at install time
        // via the <meta name="theme-color" media="..."> in index.html.
        theme_color: '#FAF7F2',
        background_color: '#FAF7F2',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/?source=pwa',
        scope: '/',
        categories: ['productivity', 'lifestyle', 'utilities'],
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
          {
            src: '/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any',
          },
        ],
        // Deep-link shortcuts shown on long-press of the home icon
        // (Android) or in macOS dock context menu.
        shortcuts: [
          {
            name: 'Parla con Cara',
            short_name: 'Voce',
            description: 'Apri direttamente la pagina vocale',
            url: '/?source=shortcut',
            icons: [{ src: '/icon-192.png', sizes: '192x192' }],
          },
          {
            name: 'Le mie task',
            short_name: 'Task',
            description: 'Apri la lista delle cose da fare',
            url: '/tasks?source=shortcut',
            icons: [{ src: '/icon-192.png', sizes: '192x192' }],
          },
          {
            name: 'Lista della spesa',
            short_name: 'Spesa',
            description: 'Apri la lista della spesa',
            url: '/shopping?source=shortcut',
            icons: [{ src: '/icon-192.png', sizes: '192x192' }],
          },
          {
            name: 'Wallet',
            short_name: 'Wallet',
            description: 'Apri il wallet con i widget',
            url: '/wallet?source=shortcut',
            icons: [{ src: '/icon-192.png', sizes: '192x192' }],
          },
        ],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,webp,woff2}'],
      },
    }),
  ],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
});
