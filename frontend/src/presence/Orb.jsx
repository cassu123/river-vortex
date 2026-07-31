/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/presence/Orb.jsx
 * Purpose:  River's visible presence — a CSS/SVG orb driven by the presence
 *           contract. This is the always-on renderer, so it is built for the
 *           weakest target hardware (Raspberry Pi 4, Chromium kiosk):
 *
 *             - animates transform and opacity ONLY (GPU compositable)
 *             - no animated filter: blur() — glow is baked into gradients
 *             - amplitude is written to a CSS variable from a rAF loop, so
 *               a 30Hz audio envelope causes ZERO React re-renders
 *
 *           Consumes the same presence object the Rive character and the 3D
 *           holographic avatar will consume later.
 * ============================================================================
 */

import React, { useEffect, useMemo, useRef } from 'react';
import {
  ERROR_COLOR,
  PALETTES,
  STATE_TINT,
} from './presenceContract';

/**
 * Exponential smoothing factor for the amplitude envelope.
 * Lower = smoother but laggier. 0.25 tracks speech without jitter.
 */
const AMP_SMOOTHING = 0.25;

/**
 * River's presence orb.
 *
 * @param {object} props
 * @param {object} props.presence      - Presence object from presenceContract.
 * @param {object} [props.amplitudeRef] - Ref whose .current is the live 0..1
 *        envelope. Passed as a ref (not a prop value) deliberately: it updates
 *        at ~30Hz during speech and must not drive React renders.
 * @param {number} [props.size=280]    - Orb diameter in px.
 * @param {boolean} [props.showCaption=true] - Render the state caption.
 */
export default function Orb({
  presence,
  amplitudeRef = null,
  size = 280,
  showCaption = true,
}) {
  const rootRef = useRef(null);
  const smoothedRef = useRef(0);

  const { state, mood, caption } = presence;
  const tint = STATE_TINT[state] || STATE_TINT.idle;
  const palette = PALETTES[mood] || PALETTES.spice;

  // Colours shift toward the palette's accent as warmShift rises. Recomputed
  // only when state/mood change — never on amplitude.
  const cssVars = useMemo(() => {
    const bodyColor = tint.errorTint ? ERROR_COLOR : palette.warm;
    const coreColor = tint.errorTint ? ERROR_COLOR : palette.accent;

    return {
      '--orb-size': `${size}px`,
      '--orb-warm': bodyColor,
      '--orb-deep': tint.errorTint ? '#3a1a16' : palette.deep,
      '--orb-accent': coreColor,
      '--orb-silhouette': tint.errorTint ? '#e09a8a' : palette.silhouette,
      '--orb-glyph': palette.glyph,
      // Animation periods derive from the state's speed multiplier.
      '--orb-spin': `${28 / tint.speed}s`,
      '--orb-breathe': `${6 / tint.speed}s`,
      '--orb-bloom': tint.bloomBump,
      '--orb-warmshift': tint.warmShift,
      // Starting value; the rAF loop below overwrites this continuously.
      '--orb-amp': 0,
    };
  }, [size, palette, tint]);

  // ── Amplitude loop ────────────────────────────────────────────────────────
  // Reads the live envelope and writes it straight to CSS. Deliberately
  // outside React's render cycle: on a Pi 4, re-rendering this tree 30 times
  // a second is the difference between smooth and visibly stuttering.
  useEffect(() => {
    if (!amplitudeRef) return undefined;

    let frame = 0;
    const tick = () => {
      const node = rootRef.current;
      if (node) {
        const target = amplitudeRef.current || 0;
        const prev = smoothedRef.current;
        const next = prev + (target - prev) * AMP_SMOOTHING;
        smoothedRef.current = next;
        node.style.setProperty('--orb-amp', next.toFixed(3));
      }
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [amplitudeRef]);

  return (
    <div className="orb-wrap">
      <div
        ref={rootRef}
        className={`orb orb--${state}`}
        style={cssVars}
        role="img"
        aria-label={`River is ${state}`}
      >
        {/* Outer bloom — scales with amplitude, pre-baked gradient (no blur) */}
        <div className="orb__glow" />

        {/* Slowly rotating ring, speed set by state */}
        <div className="orb__ring" />

        {/* Main body */}
        <div className="orb__body" />

        {/* Bright inner core — the part that "speaks" */}
        <div className="orb__core" />

        {/* Drifting highlight, gives the surface motion at rest */}
        <div className="orb__shimmer" />
      </div>

      {showCaption && <div className="orb__caption">{caption}</div>}
    </div>
  );
}
