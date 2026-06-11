/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/TimersWidget.jsx
 * Purpose:  Floating display of active kitchen timers/alarms (core/timers.py).
 *           Shows a live countdown for each timer, lets the user cancel a
 *           timer by tapping it, and shows a brief "time's up" banner when a
 *           timer elapses. Timer state arrives over the WebSocket hub
 *           (`timers_update` / `timer_done`) — this component only renders it.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-11
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useApp } from '../App';

const TIMER_DONE_BANNER_MS = 8000;

/**
 * Format a whole number of seconds as `H:MM:SS` (or `M:SS` under an hour).
 *
 * @param {number} totalSeconds
 * @returns {string}
 */
function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const ss = s.toString().padStart(2, '0');
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${ss}`;
  }
  return `${m}:${ss}`;
}

/**
 * TimerChip — a single active timer with a live countdown and tap-to-cancel.
 *
 * @param {object} props
 * @param {object} props.timer - Timer dict from the backend
 *                                (id, label, remaining_seconds, ...).
 */
function TimerChip({ timer }) {
  const [remaining, setRemaining] = useState(timer.remaining_seconds);
  const receivedAt = useRef(Date.now());

  // Re-sync the countdown whenever the backend sends a fresh snapshot.
  useEffect(() => {
    setRemaining(timer.remaining_seconds);
    receivedAt.current = Date.now();
  }, [timer.id, timer.remaining_seconds]);

  // Tick the displayed countdown every second between snapshots.
  useEffect(() => {
    const interval = setInterval(() => {
      const elapsed = (Date.now() - receivedAt.current) / 1000;
      setRemaining(Math.max(0, timer.remaining_seconds - elapsed));
    }, 1000);
    return () => clearInterval(interval);
  }, [timer.remaining_seconds]);

  const handleCancel = useCallback((e) => {
    e.stopPropagation();
    fetch(`/api/vortex/v1/timers/${timer.id}`, { method: 'DELETE' }).catch(() => {});
  }, [timer.id]);

  return (
    <div
      style={styles.chip}
      onClick={handleCancel}
      role="button"
      aria-label={`Cancel timer: ${timer.label}, ${formatDuration(remaining)} remaining`}
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleCancel(e)}
    >
      <span style={styles.chipIcon}>⏱</span>
      <div style={styles.chipText}>
        <span style={styles.chipLabel}>{timer.label}</span>
        <span style={styles.chipTime}>{formatDuration(remaining)}</span>
      </div>
      <span style={styles.chipDismiss}>✕</span>
    </div>
  );
}

/**
 * TimersWidget — floating stack of active timer chips plus a "time's up" banner.
 *
 * Renders nothing when there are no active timers and no recent completion.
 */
export default function TimersWidget() {
  const { state, dispatch } = useApp();
  const timers = state.timers || [];
  const lastTimerDone = state.lastTimerDone;

  // Auto-dismiss the "time's up" banner after a few seconds.
  useEffect(() => {
    if (!lastTimerDone) return undefined;
    const timeout = setTimeout(() => dispatch({ type: 'CLEAR_TIMER_DONE' }), TIMER_DONE_BANNER_MS);
    return () => clearTimeout(timeout);
  }, [lastTimerDone, dispatch]);

  if (timers.length === 0 && !lastTimerDone) return null;

  return (
    <div style={styles.container} aria-live="polite" aria-label="Active timers">
      {lastTimerDone && (
        <div style={styles.doneBanner}>
          <span style={styles.doneIcon}>⏰</span>
          <span style={styles.doneText}>{lastTimerDone.label} is done!</span>
        </div>
      )}
      {timers.map((timer) => (
        <TimerChip key={timer.id} timer={timer} />
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
    maxWidth: 220,
  },
  chip: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    background: 'rgba(16,16,28,0.92)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderLeft: '3px solid #4a9eff',
    borderRadius: 10,
    padding: '8px 12px',
    cursor: 'pointer',
    backdropFilter: 'blur(12px)',
  },
  chipIcon: {
    fontSize: 16,
  },
  chipText: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
  },
  chipLabel: {
    fontSize: 12,
    color: '#c0c0e0',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  chipTime: {
    fontSize: 16,
    fontWeight: 300,
    color: '#f0f0ff',
    fontVariantNumeric: 'tabular-nums',
  },
  chipDismiss: {
    fontSize: 11,
    color: '#444466',
  },
  doneBanner: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: 'rgba(138,32,32,0.85)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: 10,
    padding: '8px 12px',
    backdropFilter: 'blur(12px)',
  },
  doneIcon: {
    fontSize: 16,
  },
  doneText: {
    fontSize: 13,
    color: '#fff0f0',
    fontWeight: 500,
  },
};
