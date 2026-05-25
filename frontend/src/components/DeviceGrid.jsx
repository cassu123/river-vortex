/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/DeviceGrid.jsx
 * Purpose:  Responsive grid of Home Assistant device tiles. Renders lights,
 *           switches, climate, and locks with current state. Supports
 *           tap-to-toggle for lights and switches. Groups devices by domain.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback, useState } from 'react';
import { useApp } from '../App';

// ─────────────────────────────────────────────────────────────────────────────
// Domain config — icon, label, toggleable
// ─────────────────────────────────────────────────────────────────────────────

const DOMAIN_CONFIG = {
  light:        { icon: '💡', label: 'Lights',      toggleable: true  },
  switch:       { icon: '🔌', label: 'Switches',    toggleable: true  },
  climate:      { icon: '🌡️', label: 'Climate',     toggleable: false },
  lock:         { icon: '🔒', label: 'Locks',       toggleable: false },
  cover:        { icon: '🪟', label: 'Covers',      toggleable: false },
  media_player: { icon: '🎵', label: 'Media',       toggleable: false },
  binary_sensor:{ icon: '📡', label: 'Sensors',     toggleable: false },
};

function getDomain(entityId = '') {
  return entityId.split('.')[0] || 'unknown';
}

function getFriendlyName(entity) {
  return entity?.attributes?.friendly_name || entity?.entity_id || 'Unknown';
}

function isOn(entity) {
  return entity?.state === 'on' || entity?.state === 'unlocked' || entity?.state === 'open';
}

// ─────────────────────────────────────────────────────────────────────────────
// Single device tile
// ─────────────────────────────────────────────────────────────────────────────

/**
 * DeviceTile — renders one HA entity as a touchable card.
 *
 * @param {object} props
 * @param {object}   props.entity     - HA entity state object.
 * @param {function} props.onToggle   - Called with entity_id on tap.
 * @param {boolean}  props.loading    - Show loading state.
 */
function DeviceTile({ entity, onToggle, loading }) {
  const domain = getDomain(entity.entity_id);
  const config = DOMAIN_CONFIG[domain] || { icon: '⚙️', toggleable: false };
  const active = isOn(entity);
  const name = getFriendlyName(entity);

  // Climate extra info
  const temp = entity?.attributes?.current_temperature;
  const target = entity?.attributes?.temperature;

  return (
    <div
      style={{
        ...styles.tile,
        ...(active ? styles.tileActive : styles.tileInactive),
        ...(loading ? styles.tileLoading : {}),
      }}
      onClick={() => config.toggleable && !loading && onToggle(entity.entity_id)}
      role={config.toggleable ? 'button' : 'status'}
      aria-label={`${name}: ${entity.state}`}
      aria-pressed={config.toggleable ? active : undefined}
      tabIndex={config.toggleable ? 0 : -1}
      onKeyDown={(e) => e.key === 'Enter' && config.toggleable && onToggle(entity.entity_id)}
    >
      <span style={styles.tileIcon}>{config.icon}</span>
      <span style={styles.tileName}>{name}</span>
      <span style={{ ...styles.tileState, color: active ? '#7ab8ff' : '#555577' }}>
        {domain === 'climate' && temp !== undefined
          ? `${Math.round(temp)}° → ${Math.round(target)}°`
          : entity.state}
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DeviceGrid
// ─────────────────────────────────────────────────────────────────────────────

/**
 * DeviceGrid — renders all HA devices grouped by domain.
 *
 * @param {object}   props
 * @param {string[]} [props.domains] - Filter to specific domains. Shows all if omitted.
 */
export default function DeviceGrid({ domains }) {
  const { state, dispatch } = useApp();
  const [loadingIds, setLoadingIds] = useState(new Set());

  const allDevices = state.devices || [];

  // Filter and group by domain
  const filtered = domains
    ? allDevices.filter((e) => domains.includes(getDomain(e.entity_id)))
    : allDevices;

  const grouped = filtered.reduce((acc, entity) => {
    const domain = getDomain(entity.entity_id);
    if (!acc[domain]) acc[domain] = [];
    acc[domain].push(entity);
    return acc;
  }, {});

  const handleToggle = useCallback(async (entityId) => {
    setLoadingIds((prev) => new Set(prev).add(entityId));

    try {
      const response = await fetch('/api/devices/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_id: entityId }),
      });

      if (response.ok) {
        // Optimistic update — flip the state locally
        dispatch({
          type: 'UPDATE_DEVICES',
          payload: state.devices.map((e) =>
            e.entity_id === entityId
              ? { ...e, state: e.state === 'on' ? 'off' : 'on' }
              : e
          ),
        });
      }
    } catch (err) {
      console.error('Toggle failed:', err);
    } finally {
      setLoadingIds((prev) => {
        const next = new Set(prev);
        next.delete(entityId);
        return next;
      });
    }
  }, [state.devices, dispatch]);

  if (filtered.length === 0) {
    return (
      <div style={styles.empty}>
        <span style={styles.emptyIcon}>🏠</span>
        <span style={styles.emptyText}>No devices available</span>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {Object.entries(grouped).map(([domain, entities]) => {
        const config = DOMAIN_CONFIG[domain] || { label: domain, icon: '⚙️' };
        return (
          <div key={domain} style={styles.group}>
            <div style={styles.groupHeader}>
              <span style={styles.groupIcon}>{config.icon}</span>
              <span style={styles.groupLabel}>{config.label}</span>
              <span style={styles.groupCount}>{entities.length}</span>
            </div>
            <div style={styles.grid}>
              {entities.map((entity) => (
                <DeviceTile
                  key={entity.entity_id}
                  entity={entity}
                  onToggle={handleToggle}
                  loading={loadingIds.has(entity.entity_id)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 24,
  },
  group: {
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  groupHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    paddingBottom: 4,
    borderBottom: '1px solid rgba(255,255,255,0.06)',
  },
  groupIcon: {
    fontSize: 16,
  },
  groupLabel: {
    flex: 1,
    fontSize: 13,
    fontWeight: 500,
    color: '#8888aa',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
  },
  groupCount: {
    fontSize: 12,
    color: '#444466',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    gap: 10,
  },
  tile: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    padding: '14px 12px',
    borderRadius: 12,
    border: '1px solid rgba(255,255,255,0.06)',
    cursor: 'pointer',
    transition: 'background 0.15s, border-color 0.15s',
    minHeight: 80,
  },
  tileActive: {
    background: 'rgba(74,158,255,0.12)',
    borderColor: 'rgba(74,158,255,0.25)',
  },
  tileInactive: {
    background: 'rgba(255,255,255,0.03)',
    borderColor: 'rgba(255,255,255,0.06)',
  },
  tileLoading: {
    opacity: 0.5,
    cursor: 'wait',
  },
  tileIcon: {
    fontSize: 22,
  },
  tileName: {
    fontSize: 13,
    fontWeight: 400,
    color: '#c0c0d8',
    lineHeight: 1.3,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  tileState: {
    fontSize: 11,
    textTransform: 'capitalize',
    letterSpacing: '0.04em',
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
    fontSize: 36,
  },
  emptyText: {
    fontSize: 14,
    color: '#7070a0',
  },
};
