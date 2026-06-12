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
import AnnouncementBanner from './components/AnnouncementBanner';
import IntercomBanner from './components/IntercomBanner';
import ReminderBanner from './components/ReminderBanner';

// ─────────────────────────────────────────────────────────────────────────────
// App Context — shared state accessible to all child components
// ─────────────────────────────────────────────────────────────────────────────

const initialState = {
  /** Current display page: 'loading' | 'setup' | 'ambient' | 'dashboard' | 'devices' | 'cameras' */
  page: 'loading',
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
      return { ...state, vortexState: action.payload };
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

function useBackendSocket(dispatch) {
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
      reconnectTimer.current = setTimeout(connect, WS_RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg, dispatch);
      } catch {
        // Ignore malformed messages
      }
    };
  }, [dispatch]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return wsRef;
}

function handleMessage(msg, dispatch) {
  switch (msg.type) {
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

function PageRouter({ page }) {
  switch (page) {
    case 'loading':   return null;
    case 'setup':     return <Setup />;
    case 'dashboard': return <Dashboard />;
    case 'devices':   return <Devices />;
    case 'cameras':   return <Cameras />;
    case 'routine':   return <Routine />;
    case 'lists':     return <Lists />;
    case 'ambient':
    default:          return <Ambient />;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Vortex state indicator — shows listening/processing overlay
// ─────────────────────────────────────────────────────────────────────────────

const STATE_LABELS = {
  listening:  'Listening…',
  processing: 'Thinking…',
  responding: 'Speaking…',
};

function VortexStateOverlay({ vortexState }) {
  if (vortexState === 'idle') return null;
  return (
    <div style={styles.overlay}>
      <div style={styles.overlayPulse} />
      <span style={styles.overlayLabel}>{STATE_LABELS[vortexState] || ''}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Root App component
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const [state, dispatch] = useReducer(appReducer, initialState);
  useBackendSocket(dispatch);

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
        dispatch({ type: 'UPDATE_SYSTEM', payload: data });
        dispatch({ type: 'SET_PAGE', payload: data.configured ? 'ambient' : 'setup' });
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: 'SET_PAGE', payload: 'ambient' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const contextValue = { state, dispatch, navigate };

  return (
    <AppContext.Provider value={contextValue}>
      <div style={styles.root}>
        <PageRouter page={state.page} />
        <IntercomBanner />
        <AnnouncementBanner />
        <ReminderBanner />
        <VortexStateOverlay vortexState={state.vortexState} />
      </div>
    </AppContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles — inline for kiosk reliability (no CSS file dependency)
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  root: {
    width: '100vw',
    height: '100vh',
    background: '#0a0a0f',
    color: '#e8e8f0',
    overflow: 'hidden',
    position: 'relative',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  overlay: {
    position: 'absolute',
    bottom: 32,
    left: '50%',
    transform: 'translateX(-50%)',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    background: 'rgba(10,10,20,0.85)',
    border: '1px solid rgba(100,160,255,0.3)',
    borderRadius: 32,
    padding: '10px 24px',
    backdropFilter: 'blur(12px)',
    zIndex: 100,
  },
  overlayPulse: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: '#4a9eff',
    animation: 'pulse 1.2s ease-in-out infinite',
  },
  overlayLabel: {
    fontSize: 15,
    color: '#a0c4ff',
    letterSpacing: '0.04em',
  },
};
