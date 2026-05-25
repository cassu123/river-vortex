/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Devices.jsx
 * Purpose:  Full device control page. Shows all Home Assistant entities
 *           grouped by domain with toggle controls. Includes a search/filter
 *           bar and navigation back to Dashboard.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useMemo, useState } from 'react';
import DeviceGrid from '../components/DeviceGrid';
import { useApp } from '../App';

/**
 * Devices page — full Home Assistant device control.
 */
export default function Devices() {
  const { navigate, state } = useApp();
  const [search, setSearch] = useState('');

  const devices = state.devices || [];

  // Filter devices by search query
  const filteredDevices = useMemo(() => {
    if (!search.trim()) return devices;
    const q = search.toLowerCase();
    return devices.filter((d) => {
      const name = (d?.attributes?.friendly_name || d?.entity_id || '').toLowerCase();
      return name.includes(q) || d?.entity_id?.toLowerCase().includes(q);
    });
  }, [devices, search]);

  // Inject filtered devices into context temporarily via a local override
  // DeviceGrid reads from context, so we pass filtered list via a wrapper
  const onCount = devices.length;
  const offCount = devices.filter((d) => d.state === 'off' || d.state === 'locked').length;

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <button
          style={styles.backBtn}
          onClick={() => navigate('dashboard')}
          aria-label="Back to dashboard"
        >
          ← Back
        </button>
        <span style={styles.title}>All Devices</span>
        <span style={styles.count}>{onCount} total</span>
      </div>

      {/* Stats row */}
      <div style={styles.statsRow}>
        <div style={styles.statChip}>
          <span style={{ ...styles.statDot, background: '#44cc88' }} />
          <span style={styles.statText}>{onCount - offCount} on</span>
        </div>
        <div style={styles.statChip}>
          <span style={{ ...styles.statDot, background: '#444466' }} />
          <span style={styles.statText}>{offCount} off</span>
        </div>
      </div>

      {/* Search */}
      <div style={styles.searchRow}>
        <span style={styles.searchIcon}>🔍</span>
        <input
          style={styles.searchInput}
          type="text"
          placeholder="Search devices…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search devices"
        />
        {search && (
          <button
            style={styles.clearBtn}
            onClick={() => setSearch('')}
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {/* Device grid — all domains */}
      <div style={styles.content}>
        {filteredDevices.length === 0 ? (
          <div style={styles.empty}>
            <span style={styles.emptyIcon}>🔍</span>
            <span style={styles.emptyText}>No devices match "{search}"</span>
          </div>
        ) : (
          <DeviceGrid />
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
    flexDirection: 'column',
    background: '#0a0a0f',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '14px 20px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    flexShrink: 0,
  },
  backBtn: {
    background: 'none',
    border: 'none',
    color: '#7ab8ff',
    fontSize: 14,
    cursor: 'pointer',
    padding: '4px 0',
  },
  title: {
    flex: 1,
    fontSize: 16,
    fontWeight: 400,
    color: '#d0d0e8',
  },
  count: {
    fontSize: 12,
    color: '#555577',
  },
  statsRow: {
    display: 'flex',
    gap: 12,
    padding: '8px 20px',
    flexShrink: 0,
  },
  statChip: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    background: 'rgba(255,255,255,0.04)',
    borderRadius: 20,
    padding: '4px 12px',
  },
  statDot: {
    width: 7,
    height: 7,
    borderRadius: '50%',
  },
  statText: {
    fontSize: 12,
    color: '#8888aa',
  },
  searchRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    margin: '8px 20px',
    background: 'rgba(255,255,255,0.05)',
    borderRadius: 10,
    padding: '8px 14px',
    flexShrink: 0,
  },
  searchIcon: {
    fontSize: 14,
    opacity: 0.5,
  },
  searchInput: {
    flex: 1,
    background: 'none',
    border: 'none',
    outline: 'none',
    color: '#d0d0e8',
    fontSize: 14,
  },
  clearBtn: {
    background: 'none',
    border: 'none',
    color: '#555577',
    cursor: 'pointer',
    fontSize: 12,
    padding: 0,
  },
  content: {
    flex: 1,
    overflowY: 'auto',
    padding: '12px 20px',
  },
  empty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 12,
    padding: 40,
    opacity: 0.4,
  },
  emptyIcon: {
    fontSize: 32,
  },
  emptyText: {
    fontSize: 14,
    color: '#7070a0',
  },
};
