/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Setup.jsx
 * Purpose:  First-run pairing screen, shown when this unit has not yet been
 *           paired with River Song. Displays the unit's identity and a
 *           one-time pairing PIN — the user opens the River Song app on
 *           their phone/computer (same WiFi network), finds this device,
 *           and enters the PIN to complete setup. Once paired, the backend
 *           restarts and this screen automatically gives way to Ambient.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-11
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../App';

const SETUP_INFO_URL = '/api/vortex/v1/setup/info';
const POLL_INTERVAL_MS = 4000;

/**
 * Setup (pairing) page — full-screen pairing PIN display.
 *
 * Polls the unit's own setup API until `configured` becomes true (which
 * happens after the River Song app completes pairing and the backend
 * restarts), then navigates to Ambient.
 */
export default function Setup() {
  const { navigate } = useApp();
  const [info, setInfo] = useState(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      fetch(SETUP_INFO_URL)
        .then((res) => res.json())
        .then((data) => {
          if (cancelled) return;
          setUnreachable(false);
          if (data.configured) {
            navigate('ambient');
            return;
          }
          setInfo(data);
        })
        .catch(() => {
          if (!cancelled) setUnreachable(true);
        });
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [navigate]);

  const pin = info?.pairing_pin || '';

  return (
    <div style={styles.container} role="main" aria-label="Pairing setup">
      <div style={styles.card}>
        <div style={styles.eyebrow}>River Vortex Setup</div>
        <h1 style={styles.title}>{info?.unit_name || 'New Vortex Unit'}</h1>
        <p style={styles.subtitle}>
          Open the River Song app and add a new device. Make sure your phone
          or computer is on the same WiFi network as this unit.
        </p>

        <div style={styles.pinLabel}>Pairing Code</div>
        <div style={styles.pin}>
          {pin ? pin.split('').join(' ') : '— — — — — —'}
        </div>

        <div style={styles.details}>
          <div style={styles.detailRow}>
            <span style={styles.detailLabel}>Unit ID</span>
            <span style={styles.detailValue}>{info?.unit_id || '—'}</span>
          </div>
          <div style={styles.detailRow}>
            <span style={styles.detailLabel}>Location</span>
            <span style={styles.detailValue}>{info?.location || '—'}</span>
          </div>
        </div>

        {unreachable && (
          <div style={styles.notice}>Connecting to this unit…</div>
        )}
      </div>
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
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(160deg, #08080f 0%, #0d0d1a 100%)',
    userSelect: 'none',
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 16,
    padding: '40px 56px',
    maxWidth: 560,
    textAlign: 'center',
    border: '1px solid rgba(100,160,255,0.18)',
    borderRadius: 24,
    background: 'rgba(20,20,35,0.6)',
    backdropFilter: 'blur(12px)',
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: 500,
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: '#4a9eff',
  },
  title: {
    margin: 0,
    fontSize: 'clamp(28px, 5vw, 40px)',
    fontWeight: 300,
    color: '#f0f0ff',
  },
  subtitle: {
    margin: 0,
    fontSize: 15,
    fontWeight: 300,
    lineHeight: 1.6,
    color: '#a0a0c0',
  },
  pinLabel: {
    marginTop: 12,
    fontSize: 12,
    letterSpacing: '0.1em',
    textTransform: 'uppercase',
    color: '#7070a0',
  },
  pin: {
    fontSize: 'clamp(40px, 9vw, 64px)',
    fontWeight: 200,
    letterSpacing: '0.18em',
    color: '#f0f0ff',
    fontVariantNumeric: 'tabular-nums',
  },
  details: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    marginTop: 16,
    width: '100%',
  },
  detailRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 13,
    color: '#7070a0',
  },
  detailLabel: {
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
  detailValue: {
    color: '#a0c4ff',
    fontVariantNumeric: 'tabular-nums',
  },
  notice: {
    marginTop: 8,
    fontSize: 12,
    color: '#555577',
  },
};
