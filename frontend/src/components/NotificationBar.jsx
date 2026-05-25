/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/NotificationBar.jsx
 * Purpose:  Notification overlay bar. Displays active notifications from
 *           Home Assistant, River Song, and system events. Supports
 *           priority-based styling, tap-to-dismiss, and auto-fade.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback } from 'react';
import { useApp } from '../App';

/** Priority → accent color mapping */
const PRIORITY_COLORS = {
  1: '#444466',   // LOW — subtle
  2: '#3a5a8a',   // NORMAL — blue
  3: '#7a5a00',   // HIGH — amber
  4: '#8a2020',   // URGENT — red
};

const PRIORITY_LABELS = {
  1: 'LOW',
  2: '',
  3: 'HIGH',
  4: 'URGENT',
};

/**
 * Single notification card.
 *
 * @param {object} props
 * @param {object} props.notification - Notification data object.
 * @param {function} props.onDismiss  - Called with notification id on dismiss.
 */
function NotificationCard({ notification, onDismiss }) {
  const { id, title, message, priority = 2, source = 'system', icon } = notification;
  const accentColor = PRIORITY_COLORS[priority] || PRIORITY_COLORS[2];
  const priorityLabel = PRIORITY_LABELS[priority];

  return (
    <div
      style={{ ...styles.card, borderLeftColor: accentColor }}
      onClick={() => onDismiss(id)}
      role="button"
      aria-label={`Dismiss notification: ${title}`}
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onDismiss(id)}
    >
      <div style={styles.cardHeader}>
        {icon && <span style={styles.cardIcon}>{icon}</span>}
        <span style={styles.cardTitle}>{title}</span>
        {priorityLabel && (
          <span style={{ ...styles.priorityBadge, background: accentColor }}>
            {priorityLabel}
          </span>
        )}
        <span style={styles.dismissHint}>✕</span>
      </div>
      {message && <div style={styles.cardMessage}>{message}</div>}
      <div style={styles.cardSource}>{source}</div>
    </div>
  );
}

/**
 * NotificationBar — renders the active notification stack.
 *
 * Positioned at the top of the screen. Tap any notification to dismiss it.
 * Empty when there are no active notifications.
 */
export default function NotificationBar() {
  const { state, dispatch } = useApp();
  const notifications = state.notifications || [];

  const handleDismiss = useCallback((id) => {
    // Optimistic local dismiss
    dispatch({
      type: 'SET_NOTIFICATIONS',
      payload: notifications.filter((n) => n.id !== id),
    });

    // Notify backend
    fetch(`/api/notifications/${id}/dismiss`, { method: 'POST' }).catch(() => {});
  }, [notifications, dispatch]);

  if (notifications.length === 0) return null;

  return (
    <div style={styles.container} aria-live="polite" aria-label="Notifications">
      {notifications.map((n) => (
        <NotificationCard
          key={n.id}
          notification={n}
          onDismiss={handleDismiss}
        />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  container: {
    position: 'absolute',
    top: 16,
    right: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    zIndex: 50,
    maxWidth: 340,
    width: '90vw',
  },
  card: {
    background: 'rgba(16,16,28,0.92)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderLeft: '3px solid #3a5a8a',
    borderRadius: 10,
    padding: '10px 14px',
    cursor: 'pointer',
    backdropFilter: 'blur(12px)',
    transition: 'opacity 0.2s',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  cardIcon: {
    fontSize: 16,
  },
  cardTitle: {
    flex: 1,
    fontSize: 14,
    fontWeight: 500,
    color: '#d8d8f0',
  },
  priorityBadge: {
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: '0.08em',
    color: '#fff',
    padding: '2px 6px',
    borderRadius: 4,
  },
  dismissHint: {
    fontSize: 11,
    color: '#444466',
    marginLeft: 4,
  },
  cardMessage: {
    fontSize: 13,
    color: '#8888aa',
    lineHeight: 1.4,
    marginBottom: 4,
  },
  cardSource: {
    fontSize: 10,
    color: '#444466',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
};
