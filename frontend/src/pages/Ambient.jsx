/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Ambient.jsx
 * Purpose:  Ambient display page — the always-on idle screen. Shows the
 *           large clock, current weather, and notification overlay. Dims
 *           the display and minimizes UI chrome. Tap anywhere to go to
 *           the Dashboard. Designed for 7"/10" touchscreen kiosk use.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback } from 'react';
import Clock from '../components/Clock';
import Weather from '../components/Weather';
import NotificationBar from '../components/NotificationBar';
import PhotoBackdrop from '../components/PhotoBackdrop';
import TimersWidget from '../components/TimersWidget';
import { useApp } from '../App';

/**
 * Ambient page — full-screen clock and weather display.
 *
 * Tapping anywhere on the screen navigates to the Dashboard.
 * The backend also sends a 'navigate' WebSocket event when the
 * wake word is detected, which transitions away from ambient mode.
 */
export default function Ambient() {
  const { navigate } = useApp();

  const handleTap = useCallback(() => {
    navigate('dashboard');
    // Notify backend of user activity
    fetch('/api/display/activity', { method: 'POST' }).catch(() => {});
  }, [navigate]);

  return (
    <div
      style={styles.container}
      onClick={handleTap}
      role="main"
      aria-label="Ambient display — tap to open dashboard"
    >
      {/* Photo layer sits behind everything. Renders nothing when the
          unit has no photo library, leaving the gradient below it. */}
      <PhotoBackdrop />

      {/* Notification overlay — top right */}
      <NotificationBar />

      {/* Active timers — top left */}
      <TimersWidget />

      {/* Center content */}
      <div style={styles.center}>
        <Clock showSeconds={false} />
        <div style={styles.divider} />
        <Weather />
      </div>

      {/* Bottom hint */}
      <div style={styles.hint}>Tap to open dashboard</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  container: {
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(160deg, #08080f 0%, #0d0d1a 100%)',
    cursor: 'pointer',
    position: 'relative',
    userSelect: 'none',
  },
  center: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 24,
    padding: '0 32px',
  },
  divider: {
    width: 60,
    height: 1,
    background: 'rgba(255,255,255,0.08)',
  },
  hint: {
    zIndex: 1,
    position: 'absolute',
    bottom: 20,
    fontSize: 12,
    color: 'rgba(255,255,255,0.15)',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
  },
};
