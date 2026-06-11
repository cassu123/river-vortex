/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Dashboard.jsx
 * Purpose:  Main dashboard page. Shows compact clock/weather header, quick
 *           device status summary, and navigation to Devices and Cameras
 *           pages. The primary interactive screen after wake-from-ambient.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React from 'react';
import Clock from '../components/Clock';
import Weather from '../components/Weather';
import NotificationBar from '../components/NotificationBar';
import TimersWidget from '../components/TimersWidget';
import DeviceGrid from '../components/DeviceGrid';
import { useApp } from '../App';

/**
 * NavButton — bottom navigation tab.
 *
 * @param {object}   props
 * @param {string}   props.icon    - Emoji icon.
 * @param {string}   props.label   - Tab label.
 * @param {string}   props.page    - Target page key.
 * @param {boolean}  props.active  - Whether this tab is currently active.
 * @param {function} props.onClick - Navigation callback.
 */
function NavButton({ icon, label, page, active, onClick }) {
  return (
    <button
      style={{ ...styles.navBtn, ...(active ? styles.navBtnActive : {}) }}
      onClick={() => onClick(page)}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
    >
      <span style={styles.navIcon}>{icon}</span>
      <span style={styles.navLabel}>{label}</span>
    </button>
  );
}

/**
 * Dashboard page — main hub screen.
 */
export default function Dashboard() {
  const { state, navigate } = useApp();
  const { page, devices = [], wsConnected } = state;

  // Quick stats
  const lightsOn = devices.filter(
    (d) => d.entity_id?.startsWith('light.') && d.state === 'on'
  ).length;
  const totalLights = devices.filter((d) => d.entity_id?.startsWith('light.')).length;

  return (
    <div style={styles.container}>
      {/* Notifications */}
      <NotificationBar />

      {/* Active timers */}
      <TimersWidget />

      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <Clock compact />
          <div style={styles.headerDivider} />
          <Weather compact />
        </div>
        <div style={styles.headerRight}>
          {/* Connectivity indicator */}
          <div style={styles.connDot} title={wsConnected ? 'Connected' : 'Disconnected'}>
            <span style={{
              ...styles.connDotInner,
              background: wsConnected ? '#44cc88' : '#cc4444',
            }} />
          </div>
          {/* Ambient mode button */}
          <button
            style={styles.ambientBtn}
            onClick={() => navigate('ambient')}
            aria-label="Return to ambient mode"
          >
            🌙
          </button>
        </div>
      </div>

      {/* Quick stats bar */}
      <div style={styles.statsBar}>
        <div style={styles.stat}>
          <span style={styles.statValue}>{lightsOn}</span>
          <span style={styles.statLabel}>of {totalLights} lights on</span>
        </div>
        <div style={styles.stat}>
          <span style={styles.statValue}>{devices.length}</span>
          <span style={styles.statLabel}>devices</span>
        </div>
      </div>

      {/* Device grid — lights and switches on dashboard */}
      <div style={styles.content}>
        <DeviceGrid domains={['light', 'switch', 'climate', 'lock']} />
      </div>

      {/* Bottom navigation */}
      <nav style={styles.nav} aria-label="Main navigation">
        <NavButton icon="🏠" label="Dashboard" page="dashboard" active={page === 'dashboard'} onClick={navigate} />
        <NavButton icon="💡" label="Devices"   page="devices"   active={page === 'devices'}   onClick={navigate} />
        <NavButton icon="📷" label="Cameras"   page="cameras"   active={page === 'cameras'}   onClick={navigate} />
      </nav>
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
    background: '#0a0a0f',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 20px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    flexShrink: 0,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
  },
  headerDivider: {
    width: 1,
    height: 24,
    background: 'rgba(255,255,255,0.1)',
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  connDot: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 20,
    height: 20,
  },
  connDotInner: {
    width: 8,
    height: 8,
    borderRadius: '50%',
  },
  ambientBtn: {
    background: 'none',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: 8,
    color: '#8888aa',
    fontSize: 16,
    padding: '4px 10px',
    cursor: 'pointer',
  },
  statsBar: {
    display: 'flex',
    gap: 24,
    padding: '10px 20px',
    borderBottom: '1px solid rgba(255,255,255,0.04)',
    flexShrink: 0,
  },
  stat: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 6,
  },
  statValue: {
    fontSize: 20,
    fontWeight: 300,
    color: '#c0c0e0',
  },
  statLabel: {
    fontSize: 12,
    color: '#555577',
  },
  content: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px 20px',
  },
  nav: {
    display: 'flex',
    borderTop: '1px solid rgba(255,255,255,0.06)',
    flexShrink: 0,
  },
  navBtn: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 4,
    padding: '12px 8px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: '#555577',
    transition: 'color 0.15s',
  },
  navBtnActive: {
    color: '#7ab8ff',
    borderTop: '2px solid #4a9eff',
  },
  navIcon: {
    fontSize: 20,
  },
  navLabel: {
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
};
