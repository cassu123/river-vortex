/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/vite.config.js
 * Purpose:  Vite build configuration for the kiosk UI. Builds to frontend/dist,
 *           which core/main.py mounts as static files (FRONTEND_BUILD_DIR).
 *           In dev, proxies /api to the local FastAPI backend so the React dev
 *           server and the Python backend can run side by side.
 * ============================================================================
 */

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend port must match VORTEX_BACKEND_PORT / constants.BACKEND_PORT.
const BACKEND = 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],

  // Served from the backend root in kiosk mode.
  base: '/',

  build: {
    // core/main.py mounts this directory. Do not rename without updating
    // FRONTEND_BUILD_DIR in core/constants.py.
    outDir: 'dist',
    emptyOutDir: true,
    // Pi 4 Chromium — no need to ship legacy transpilation, but keep the
    // bundle small since it loads off an SD card.
    target: 'es2020',
    sourcemap: false,
  },

  server: {
    port: 3000,
    host: true, // allow hitting the dev server from the Pi over the LAN
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        ws: true, // /api/ws presence + state channel
      },
    },
  },
});
