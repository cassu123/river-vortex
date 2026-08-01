/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/surfaces/surfaceContract.js
 * Purpose:  The surface contract — how River Song tells a unit what to show.
 *
 *           The point of this file is that Vortex does NOT decide what is
 *           important. River Song knows the room, the time, who is home and
 *           what is happening; the unit just renders what it is handed. That
 *           keeps "show me something new" a server-side change rather than a
 *           frontend release every time.
 *
 *           A surface is a small declarative descriptor — a kind, a payload,
 *           a priority and a lifetime. The renderer knows how to draw a fixed
 *           set of kinds; River Song composes them.
 * ============================================================================
 */

/**
 * The card shapes a unit can draw. Deliberately few: every kind added here is
 * a permanent commitment the renderer has to keep supporting.
 *
 * note    — a line or two of text. The default for "you should know this".
 * list    — a titled list of short items (shopping, todo, agenda).
 * stat    — one big number with a label. Temperature, count, time remaining.
 * media   — artwork with title and subtitle. What is playing.
 * image   — a full-bleed image with an optional caption. Camera snapshot.
 * alert   — something wrong that wants attention.
 * confirm — a question with actions. The second factor for a risky command.
 */
export const SURFACE_KINDS = Object.freeze([
  'note', 'list', 'stat', 'media', 'image', 'alert', 'confirm',
]);

/**
 * How insistent a surface is.
 *
 * ambient  — shown only when nothing else wants the screen. Idle-time filler.
 * normal   — the usual "here is something useful now".
 * high     — pushes past ambient content and wakes the screen.
 * critical — takes over the display entirely. Doorbell, alarm, smoke.
 */
export const SURFACE_PRIORITIES = Object.freeze(['ambient', 'normal', 'high', 'critical']);

/** Numeric weight, so surfaces can be compared. Higher wins. */
const PRIORITY_WEIGHT = Object.freeze({
  ambient: 0, normal: 1, high: 2, critical: 3,
});

/** Priorities that justify interrupting whatever is on screen. */
const INTERRUPTING = Object.freeze(['high', 'critical']);

/** Fallback lifetime when River Song does not specify one, in seconds. */
const DEFAULT_TTL_SECONDS = 120;

/**
 * Normalise a raw surface descriptor from the backend.
 *
 * Every field is defended, because a malformed surface must degrade to
 * something harmless rather than blanking a wall panel.
 *
 * @param {object} raw - Descriptor as received.
 * @returns {object|null} A validated surface, or null if unusable.
 */
export function makeSurface(raw) {
  if (!raw || typeof raw !== 'object') return null;

  const kind = SURFACE_KINDS.includes(raw.kind) ? raw.kind : 'note';
  const priority = SURFACE_PRIORITIES.includes(raw.priority) ? raw.priority : 'normal';

  // An id lets River Song update or withdraw a surface it already sent —
  // "the garage is still open" should replace itself, not stack up.
  const id = String(raw.id || `${kind}-${Date.now()}`);

  return {
    id,
    kind,
    priority,
    weight: PRIORITY_WEIGHT[priority],
    title: raw.title ? String(raw.title) : '',
    body: raw.body ? String(raw.body) : '',
    value: raw.value !== undefined && raw.value !== null ? String(raw.value) : '',
    unit: raw.unit ? String(raw.unit) : '',
    items: Array.isArray(raw.items) ? raw.items.map(String).slice(0, 8) : [],
    image_url: raw.image_url ? String(raw.image_url) : '',
    icon: raw.icon ? String(raw.icon) : '',
    actions: Array.isArray(raw.actions) ? raw.actions.slice(0, 3) : [],
    expires_at: deadlineOf(raw),
  };
}

/**
 * Work out when a surface stops being valid, as a JS epoch in milliseconds.
 *
 * An absolute deadline rather than a countdown, because comparing against a
 * stored timestamp survives the tab being backgrounded — a Pi that suspends
 * rAF for an hour must not come back with an hour still on the clock.
 *
 * Two shapes arrive here, and reading only one of them is how a card ends up
 * pinned to the screen for the default lifetime no matter what was asked for:
 *
 *   - `expires_at`   — what core/surfaces.py broadcasts, in UNIX SECONDS.
 *   - `ttl_seconds`  — what a hand-written or mocked descriptor carries.
 *
 * @param {object} raw
 * @returns {number} Epoch milliseconds.
 */
function deadlineOf(raw) {
  const absolute = Number(raw.expires_at);
  if (Number.isFinite(absolute) && absolute > 0) {
    // Seconds vs milliseconds: anything below this threshold is a timestamp
    // in seconds, since as milliseconds it would be somewhere in 1970.
    return absolute < 1e11 ? absolute * 1000 : absolute;
  }

  const ttl = Number(raw.ttl_seconds);
  const seconds = Number.isFinite(ttl) && ttl > 0 ? ttl : DEFAULT_TTL_SECONDS;
  return Date.now() + seconds * 1000;
}

/**
 * Merge an incoming surface into the current set.
 *
 * Replaces by id rather than appending, so a surface that updates itself does
 * not pile up duplicates on the screen.
 *
 * @param {object[]} surfaces - Current surfaces.
 * @param {object} incoming   - Already normalised via makeSurface.
 * @returns {object[]} The new set.
 */
export function upsertSurface(surfaces, incoming) {
  if (!incoming) return surfaces;
  const without = surfaces.filter((s) => s.id !== incoming.id);
  return [...without, incoming];
}

/**
 * Drop a surface by id — River Song withdrawing something before it expires.
 *
 * @param {object[]} surfaces
 * @param {string} id
 * @returns {object[]}
 */
export function removeSurface(surfaces, id) {
  return surfaces.filter((s) => s.id !== String(id));
}

/**
 * Discard anything past its lifetime.
 *
 * @param {object[]} surfaces
 * @param {number} [now] - Injectable for tests.
 * @returns {object[]}
 */
export function pruneSurfaces(surfaces, now = Date.now()) {
  return surfaces.filter((s) => s.expires_at > now);
}

/**
 * Pick the surface that should be on screen.
 *
 * Highest priority wins; ties go to the most recently received, because when
 * two things are equally important the newer one is the news.
 *
 * @param {object[]} surfaces
 * @param {number} [now]
 * @returns {object|null} The winner, or null if there is nothing to show.
 */
export function topSurface(surfaces, now = Date.now()) {
  const live = pruneSurfaces(surfaces, now);
  if (live.length === 0) return null;
  return live.reduce((best, s) => (s.weight >= best.weight ? s : best));
}

/**
 * Whether a surface justifies interrupting — waking the screen, or pushing
 * past the ambient view.
 *
 * @param {object|null} surface
 * @returns {boolean}
 */
export function isInterrupting(surface) {
  return Boolean(surface) && INTERRUPTING.includes(surface.priority);
}

/**
 * Whether a surface should take the whole screen rather than sit within the
 * ambient layout.
 *
 * @param {object|null} surface
 * @returns {boolean}
 */
export function isTakeover(surface) {
  return Boolean(surface) && surface.priority === 'critical';
}
