/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/main.jsx
 * Purpose:  Application entry point. Mounts the root <App /> component into
 *           the #root DOM node defined in index.html.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
