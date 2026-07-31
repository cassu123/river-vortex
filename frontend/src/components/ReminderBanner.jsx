/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/ReminderBanner.jsx
 * Purpose:  Upcoming-reminder overlay. River Song owns reminder data and
 *           pushes the latest snapshot via POST /api/vortex/v1/reminders
 *           (core/lists.py, core/lists_api.py); this component shows any
 *           reminder due within the next REMINDER_LOOKAHEAD_MINUTES as a
 *           small card, similar in style to NotificationBar. Renders
 *           nothing when no reminder is due soon.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-12
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../App';

const REMINDER_LOOKAHEAD_MINUTES = 60;
const RECHECK_INTERVAL_MS = 30000;

/** Format a due Date as e.g. "in 12 min" or "now". */
function formatDueIn(due, now) {
  const minutes = Math.round((due.getTime() - now.getTime()) / 60000);
  if (minutes <= 0) return 'now';
  if (minutes === 1) return 'in 1 min';
  return `in ${minutes} min`;
}

/**
 * ReminderBanner — shows upcoming reminders due within the look-ahead window.
 *
 * Positioned at the top-left of the screen (NotificationBar occupies the
 * top-right). Empty when there are no reminders due soon.
 */
export default function ReminderBanner() {
  const { state } = useApp();
  const reminders = state.reminders || [];
  const [now, setNow] = useState(() => new Date());

  // Recheck periodically so reminders enter/leave the look-ahead window
  // without requiring a fresh `reminders_update` push.
  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), RECHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const upcoming = reminders
    .map((r) => ({ ...r, dueDate: r.due ? new Date(r.due) : null }))
    .filter((r) => r.dueDate && !Number.isNaN(r.dueDate.getTime()))
    .filter((r) => {
      const minutesUntilDue = (r.dueDate.getTime() - now.getTime()) / 60000;
      return minutesUntilDue <= REMINDER_LOOKAHEAD_MINUTES;
    })
    .sort((a, b) => a.dueDate - b.dueDate);

  if (upcoming.length === 0) return null;

  return (
    <div style={styles.container} aria-live="polite" aria-label="Upcoming reminders">
      {upcoming.map((r) => (
        <div key={r.id} style={styles.card}>
          <span style={styles.icon}>🔔</span>
          <div style={styles.text}>
            <span style={styles.message}>{r.text}</span>
            <span style={styles.due}>{formatDueIn(r.dueDate, now)}</span>
          </div>
        </div>
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
    left: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    zIndex: 50,
    maxWidth: 340,
    width: '90vw',
  },
  card: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    background: 'rgba(16,16,28,0.92)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderLeft: '3px solid #4a9eff',
    borderRadius: 10,
    padding: '10px 14px',
    backdropFilter: 'blur(12px)',
  },
  icon: {
    fontSize: 16,
  },
  text: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  message: {
    fontSize: 14,
    fontWeight: 500,
    color: '#d8d8f0',
  },
  due: {
    fontSize: 11,
    color: '#7ab8ff',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
};
