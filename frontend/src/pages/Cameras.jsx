/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Cameras.jsx
 * Purpose:  Camera feed viewer page. Displays a grid of camera snapshots
 *           from Home Assistant. Tap a camera to view its live stream.
 *           Snapshots auto-refresh every 10 seconds. Camera access is
 *           gated by the privacy manager.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useApp } from '../App';

const SNAPSHOT_REFRESH_MS = 10_000;

/**
 * CameraCard — single camera tile with snapshot image.
 *
 * @param {object}   props
 * @param {object}   props.camera   - Camera entity info from backend.
 * @param {function} props.onSelect - Called with camera when tapped.
 */
function CameraCard({ camera, onSelect }) {
  const [imgKey, setImgKey] = useState(Date.now());

  // Refresh snapshot periodically
  useEffect(() => {
    const interval = setInterval(() => setImgKey(Date.now()), SNAPSHOT_REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <div
      style={styles.card}
      onClick={() => onSelect(camera)}
      role="button"
      aria-label={`View camera: ${camera.name}`}
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(camera)}
    >
      <div style={styles.imageWrapper}>
        <img
          src={`${camera.snapshot_url}?t=${imgKey}`}
          alt={camera.name}
          style={styles.image}
          onError={(e) => { e.target.style.display = 'none'; }}
        />
        <div style={styles.imageFallback}>📷</div>
      </div>
      <div style={styles.cardFooter}>
        <span style={styles.cameraName}>{camera.name}</span>
        <span style={{
          ...styles.cameraState,
          color: camera.state === 'idle' ? '#44cc88' : '#cc4444',
        }}>
          {camera.state}
        </span>
      </div>
    </div>
  );
}

/**
 * StreamModal — full-screen camera stream overlay.
 *
 * @param {object}   props
 * @param {object}   props.camera  - Camera entity being viewed.
 * @param {function} props.onClose - Called to close the modal.
 */
function StreamModal({ camera, onClose }) {
  return (
    <div
      style={styles.modal}
      onClick={onClose}
      role="dialog"
      aria-label={`Live stream: ${camera.name}`}
      aria-modal="true"
    >
      <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <span style={styles.modalTitle}>{camera.name}</span>
          <button style={styles.closeBtn} onClick={onClose} aria-label="Close stream">
            ✕
          </button>
        </div>
        <img
          src={camera.stream_url}
          alt={`Live: ${camera.name}`}
          style={styles.streamImage}
        />
      </div>
    </div>
  );
}

/**
 * Cameras page — grid of all HA camera feeds.
 */
export default function Cameras() {
  const { navigate, state } = useApp();
  const cameras = state.cameras || [];
  const [selectedCamera, setSelectedCamera] = useState(null);

  const handleSelect = useCallback((camera) => {
    setSelectedCamera(camera);
  }, []);

  const handleClose = useCallback(() => {
    setSelectedCamera(null);
  }, []);

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
        <span style={styles.title}>Cameras</span>
        <span style={styles.count}>{cameras.length} feeds</span>
      </div>

      {/* Camera grid */}
      <div style={styles.content}>
        {cameras.length === 0 ? (
          <div style={styles.empty}>
            <span style={styles.emptyIcon}>📷</span>
            <span style={styles.emptyText}>No cameras available</span>
            <span style={styles.emptyHint}>
              Add camera entities in Home Assistant to see them here.
            </span>
          </div>
        ) : (
          <div style={styles.grid}>
            {cameras.map((camera) => (
              <CameraCard
                key={camera.entity_id}
                camera={camera}
                onSelect={handleSelect}
              />
            ))}
          </div>
        )}
      </div>

      {/* Stream modal */}
      {selectedCamera && (
        <StreamModal camera={selectedCamera} onClose={handleClose} />
      )}
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
  content: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px 20px',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    gap: 14,
  },
  card: {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 12,
    overflow: 'hidden',
    cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  imageWrapper: {
    position: 'relative',
    width: '100%',
    paddingTop: '56.25%', // 16:9
    background: '#111118',
    overflow: 'hidden',
  },
  image: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
  },
  imageFallback: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    fontSize: 32,
    opacity: 0.3,
  },
  cardFooter: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
  },
  cameraName: {
    fontSize: 13,
    color: '#c0c0d8',
    fontWeight: 400,
  },
  cameraState: {
    fontSize: 11,
    textTransform: 'capitalize',
  },
  // Stream modal
  modal: {
    position: 'absolute',
    inset: 0,
    background: 'rgba(0,0,0,0.85)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 200,
    backdropFilter: 'blur(8px)',
  },
  modalContent: {
    width: '90%',
    maxWidth: 800,
    background: '#0d0d1a',
    borderRadius: 16,
    overflow: 'hidden',
    border: '1px solid rgba(255,255,255,0.1)',
  },
  modalHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 16px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
  },
  modalTitle: {
    fontSize: 15,
    color: '#d0d0e8',
    fontWeight: 400,
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: '#7070a0',
    fontSize: 16,
    cursor: 'pointer',
    padding: '4px 8px',
  },
  streamImage: {
    width: '100%',
    display: 'block',
  },
  // Empty state
  empty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 12,
    padding: 60,
    opacity: 0.5,
  },
  emptyIcon: {
    fontSize: 48,
  },
  emptyText: {
    fontSize: 16,
    color: '#8888aa',
  },
  emptyHint: {
    fontSize: 13,
    color: '#555577',
    textAlign: 'center',
    maxWidth: 280,
  },
};
