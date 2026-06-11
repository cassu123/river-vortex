/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Routine.jsx
 * Purpose:  Guided routine display — step-by-step walkthroughs such as
 *           cooking mode, workout mode, or a bedtime checklist (see
 *           core/routines.py). River Song drives step changes via voice
 *           ("next step", "go back", "done"); this screen mirrors that
 *           state and also offers touch controls for the same actions,
 *           plus a shortcut to start a kitchen timer for steps that have
 *           a duration.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-11
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback } from 'react';
import NotificationBar from '../components/NotificationBar';
import TimersWidget from '../components/TimersWidget';
import { useApp } from '../App';

const ROUTINE_BASE = '/api/vortex/v1/routine';

/** Format whole seconds as e.g. "9 min" or "1 hr 30 min" or "45 sec". */
function formatStepDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;

  const parts = [];
  if (h > 0) parts.push(`${h} hr`);
  if (m > 0) parts.push(`${m} min`);
  if (h === 0 && (s > 0 || parts.length === 0)) parts.push(`${s} sec`);
  return parts.join(' ');
}

/**
 * Routine page — full-screen guided step display.
 */
export default function Routine() {
  const { state, navigate } = useApp();
  const routine = state.routine || { active: false };

  const goPrevious = useCallback(() => {
    fetch(`${ROUTINE_BASE}/previous`, { method: 'POST' }).catch(() => {});
  }, []);

  const goNext = useCallback(() => {
    fetch(`${ROUTINE_BASE}/next`, { method: 'POST' }).catch(() => {});
  }, []);

  const endRoutine = useCallback(() => {
    fetch(ROUTINE_BASE, { method: 'DELETE' }).catch(() => {});
  }, []);

  const startStepTimer = useCallback(() => {
    const step = routine.step;
    if (!step?.duration_seconds) return;
    fetch('/api/vortex/v1/timers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        duration_seconds: step.duration_seconds,
        label: routine.title || 'Routine',
      }),
    }).catch(() => {});
  }, [routine.step, routine.title]);

  if (!routine.active) {
    return (
      <div style={styles.container}>
        <NotificationBar />
        <TimersWidget />
        <div style={styles.empty}>
          <span style={styles.emptyIcon}>📋</span>
          <span style={styles.emptyText}>No routine in progress</span>
          <button style={styles.primaryBtn} onClick={() => navigate('dashboard')}>
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

  const { title, step, step_index: stepIndex, step_count: stepCount, is_last_step: isLastStep } = routine;

  return (
    <div style={styles.container}>
      <NotificationBar />
      <TimersWidget />

      {/* Header */}
      <div style={styles.header}>
        <span style={styles.title}>{title}</span>
        <button style={styles.endBtn} onClick={endRoutine} aria-label="End routine">
          ✕ End
        </button>
      </div>

      {/* Step progress dots */}
      <div style={styles.progress} aria-label={`Step ${stepIndex + 1} of ${stepCount}`}>
        {Array.from({ length: stepCount }).map((_, i) => (
          <span
            key={i}
            style={{
              ...styles.dot,
              ...(i === stepIndex ? styles.dotActive : {}),
              ...(i < stepIndex ? styles.dotDone : {}),
            }}
          />
        ))}
      </div>

      {/* Step content */}
      <div style={styles.content}>
        <span style={styles.stepLabel}>Step {stepIndex + 1} of {stepCount}</span>
        <p style={styles.instruction}>{step?.instruction}</p>

        {step?.duration_seconds ? (
          <button style={styles.timerBtn} onClick={startStepTimer}>
            ⏱ Start {formatStepDuration(step.duration_seconds)} timer
          </button>
        ) : null}
      </div>

      {/* Navigation */}
      <div style={styles.nav}>
        <button
          style={{ ...styles.navBtn, ...(stepIndex === 0 ? styles.navBtnDisabled : {}) }}
          onClick={goPrevious}
          disabled={stepIndex === 0}
          aria-label="Previous step"
        >
          ◀ Back
        </button>
        <button style={{ ...styles.navBtn, ...styles.navBtnPrimary }} onClick={goNext} aria-label={isLastStep ? 'Finish routine' : 'Next step'}>
          {isLastStep ? 'Done ✓' : 'Next ▶'}
        </button>
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
    background: 'linear-gradient(160deg, #08080f 0%, #0d0d1a 100%)',
    overflow: 'hidden',
    position: 'relative',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '20px 24px 8px',
    flexShrink: 0,
  },
  title: {
    fontSize: 18,
    fontWeight: 400,
    color: '#d8d8f0',
    letterSpacing: '0.02em',
  },
  endBtn: {
    background: 'rgba(255,255,255,0.06)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: 20,
    color: '#cc8888',
    fontSize: 13,
    padding: '6px 14px',
    cursor: 'pointer',
  },
  progress: {
    display: 'flex',
    justifyContent: 'center',
    gap: 8,
    padding: '12px 24px',
    flexShrink: 0,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: 'rgba(255,255,255,0.1)',
    transition: 'background 0.2s',
  },
  dotActive: {
    background: '#4a9eff',
  },
  dotDone: {
    background: 'rgba(74,158,255,0.35)',
  },
  content: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 24,
    padding: '0 32px',
    textAlign: 'center',
  },
  stepLabel: {
    fontSize: 13,
    color: '#7070a0',
    textTransform: 'uppercase',
    letterSpacing: '0.12em',
  },
  instruction: {
    fontSize: 'clamp(24px, 5vw, 44px)',
    fontWeight: 300,
    color: '#f0f0ff',
    lineHeight: 1.4,
    margin: 0,
    maxWidth: 720,
  },
  timerBtn: {
    background: 'rgba(74,158,255,0.12)',
    border: '1px solid rgba(74,158,255,0.35)',
    borderRadius: 24,
    color: '#a0c4ff',
    fontSize: 15,
    padding: '10px 22px',
    cursor: 'pointer',
  },
  nav: {
    display: 'flex',
    gap: 12,
    padding: '20px 24px',
    flexShrink: 0,
  },
  navBtn: {
    flex: 1,
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: 14,
    color: '#c0c0e0',
    fontSize: 16,
    padding: '16px',
    cursor: 'pointer',
  },
  navBtnPrimary: {
    background: 'rgba(74,158,255,0.18)',
    border: '1px solid rgba(74,158,255,0.4)',
    color: '#a0c4ff',
  },
  navBtnDisabled: {
    opacity: 0.3,
    cursor: 'default',
  },
  empty: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    opacity: 0.6,
  },
  emptyIcon: {
    fontSize: 40,
  },
  emptyText: {
    fontSize: 16,
    color: '#8888aa',
  },
  primaryBtn: {
    background: 'rgba(74,158,255,0.18)',
    border: '1px solid rgba(74,158,255,0.4)',
    borderRadius: 20,
    color: '#a0c4ff',
    fontSize: 14,
    padding: '10px 20px',
    cursor: 'pointer',
    marginTop: 8,
  },
};
