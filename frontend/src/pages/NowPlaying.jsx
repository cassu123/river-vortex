/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/NowPlaying.jsx
 * Purpose:  Full-screen now-playing view — artwork, track, and transport
 *           controls sized for a wall panel you tap in passing.
 *
 *           Controls POST to the same /api/vortex/v1/media endpoints River
 *           Song uses for voice, so a tap and "River, skip this" go through
 *           one player and one state.
 * ============================================================================
 */

import React, { useCallback } from 'react';
import { useApp } from '../App';

const MEDIA_BASE = '/api/vortex/v1/media';

/** Fire-and-forget control call. State comes back over the WebSocket. */
function control(path, options = {}) {
  fetch(`${MEDIA_BASE}${path}`, { method: 'POST', ...options }).catch(() => {});
}

/**
 * Format seconds as m:ss.
 *
 * @param {number} total
 * @returns {string}
 */
function formatTime(total) {
  const seconds = Math.max(0, Math.floor(total || 0));
  const mins = Math.floor(seconds / 60);
  return `${mins}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * Now-playing screen.
 */
export default function NowPlaying() {
  const { state, navigate } = useApp();
  const media = state.media || {};
  const track = media.now_playing || {};
  const playing = media.state === 'playing';

  const onToggle = useCallback(() => control('/toggle'), []);
  const onNext = useCallback(() => control('/next'), []);
  const onPrevious = useCallback(() => control('/previous'), []);
  const onStop = useCallback(() => {
    fetch(MEDIA_BASE, { method: 'DELETE' }).catch(() => {});
    navigate('dashboard');
  }, [navigate]);

  // Nothing playing — say so plainly rather than showing dead controls.
  if (!media.state || media.state === 'idle') {
    return (
      <div style={styles.container}>
        <div style={styles.empty}>
          <span style={styles.emptyIcon}>♪</span>
          <span style={styles.emptyText}>
            {media.available === false
              ? 'Media playback is not available on this unit'
              : 'Nothing playing'}
          </span>
          <button style={styles.secondaryBtn} onClick={() => navigate('dashboard')}>
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

  const duration = track.duration_seconds || 0;
  const elapsed = media.elapsed_seconds || 0;
  const progress = duration > 0 ? Math.min(100, (elapsed / duration) * 100) : 0;

  return (
    <div style={styles.container}>
      <button style={styles.closeBtn} onClick={onStop} aria-label="Stop and close">
        ✕
      </button>

      <div style={styles.content}>
        {/* Artwork, or a placeholder disc when the track has none */}
        <div style={styles.artWrap}>
          {track.artwork_url ? (
            <img src={track.artwork_url} alt="" style={styles.art} />
          ) : (
            <div style={styles.artPlaceholder}>♪</div>
          )}
        </div>

        <div style={styles.meta}>
          <div style={styles.title}>{track.title || 'Unknown track'}</div>
          <div style={styles.artist}>{track.artist || ''}</div>
          {track.album ? <div style={styles.album}>{track.album}</div> : null}

          {duration > 0 ? (
            <div style={styles.progressRow}>
              <span style={styles.time}>{formatTime(elapsed)}</span>
              <div style={styles.progressTrack}>
                <div style={{ ...styles.progressFill, width: `${progress}%` }} />
              </div>
              <span style={styles.time}>{formatTime(duration)}</span>
            </div>
          ) : (
            <div style={styles.live}>Live</div>
          )}

          <div style={styles.controls}>
            <button
              style={{ ...styles.ctrlBtn, ...(media.has_previous ? {} : styles.ctrlDisabled) }}
              onClick={onPrevious}
              disabled={!media.has_previous}
              aria-label="Previous track"
            >
              ⏮
            </button>
            <button
              style={{ ...styles.ctrlBtn, ...styles.ctrlPrimary }}
              onClick={onToggle}
              aria-label={playing ? 'Pause' : 'Play'}
            >
              {playing ? '⏸' : '▶'}
            </button>
            <button
              style={{ ...styles.ctrlBtn, ...(media.has_next ? {} : styles.ctrlDisabled) }}
              onClick={onNext}
              disabled={!media.has_next}
              aria-label="Next track"
            >
              ⏭
            </button>
          </div>

          {media.ducked ? (
            <div style={styles.duckedNote}>Lowered — River is speaking</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: {
    width: '100%',
    height: '100%',
    background: 'linear-gradient(160deg, #0a0a12 0%, #12101c 100%)',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  closeBtn: {
    position: 'absolute',
    top: 16,
    right: 20,
    background: 'none',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: 10,
    color: '#8888aa',
    fontSize: 16,
    padding: '6px 12px',
    cursor: 'pointer',
    zIndex: 2,
  },
  content: {
    display: 'flex',
    alignItems: 'center',
    gap: 'clamp(20px, 4vw, 48px)',
    padding: '0 clamp(20px, 5vw, 64px)',
    width: '100%',
    maxWidth: 1100,
  },
  artWrap: {
    flexShrink: 0,
    width: 'clamp(120px, 26vw, 300px)',
    height: 'clamp(120px, 26vw, 300px)',
    borderRadius: 18,
    overflow: 'hidden',
    boxShadow: '0 18px 50px rgba(0,0,0,0.55)',
  },
  art: {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    display: 'block',
  },
  artPlaceholder: {
    width: '100%',
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(140deg, #241d33 0%, #14121f 100%)',
    color: '#5a5a80',
    fontSize: 'clamp(40px, 8vw, 84px)',
  },
  meta: {
    flex: 1,
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  title: {
    fontSize: 'clamp(22px, 3.6vw, 42px)',
    fontWeight: 400,
    color: '#f0f0f8',
    lineHeight: 1.15,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  artist: {
    fontSize: 'clamp(15px, 2vw, 22px)',
    color: '#a0a0c8',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  album: {
    fontSize: 'clamp(12px, 1.4vw, 15px)',
    color: '#606080',
  },
  progressRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginTop: 10,
  },
  progressTrack: {
    flex: 1,
    height: 4,
    borderRadius: 2,
    background: 'rgba(255,255,255,0.10)',
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: '#7ab8ff',
    transition: 'width 1s linear',
  },
  time: {
    fontSize: 12,
    color: '#606080',
    fontVariantNumeric: 'tabular-nums',
  },
  live: {
    marginTop: 10,
    fontSize: 12,
    color: '#cc7755',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
  },
  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: 'clamp(10px, 2vw, 22px)',
    marginTop: 14,
  },
  ctrlBtn: {
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.10)',
    borderRadius: 999,
    color: '#d0d0e8',
    // Large targets: this gets tapped with a wet or floury hand.
    fontSize: 'clamp(18px, 2.4vw, 26px)',
    width: 'clamp(52px, 7vw, 72px)',
    height: 'clamp(52px, 7vw, 72px)',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  ctrlPrimary: {
    background: 'rgba(74,158,255,0.16)',
    borderColor: 'rgba(74,158,255,0.35)',
    color: '#9fcaff',
  },
  ctrlDisabled: {
    opacity: 0.3,
    cursor: 'default',
  },
  duckedNote: {
    marginTop: 10,
    fontSize: 12,
    color: '#c9a86a',
    letterSpacing: '0.04em',
  },
  empty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 16,
  },
  emptyIcon: {
    fontSize: 48,
    color: '#3a3a55',
  },
  emptyText: {
    fontSize: 16,
    color: '#606080',
  },
  secondaryBtn: {
    marginTop: 8,
    background: 'none',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: 10,
    color: '#8888aa',
    fontSize: 14,
    padding: '10px 20px',
    cursor: 'pointer',
  },
};
