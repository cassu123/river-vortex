/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Ambient.jsx
 * Purpose:  Ambient display page — the always-on idle screen. Shows the
 *           large clock, current weather, and notification overlay. Dims
 *           the display and minimizes UI chrome. Tap anywhere to go to
 *           the Dashboard. Designed for 7"/10" touchscreen kiosk use.
 *
 *           It also shows the top SURFACE — the one card River Song has
 *           decided matters right now. When nothing does, the screen falls
 *           back to clock, weather and photos, which is the point: a hub
 *           should be right without being asked, and blank when there is
 *           genuinely nothing to say.
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
import Surface from '../surfaces/Surface';
import { isTakeover, topSurface } from '../surfaces/surfaceContract';
import { useApp } from '../App';

/**
 * Ambient page — full-screen clock and weather display.
 *
 * Tapping anywhere on the screen navigates to the Dashboard.
 * The backend also sends a 'navigate' WebSocket event when the
 * wake word is detected, which transitions away from ambient mode.
 */
export default function Ambient() {
  const { navigate, state, dispatch } = useApp();

  const handleTap = useCallback(() => {
    navigate('dashboard');
    // Notify backend of user activity
    fetch('/api/display/activity', { method: 'POST' }).catch(() => {});
  }, [navigate]);

  const dismissSurface = useCallback((id) => {
    dispatch({ type: 'REMOVE_SURFACE', payload: id });
  }, [dispatch]);

  // The one card River Song has decided matters most right now. Critical
  // surfaces are drawn by App over every page, so they are skipped here —
  // rendering both would put the takeover on screen twice.
  const surface = topSurface(state.surfaces);
  const card = surface && !isTakeover(surface) ? surface : null;

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

      {/* Center content. With a card in play the clock steps aside into a
          column rather than shrinking to nothing — the time is still the
          thing most glances are looking for. */}
      <div style={card ? styles.centerWithCard : styles.center}>
        <div style={styles.clockColumn}>
          <Clock showSeconds={false} />
          <div style={styles.divider} />
          <Weather />
        </div>

        {card && (
          <Surface surface={card} onDismiss={dismissSurface} />
        )}
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
  // Side by side on a wide panel, stacked on a tall one. `wrap` does the
  // switch on its own, so a 7" landscape and a portrait wall mount both work
  // without a media query.
  centerWithCard: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 44,
    padding: '0 40px',
    maxWidth: '100%',
  },
  clockColumn: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 24,
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
