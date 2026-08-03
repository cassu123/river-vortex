/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/main.jsx
 * Purpose:  React entry point. Mounts <App> into #root. Referenced by
 *           frontend/index.html as the module entry for the Vite build.
 * ============================================================================
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './presence/orb.css';
import './components/photoBackdrop.css';
import './pages/boot.css';
import './surfaces/surfaces.css';
import './pages/settings.css';
import './components/muteBanner.css';

const container = document.getElementById('root');

if (!container) {
  // Kiosk mode has no console visible — fail loudly on screen instead.
  document.body.innerHTML =
    '<pre style="color:#f88;padding:24px;font:14px monospace">' +
    'River Vortex: #root element missing from index.html' +
    '</pre>';
} else {
  // StrictMode double-invokes effects in dev, which would open two
  // WebSockets. The socket layer is idempotent (readyState check in
  // useBackendSocket), so this is safe and worth the extra checks.
  createRoot(container).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
