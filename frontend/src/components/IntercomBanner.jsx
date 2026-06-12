/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/IntercomBanner.jsx
 * Purpose:  Global overlay for room-to-room "Drop In" intercom calls
 *           (core/intercom_api.py, intercom/intercom_manager.py). Shows an
 *           incoming-call banner with Answer/Decline actions, an outgoing
 *           "Calling..." banner with Cancel, and an active-call banner with
 *           Hang Up. Intercom state arrives over the WebSocket hub
 *           (`intercom_update`) — this component only renders it and posts
 *           touch actions back to the REST API.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-12
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback } from 'react';
import { useApp } from '../App';

const INTERCOM_BASE = '/api/vortex/v1/intercom';

const STATE_CONFIG = {
  ringing: {
    icon: '📞',
    label: (peer) => `Incoming call from ${peer?.location || peer?.unit_name || 'another room'}`,
  },
  calling: {
    icon: '📞',
    label: (peer) => `Calling ${peer?.location || peer?.unit_name || '...'}`,
  },
  active: {
    icon: '🔊',
    label: (peer) => `On call with ${peer?.location || peer?.unit_name || 'another room'}`,
  },
};

/**
 * IntercomBanner — top-center overlay reflecting the current intercom call state.
 *
 * Renders nothing while intercom is idle.
 */
export default function IntercomBanner() {
  const { state } = useApp();
  const intercom = state.intercom || { state: 'idle', peer: null };

  const answer = useCallback(() => {
    fetch(`${INTERCOM_BASE}/answer`, { method: 'POST' }).catch(() => {});
  }, []);

  const decline = useCallback(() => {
    fetch(`${INTERCOM_BASE}/decline`, { method: 'POST' }).catch(() => {});
  }, []);

  const hangUp = useCallback(() => {
    fetch(INTERCOM_BASE, { method: 'DELETE' }).catch(() => {});
  }, []);

  const config = STATE_CONFIG[intercom.state];
  if (!config) return null;

  return (
    <div style={styles.banner} role="status" aria-live="assertive">
      <span style={styles.icon}>{config.icon}</span>
      <span style={styles.label}>{config.label(intercom.peer)}</span>
      <div style={styles.actions}>
        {intercom.state === 'ringing' && (
          <>
            <button style={styles.btnAccept} onClick={answer}>Answer</button>
            <button style={styles.btnDecline} onClick={decline}>Decline</button>
          </>
        )}
        {intercom.state === 'calling' && (
          <button style={styles.btnDecline} onClick={hangUp}>Cancel</button>
        )}
        {intercom.state === 'active' && (
          <button style={styles.btnDecline} onClick={hangUp}>Hang Up</button>
        )}
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
    top: 16,
    left: '50%',
    transform: 'translateX(-50%)',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    background: 'rgba(16,16,28,0.94)',
    border: '1px solid rgba(74,158,255,0.35)',
    borderRadius: 16,
    padding: '10px 18px',
    backdropFilter: 'blur(12px)',
    zIndex: 80,
  },
  icon: {
    fontSize: 18,
  },
  label: {
    fontSize: 14,
    color: '#d8d8f0',
    fontWeight: 500,
  },
  actions: {
    display: 'flex',
    gap: 8,
    marginLeft: 8,
  },
  btnAccept: {
    background: 'rgba(70,200,130,0.18)',
    border: '1px solid rgba(70,200,130,0.4)',
    borderRadius: 20,
    color: '#9ce8bd',
    fontSize: 13,
    padding: '6px 16px',
    cursor: 'pointer',
  },
  btnDecline: {
    background: 'rgba(220,80,80,0.15)',
    border: '1px solid rgba(220,80,80,0.4)',
    borderRadius: 20,
    color: '#f0a0a0',
    fontSize: 13,
    padding: '6px 16px',
    cursor: 'pointer',
  },
};
