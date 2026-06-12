/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/AnnouncementBanner.jsx
 * Purpose:  Global overlay for "Drop In" / broadcast announcements
 *           (core/announce_api.py, core/announce.py) — phone → house,
 *           house → phone, and room → room messages. Shows the message and
 *           its source for a few seconds, then auto-dismisses. Announcement
 *           data arrives over the WebSocket hub (`announcement`) — this
 *           component only renders it.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-12
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useEffect } from 'react';
import { useApp } from '../App';

const ANNOUNCEMENT_BANNER_MS = 8000;

/**
 * AnnouncementBanner — bottom-center transient banner for incoming announcements.
 *
 * Renders nothing when there is no recent announcement.
 */
export default function AnnouncementBanner() {
  const { state, dispatch } = useApp();
  const announcement = state.announcement;

  // Auto-dismiss the banner after a few seconds.
  useEffect(() => {
    if (!announcement) return undefined;
    const timeout = setTimeout(() => dispatch({ type: 'CLEAR_ANNOUNCEMENT' }), ANNOUNCEMENT_BANNER_MS);
    return () => clearTimeout(timeout);
  }, [announcement, dispatch]);

  if (!announcement) return null;

  return (
    <div style={styles.banner} role="status" aria-live="polite">
      <span style={styles.icon}>📢</span>
      <div style={styles.text}>
        {announcement.source && <span style={styles.source}>{announcement.source}</span>}
        <span style={styles.message}>{announcement.message}</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  banner: {
    position: 'absolute',
    bottom: 90,
    left: '50%',
    transform: 'translateX(-50%)',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    maxWidth: '80vw',
    background: 'rgba(16,16,28,0.94)',
    border: '1px solid rgba(255,200,80,0.35)',
    borderRadius: 16,
    padding: '12px 20px',
    backdropFilter: 'blur(12px)',
    zIndex: 90,
  },
  icon: {
    fontSize: 20,
  },
  text: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  source: {
    fontSize: 11,
    color: '#ffcf80',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
  },
  message: {
    fontSize: 15,
    color: '#f0f0ff',
  },
};
