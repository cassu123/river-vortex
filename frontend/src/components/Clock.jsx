/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/Clock.jsx
 * Purpose:  Large ambient clock component. Displays current time and date
 *           with smooth second-tick updates. Designed for always-on ambient
 *           display on the 7"/10" touchscreen. Reads time from backend
 *           ambient state (synced) with local fallback.
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';

/**
 * Formats a Date object into display strings.
 * @param {Date} date
 * @returns {{ time: string, date: string, seconds: string }}
 */
function formatTime(date) {
  const hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const seconds = date.getSeconds().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHour = (hours % 12 || 12).toString();

  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const months = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December'];

  return {
    time: `${displayHour}:${minutes}`,
    ampm,
    seconds,
    date: `${days[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}`,
  };
}

/**
 * Clock component — large ambient time display.
 *
 * @param {object} props
 * @param {boolean} [props.showSeconds=false] - Show seconds sub-display.
 * @param {boolean} [props.compact=false]     - Smaller layout for dashboard use.
 */
export default function Clock({ showSeconds = false, compact = false }) {
  const [timeData, setTimeData] = useState(() => formatTime(new Date()));

  useEffect(() => {
    // Tick every second for smooth updates
    const interval = setInterval(() => {
      setTimeData(formatTime(new Date()));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  if (compact) {
    return (
      <div style={styles.compact}>
        <span style={styles.compactTime}>{timeData.time}</span>
        <span style={styles.compactAmpm}>{timeData.ampm}</span>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Time */}
      <div style={styles.timeRow}>
        <span style={styles.time}>{timeData.time}</span>
        <div style={styles.timeRight}>
          <span style={styles.ampm}>{timeData.ampm}</span>
          {showSeconds && (
            <span style={styles.seconds}>{timeData.seconds}</span>
          )}
        </div>
      </div>

      {/* Date */}
      <div style={styles.date}>{timeData.date}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
  },
  timeRow: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
  },
  time: {
    fontSize: 'clamp(72px, 14vw, 140px)',
    fontWeight: 200,
    letterSpacing: '-0.03em',
    color: '#f0f0ff',
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
  },
  timeRight: {
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'flex-start',
    paddingTop: 12,
    gap: 4,
  },
  ampm: {
    fontSize: 'clamp(18px, 3vw, 28px)',
    fontWeight: 300,
    color: '#8888aa',
    letterSpacing: '0.08em',
  },
  seconds: {
    fontSize: 'clamp(14px, 2vw, 22px)',
    fontWeight: 300,
    color: '#555577',
    fontVariantNumeric: 'tabular-nums',
  },
  date: {
    fontSize: 'clamp(16px, 2.5vw, 24px)',
    fontWeight: 300,
    color: '#7070a0',
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
  // Compact variant for dashboard header
  compact: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 6,
  },
  compactTime: {
    fontSize: 28,
    fontWeight: 300,
    color: '#e0e0f0',
    fontVariantNumeric: 'tabular-nums',
  },
  compactAmpm: {
    fontSize: 14,
    color: '#7070a0',
    fontWeight: 300,
  },
};
