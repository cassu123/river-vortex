/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/App.jsx
 * Purpose:  Root application component. Manages routing between display
 *           modes (Ambient, Dashboard, Devices, Cameras), maintains global
 *           WebSocket connection to the backend, and provides app-wide
 *           context (system state, notifications, connectivity).
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { createContext, useCallback, useContext, useEffect, useReducer, useRef } from 'react';
import Ambient from './pages/Ambient';
import Dashboard from './pages/Dashboard';
import Devices from './pages/Devices';
import Cameras from './pages/Cameras';
import Routine from './pages/Routine';
import Lists from './pages/Lists';
import Setup from './pages/Setup';
import Screensaver from './pages/Screensaver';
import NowPlaying from './pages/NowPlaying';
import Boot from './pages/Boot';
import AnnouncementBanner from './components/AnnouncementBanner';
import IntercomBanner from './components/IntercomBanner';
import ReminderBanner from './components/ReminderBanner';
import Orb from './presence/Orb';
import { IDLE_PRESENCE, makePresence } from './presence/presenceContract';

// ─────────────────────────────────────────────────────────────────────────────
// App Context — shared state accessible to all child components
// ─────────────────────────────────────────────────────────────────────────────

const initialState = {
  /** Current display page: 'loading' | 'setup' | 'ambient' | 'dashboard' | 'devices' | 'cameras' */
  page: 'boot',
  /** WebSocket connection status */
  wsConnected: false,
  /** Latest ambient data from backend */
  ambient: { time: '', date: '', weather: {}, notifications: [] },
  /** All HA device states */
  devices: [],
  /** All HA camera entities */
  cameras: [],
  /** System info (unit name, version, etc.) */
  system: {},
  /** Active notifications */
  notifications: [],
  /** Vortex listening state: idle | listening | processing | responding */
  vortexState: 'idle',
  /** Active kitchen timers/alarms (see core/timers.py) */
  timers: [],
  /** Guided routine session state (cooking mode, etc. — see core/routines.py) */
  routine: { active: false },
  /** Most recently elapsed timer, for a transient "time's up" banner */
  lastTimerDone: null,
  /** Room-to-room "Drop In" intercom state (see core/intercom_api.py) */
  intercom: { state: 'idle', peer: null },
  /** Most recent "Drop In" / broadcast announcement (see core/announce.py) */
  announcement: null,
  /** Shopping/to-do lists snapshot (see core/lists.py) */
  lists: [],
  /** Upcoming reminders snapshot (see core/lists.py) */
  reminders: [],
  /** Media transport state (see audio/media_player.py) */
  media: { state: 'idle', now_playing: {} },
  /** Boot self-test report (see core/diagnostics.py) */
  diagnostics: null,
  /**
   * River's presence — {state, amplitude, mood, caption}. Drives the orb
   * today and the Rive / holographic avatar later. See presenceContract.js.
   * NOTE: the live amplitude does NOT live here; it is carried in a ref so a
   * 30Hz envelope cannot trigger React renders on a Pi 4.
   */
  presence: IDLE_PRESENCE,
};

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_PAGE':
      return { ...state, page: action.payload };
    case 'WS_CONNECTED':
      return { ...state, wsConnected: true };
    case 'WS_DISCONNECTED':
      return { ...state, wsConnected: false };
    case 'UPDATE_AMBIENT':
      return { ...state, ambient: { ...state.ambient, ...action.payload } };
    case 'UPDATE_DEVICES':
      return { ...state, devices: action.payload };
    case 'UPDATE_CAMERAS':
      return { ...state, cameras: action.payload };
    case 'UPDATE_SYSTEM':
      return { ...state, system: action.payload };
    case 'SET_NOTIFICATIONS':
      return { ...state, notifications: action.payload };
    case 'SET_VORTEX_STATE':
      // Keep the legacy field in sync, but derive presence from it too so a
      // backend that only sends vortex_state still drives the orb.
      return {
        ...state,
        vortexState: action.payload,
        presence: makePresence({ ...state.presence, state: action.payload }),
      };
    case 'SET_PRESENCE':
      return { ...state, presence: action.payload };
    case 'SET_TIMERS':
      return { ...state, timers: action.payload };
    case 'SET_ROUTINE':
      return { ...state, routine: action.payload };
    case 'TIMER_DONE':
      return { ...state, lastTimerDone: action.payload };
    case 'CLEAR_TIMER_DONE':
      return { ...state, lastTimerDone: null };
    case 'SET_INTERCOM':
      return { ...state, intercom: action.payload };
    case 'SET_ANNOUNCEMENT':
      return { ...state, announcement: action.payload };
    case 'CLEAR_ANNOUNCEMENT':
      return { ...state, announcement: null };
    case 'SET_LISTS':
      return { ...state, lists: action.payload };
    case 'SET_REMINDERS':
      return { ...state, reminders: action.payload };
    case 'SET_MEDIA':
      return { ...state, media: action.payload };
    case 'SET_DIAGNOSTICS':
      return { ...state, diagnostics: action.payload };
    case 'BOOT_COMPLETE':
      // Only leave the boot screen — never yank the user off a page they
      // navigated to while the self-test was still finishing.
      if (state.page !== 'boot') return state;
      return { ...state, page: state.system.configured === false ? 'setup' : 'ambient' };
    default:
      return state;
  }
}

export const AppContext = createContext(null);

/** Hook for consuming app context in child components */
export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside <App>');
  return ctx;
}

// ─────────────────────────────────────────────────────────────────────────────
// WebSocket hook
// ─────────────────────────────────────────────────────────────────────────────

const WS_URL = `ws://${window.location.host}/api/ws`;
const WS_RECONNECT_DELAY_MS = 3000;

function useBackendSocket(dispatch, amplitudeRef) {
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      dispatch({ type: 'WS_CONNECTED' });
      clearTimeout(reconnectTimer.current);
    };

    ws.onclose = () => {
      dispatch({ type: 'WS_DISCONNECTED' });
      // Losing the backend means River is unreachable — show it on the orb
      // rather than leaving a stale 'listening' state on screen forever.
      dispatch({ type: 'SET_PRESENCE', payload: makePresence({ state: 'error' }) });
      if (amplitudeRef) amplitudeRef.current = 0;
      reconnectTimer.current = setTimeout(connect, WS_RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg, dispatch, amplitudeRef);
      } catch {
        // Ignore malformed messages
      }
    };
  }, [dispatch, amplitudeRef]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return wsRef;
}

function handleMessage(msg, dispatch, amplitudeRef) {
  switch (msg.type) {
    // High-frequency TTS envelope (~30Hz). Written straight to the ref —
    // deliberately NOT dispatched, so it never enters React's render cycle.
    case 'amplitude':
      if (amplitudeRef) amplitudeRef.current = Number(msg.value) || 0;
      break;
    case 'presence': {
      const presence = makePresence(msg.data);
      if (amplitudeRef && msg.data && msg.data.amplitude !== undefined) {
        amplitudeRef.current = presence.amplitude;
      }
      dispatch({ type: 'SET_PRESENCE', payload: presence });
      break;
    }
    case 'diagnostic':
      dispatch({ type: 'SET_DIAGNOSTICS', payload: msg.report });
      break;
    case 'media_update':
      dispatch({ type: 'SET_MEDIA', payload: msg.media });
      break;
    case 'ambient_update':
      dispatch({ type: 'UPDATE_AMBIENT', payload: msg.data });
      break;
    case 'devices_update':
      dispatch({ type: 'UPDATE_DEVICES', payload: msg.data });
      break;
    case 'cameras_update':
      dispatch({ type: 'UPDATE_CAMERAS', payload: msg.data });
      break;
    case 'system_update':
      dispatch({ type: 'UPDATE_SYSTEM', payload: msg.data });
      break;
    case 'notifications_update':
      dispatch({ type: 'SET_NOTIFICATIONS', payload: msg.data });
      break;
    case 'vortex_state':
      dispatch({ type: 'SET_VORTEX_STATE', payload: msg.state });
      break;
    case 'navigate':
      dispatch({ type: 'SET_PAGE', payload: msg.page });
      break;
    case 'timers_update':
      dispatch({ type: 'SET_TIMERS', payload: msg.timers });
      break;
    case 'timer_done':
      dispatch({ type: 'TIMER_DONE', payload: msg.timer });
      break;
    case 'routine_update':
      dispatch({ type: 'SET_ROUTINE', payload: msg.routine });
      break;
    case 'intercom_update':
      dispatch({ type: 'SET_INTERCOM', payload: msg.intercom });
      break;
    case 'announcement':
      dispatch({ type: 'SET_ANNOUNCEMENT', payload: msg.announcement });
      break;
    case 'lists_update':
      dispatch({ type: 'SET_LISTS', payload: msg.lists });
      break;
    case 'reminders_update':
      dispatch({ type: 'SET_REMINDERS', payload: msg.reminders });
      break;
    default:
      break;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Page router
// ─────────────────────────────────────────────────────────────────────────────

function PageRouter({ page, diagnostics }) {
  switch (page) {
    case 'loading':   return null;
    case 'setup':     return <Setup />;
    case 'dashboard': return <Dashboard />;
    case 'devices':   return <Devices />;
    case 'cameras':   return <Cameras />;
    // Burn-in protection stages, driven by display/screen_manager.py.
    case 'boot':      return <Boot report={diagnostics} />;
    case 'nowplaying': return <NowPlaying />;
    case 'screensaver': return <Screensaver />;
    // Backlight is off; render pure black so waking does not flash the
    // previous screen before the next one paints.
    case 'off':       return <div style={styles.screenOff} />;
    case 'routine':   return <Routine />;
    case 'lists':     return <Lists />;
    case 'ambient':
    default:          return <Ambient />;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Vortex state indicator — shows listening/processing overlay
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Presence overlay — River's orb, shown over whatever page is active
 * whenever she is engaged. Hidden at rest so the ambient screen stays clean.
 *
 * The Ambient page renders its own full-size orb; this is the compact
 * version that appears on the interactive pages.
 *
 * @param {object} props
 * @param {object} props.presence     - Presence object from the reducer.
 * @param {object} props.amplitudeRef - Live 0..1 envelope ref.
 */
function PresenceOverlay({ presence, amplitudeRef }) {
  if (presence.state === 'idle') return null;
  return (
    <div className="presence-overlay orb-wrap--compact">
      <Orb presence={presence} amplitudeRef={amplitudeRef} size={84} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Root App component
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const [state, dispatch] = useReducer(appReducer, initialState);

  // Live TTS envelope. Held in a ref, not in reducer state — see the
  // 'amplitude' case in handleMessage for why.
  const amplitudeRef = useRef(0);

  useBackendSocket(dispatch, amplitudeRef);

  // The kiosk browser normally starts AFTER the backend, so the self-test can
  // already be finished by the time we connect and no 'diagnostic' frame will
  // ever arrive. Fetch the report once so a late start still sees it — and so
  // the handover below fires rather than waiting out the failsafe.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/vortex/v1/diagnostics')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data && data.results?.length) {
          dispatch({ type: 'SET_DIAGNOSTICS', payload: data });
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Leave the boot screen once the self-test is done, whichever route the
  // report arrived by. The pause lets the final verdict actually be read.
  const bootDone = state.diagnostics?.complete;
  useEffect(() => {
    if (!bootDone) return undefined;
    const id = setTimeout(() => dispatch({ type: 'BOOT_COMPLETE' }), 1400);
    return () => clearTimeout(id);
  }, [bootDone]);

  // Failsafe: never strand the unit on the boot screen. If the self-test
  // never reports -- backend crashed, WebSocket never connected -- hand over
  // anyway so the panel is at least usable.
  useEffect(() => {
    const id = setTimeout(() => dispatch({ type: 'BOOT_COMPLETE' }), 20000);
    return () => clearTimeout(id);
  }, []);

  const navigate = useCallback((page) => {
    dispatch({ type: 'SET_PAGE', payload: page });
  }, []);

  // On first load, check whether this unit has been paired with River Song.
  // Unpaired units land on the Setup (pairing) screen instead of Ambient.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        // Record whether this unit is paired, but do NOT route here. The boot
        // screen owns the first transition and reads system.configured when
        // the self-test completes — routing from both places raced, and this
        // one always won, so the boot screen was never seen at all.
        dispatch({ type: 'UPDATE_SYSTEM', payload: data });
      })
      .catch(() => {
        // Backend unreachable. Mark it unconfigured so the boot screen hands
        // over to Setup rather than an ambient screen with no data behind it.
        if (!cancelled) {
          dispatch({ type: 'UPDATE_SYSTEM', payload: { configured: false } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const contextValue = { state, dispatch, navigate, amplitudeRef };

  return (
    <AppContext.Provider value={contextValue}>
      <div style={styles.root}>
        <PageRouter page={state.page} diagnostics={state.diagnostics} />
        <IntercomBanner />
        <AnnouncementBanner />
        <ReminderBanner />
        <PresenceOverlay presence={state.presence} amplitudeRef={amplitudeRef} />
      </div>
    </AppContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles — inline for kiosk reliability (no CSS file dependency)
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  screenOff: {
    width: '100%',
    height: '100%',
    background: '#000',
    cursor: 'none',
  },
  root: {
    width: '100vw',
    height: '100vh',
    background: '#0a0a0f',
    color: '#e8e8f0',
    overflow: 'hidden',
    position: 'relative',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
};
