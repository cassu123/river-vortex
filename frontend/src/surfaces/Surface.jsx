/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/surfaces/Surface.jsx
 * Purpose:  Draws one surface — the card River Song has asked this unit to
 *           show right now.
 *
 *           This component is deliberately dumb. It knows how to render seven
 *           card shapes and nothing about when any of them is appropriate;
 *           that judgement needs the whole house's context and lives on the
 *           server. See surfaceContract.js.
 *
 *           PERFORMANCE — same contract as the orb. Cards animate in with
 *           transform and opacity only, because this runs on a Pi 4 and a
 *           card can appear while music is decoding.
 * ============================================================================
 */

import React, { useCallback, useState } from 'react';
import { isTakeover } from './surfaceContract';

const SURFACES_URL = '/api/vortex/v1/surfaces';

/**
 * Report a tapped button. The backend relays it to River Song, which is the
 * only thing that knows what the intent means and whether it is allowed — a
 * confirm card is a prompt, not an authorisation.
 *
 * @param {string} surfaceId
 * @param {object} action - {label, intent, style}
 * @returns {Promise<boolean>} True once River Song has accepted it.
 */
function sendIntent(surfaceId, action) {
  return fetch(`${SURFACES_URL}/${encodeURIComponent(surfaceId)}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ intent: action.intent }),
  })
    .then((res) => res.ok)
    .catch(() => false);
}

/** The body of each kind. Split out so the shell stays one shape. */
function SurfaceBody({ surface }) {
  switch (surface.kind) {
    case 'stat':
      return (
        <>
          <div className="surface__stat">
            <span className="surface__value">{surface.value}</span>
            {surface.unit && <span className="surface__unit">{surface.unit}</span>}
          </div>
          {/* A stat can carry a line of context ("coldest room in the house").
              Dropping it silently would lose half of what River sent. */}
          {surface.body && <p className="surface__body">{surface.body}</p>}
        </>
      );

    case 'list':
      return (
        <ul className="surface__list">
          {surface.items.map((item, i) => (
            // Items are plain strings from River Song and can repeat
            // ("milk" twice); the index is the only stable key available.
            <li className="surface__item" key={`${item}-${i}`}>{item}</li>
          ))}
        </ul>
      );

    case 'media':
      return (
        <div className="surface__media">
          {surface.image_url && (
            <img className="surface__art" src={surface.image_url} alt="" />
          )}
          <div className="surface__media-text">
            <div className="surface__media-title">{surface.title}</div>
            {surface.body && (
              <div className="surface__media-sub">{surface.body}</div>
            )}
          </div>
        </div>
      );

    case 'image':
      return (
        <div className="surface__image">
          {/* alt is empty: the caption below already carries the meaning,
              and a screen reader should not hear it twice. */}
          <img src={surface.image_url} alt="" />
          {surface.body && <div className="surface__caption">{surface.body}</div>}
        </div>
      );

    default:
      // note, alert and confirm all read as text — what differs is the
      // framing, which the shell handles.
      return surface.body ? <p className="surface__body">{surface.body}</p> : null;
  }
}

/**
 * One surface card.
 *
 * @param {object} props
 * @param {object} props.surface     - Normalised surface (see makeSurface).
 * @param {Function} [props.onDismiss] - Called when the user taps it away.
 */
export default function Surface({ surface, onDismiss }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const surfaceId = surface?.id;

  const handleAction = useCallback((action) => (event) => {
    event.stopPropagation();
    setBusy(true);
    setFailed(false);
    sendIntent(surfaceId, action).then((ok) => {
      setBusy(false);
      // Only take the card down once River Song has it. A tap that never
      // arrived must not look like one that did — on a wall panel the card
      // vanishing IS the confirmation that something happened.
      if (ok) {
        if (onDismiss) onDismiss(surfaceId);
      } else {
        setFailed(true);
      }
    });
  }, [surfaceId, onDismiss]);

  if (!surface) return null;

  const takeover = isTakeover(surface);
  const className = [
    'surface',
    `surface--${surface.kind}`,
    `surface--${surface.priority}`,
    takeover ? 'surface--takeover' : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={className}
      // A critical card is an interruption, so it announces itself. Anything
      // quieter is read in document order like the rest of the screen.
      role={takeover ? 'alertdialog' : 'group'}
      aria-live={takeover ? 'assertive' : 'off'}
      aria-label={surface.title || surface.body}
    >
      {surface.title && surface.kind !== 'media' && (
        <div className="surface__title">
          {surface.icon && <span className="surface__icon">{surface.icon}</span>}
          {surface.title}
        </div>
      )}

      <SurfaceBody surface={surface} />

      {surface.actions.length > 0 && (
        <div className="surface__actions">
          {surface.actions.map((action) => (
            <button
              type="button"
              key={action.intent}
              className={`surface__action surface__action--${action.style || 'default'}`}
              onClick={handleAction(action)}
              disabled={busy}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}

      {failed && (
        <div className="surface__failed" role="status">
          Couldn&rsquo;t reach River. Try again.
        </div>
      )}

      {/* A takeover covers the whole panel, so it must always offer a way
          out — otherwise a stuck doorbell card bricks the screen until its
          TTL runs down. */}
      {takeover && onDismiss && (
        <button
          type="button"
          className="surface__dismiss"
          onClick={() => onDismiss(surface.id)}
        >
          Dismiss
        </button>
      )}
    </div>
  );
}
