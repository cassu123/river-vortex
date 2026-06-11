/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/vite.config.js
 * Purpose:  Vite build configuration for the React kiosk UI. Production
 *           builds output to frontend/dist, which is served as static
 *           files by the FastAPI backend (see core/main.py). In development,
 *           REST and WebSocket requests under /api are proxied to the local
 *           backend so the UI can run on its own dev server port.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
