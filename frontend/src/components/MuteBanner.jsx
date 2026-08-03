/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/MuteBanner.jsx
 * Purpose:  "Microphone muted" — shown whenever this unit is not listening.
 *
 *           Deliberately persistent, not a toast. A notification that fades
 *           tells you the microphone was muted a moment ago; this has to tell
 *           you it is muted NOW, at a glance, from across the room, without
 *           anyone having to remember they flipped a switch three days ago.
 *
 *           It sits above everything including a critical surface takeover.
 *           Nothing River Song can push is more important than being honest
 *           about whether the room is being listened to.
 * ============================================================================
 */

import React from 'react';
import { useApp } from '../App';

/**
 * Persistent mute indicator.
 *
 * Renders nothing when the microphone is live — the absence of this banner is
 * itself the signal, so it must never linger on a unit that is listening.
 */
export default function MuteBanner() {
  const { state } = useApp();
  const privacy = state.privacy || {};

  if (!privacy.mic_muted) return null;

  // A switch you can see beats a setting you have to remember. When the mute
  // came from hardware, say so — it tells the user where to go to undo it,
  // and it is a stronger promise than a software flag.
  const bySwitch = privacy.mic_switch_muted;

  return (
    <div className={`mute-banner ${bySwitch ? 'mute-banner--switch' : ''}`}
         role="status" aria-live="polite">
      <span className="mute-banner__icon" aria-hidden="true">🎙</span>
      <span className="mute-banner__text">
        Microphone muted
        {bySwitch && <span className="mute-banner__how"> — switch is on</span>}
      </span>
    </div>
  );
}
