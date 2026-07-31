/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Screensaver.jsx
 * Purpose:  Burn-in protection. A wall panel shows the same layout for 16
 *           hours a day, which is exactly how a permanent ghost of the clock
 *           gets etched into the display.
 *
 *           This screen shows a very dim clock that repositions itself every
 *           45 seconds, so no pixel holds a bright value for long. Everything
 *           else is pure black.
 *
 *           The backend dims the backlight to match (see display/
 *           screen_manager.py). After a longer idle it cuts the backlight
 *           entirely and this is replaced by ScreenOff.
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';

/** How often the clock jumps to a new position, in ms. */
const DRIFT_INTERVAL_MS = 45000;

/**
 * Pick a random position, kept away from the extreme edges so the clock is
 * never clipped and never sits in a screen corner.
 *
 * @returns {{top: string, left: string}} CSS percentage offsets.
 */
function randomPosition() {
  return {
    top: `${15 + Math.random() * 60}%`,
    left: `${15 + Math.random() * 60}%`,
  };
}

/**
 * Drifting dim clock shown after a long idle.
 */
export default function Screensaver() {
  const [now, setNow] = useState(() => new Date());
  const [pos, setPos] = useState(randomPosition);

  // Tick the clock. Once a minute is enough — seconds would be both
  // pointless at this brightness and needless wakeups on a Pi.
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(id);
  }, []);

  // Reposition periodically. This is the entire point of the screen.
  useEffect(() => {
    const id = setInterval(() => setPos(randomPosition()), DRIFT_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const time = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  return (
    <div style={styles.container} role="img" aria-label={`Screensaver, ${time}`}>
      <div style={{ ...styles.clock, top: pos.top, left: pos.left }}>
        {time}
      </div>
    </div>
  );
}

const styles = {
  container: {
    width: '100%',
    height: '100%',
    // Pure black, not the app's near-black: on an OLED these pixels are off,
    // and on an LCD it is the least light the panel can emit.
    background: '#000',
    position: 'relative',
    overflow: 'hidden',
    cursor: 'none',
  },
  clock: {
    position: 'absolute',
    // Deliberately dim. Bright enough to read across a dark room, dim enough
    // that it is not burning anything in while it sits there.
    color: '#2a2a35',
    fontSize: 'clamp(40px, 7vw, 88px)',
    fontWeight: 200,
    letterSpacing: '0.02em',
    // Long, eased move so the jump reads as a slow drift rather than a glitch.
    transition: 'top 8s ease-in-out, left 8s ease-in-out',
    userSelect: 'none',
  },
};
