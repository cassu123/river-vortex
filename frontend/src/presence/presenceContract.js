/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/presence/presenceContract.js
 * Purpose:  The presence contract — the single state object that every River
 *           presence renderer consumes. The CSS orb reads it today; the Rive
 *           character and the 3D holographic avatar will read the SAME object
 *           later, so swapping renderers is one import and not a rewrite.
 *
 *           State vocabulary and per-state tuning are taken from River Song's
 *           existing prototype (RiverSongAI prototypes/presence-orb.html) so
 *           the hub and the server UI express River identically.
 * ============================================================================
 */

/**
 * The six presence states. This vocabulary is authoritative — it comes from
 * the River Song orb prototype, not from Vortex's internal VortexState enum.
 *
 * idle      — present but not engaged
 * listening — wake word confirmed, capturing the command
 * thinking  — audio sent to River Song, awaiting a response
 * speaking  — playing River's TTS response
 * acting    — River is executing something (scene, device change, confirmation)
 * error     — connection lost or a subsystem has failed
 */
export const PRESENCE_STATES = Object.freeze([
  'idle',
  'listening',
  'thinking',
  'speaking',
  'acting',
  'error',
]);

/**
 * Per-state visual tuning, ported from the prototype's STATE_TINT table.
 *
 * warmShift — hue push toward the palette's warm end (0..1)
 * bloomBump — additional glow intensity (0..1)
 * speed     — animation rate multiplier
 * errorTint — desaturate and shift to the fault colour
 */
export const STATE_TINT = Object.freeze({
  idle:      { warmShift: 0.0,  bloomBump: 0.00, speed: 1.0 },
  listening: { warmShift: 0.05, bloomBump: 0.18, speed: 1.6 },
  thinking:  { warmShift: 0.25, bloomBump: 0.12, speed: 2.2 },
  speaking:  { warmShift: 0.15, bloomBump: 0.28, speed: 1.3 },
  acting:    { warmShift: 0.4,  bloomBump: 0.22, speed: 1.4 },
  error:     { warmShift: 0.0,  bloomBump: 0.06, speed: 0.6, errorTint: true },
});

/** Default caption per state. Overridable by the backend via `caption`. */
export const STATE_MESSAGES = Object.freeze({
  idle:      "She's here.",
  listening: 'Listening · go ahead',
  thinking:  'Considering …',
  speaking:  'Speaking',
  acting:    'Working on it',
  error:     'Connection lost',
});

/**
 * Palettes, ported from the prototype. Hex ints there, CSS strings here.
 * `mood` selects a palette; adding a palette requires no renderer changes.
 */
export const PALETTES = Object.freeze({
  spice: {
    label: 'Spice',
    warm:       '#d4a040', // dusty amber
    deep:       '#6e3a16', // burnt copper
    silhouette: '#e8c878', // soft sand-gold
    accent:     '#ffd28a', // bright spice
    glyph:      '#8a5a28', // bronze etching
  },
  halo: {
    label: 'Halo',
    warm:       '#78c8e6', // pale cyan
    deep:       '#1a3a52', // navy
    silhouette: '#b0e0f0', // soft cyan
    accent:     '#e6f6ff', // bright platinum
    glyph:      '#3a7090', // muted teal
  },
});

/** Fault colour, used when STATE_TINT[state].errorTint is set. */
export const ERROR_COLOR = '#cc5544';

/**
 * Vortex's internal VortexState enum (core/constants.py) does not match the
 * presence vocabulary one-to-one. This is the mapping. Anything unrecognised
 * falls back to 'idle' rather than throwing — a wall panel must never blank
 * out because the backend sent an unexpected string.
 */
const VORTEX_STATE_MAP = Object.freeze({
  INITIALIZING:  'idle',
  IDLE:          'idle',
  LISTENING:     'listening',
  PROCESSING:    'thinking',
  RESPONDING:    'speaking',
  INTERCOM:      'acting',
  ERROR:         'error',
  SHUTTING_DOWN: 'idle',
});

/**
 * Normalise a backend state string into a presence state.
 *
 * Accepts either a presence state ('thinking') or a VortexState name
 * ('PROCESSING'), in any case. Unknown values degrade to 'idle'.
 *
 * @param {string} raw - State string from the backend.
 * @returns {string} A member of PRESENCE_STATES.
 */
export function toPresenceState(raw) {
  if (!raw) return 'idle';
  const lower = String(raw).toLowerCase();
  if (PRESENCE_STATES.includes(lower)) return lower;
  return VORTEX_STATE_MAP[String(raw).toUpperCase()] || 'idle';
}

/**
 * Build a complete, validated presence object from a partial backend payload.
 *
 * This is the object every renderer receives. Keeping construction in one
 * place means the Rive and holographic renderers cannot drift from the orb.
 *
 * @param {object} [payload]           - Raw payload from the backend.
 * @param {string} [payload.state]     - Presence or VortexState string.
 * @param {number} [payload.amplitude] - TTS envelope, 0..1.
 * @param {string} [payload.mood]      - Palette key (see PALETTES).
 * @param {string} [payload.caption]   - Overrides the default state message.
 * @returns {{state: string, amplitude: number, mood: string, caption: string}}
 */
export function makePresence(payload = {}) {
  const state = toPresenceState(payload.state);
  const rawAmp = Number(payload.amplitude);
  // Clamp defensively — a runaway value would blow the orb off screen.
  const amplitude = Number.isFinite(rawAmp) ? Math.min(1, Math.max(0, rawAmp)) : 0;
  const mood = PALETTES[payload.mood] ? payload.mood : 'spice';

  return {
    state,
    amplitude,
    mood,
    caption: payload.caption || STATE_MESSAGES[state],
  };
}

/** The resting presence, used before the socket delivers anything. */
export const IDLE_PRESENCE = makePresence({ state: 'idle' });
