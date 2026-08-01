/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Boot.jsx
 * Purpose:  The boot screen — a cold-start self-test, shown while the unit
 *           brings itself up.
 *
 *           Every line here is a REAL check from core/diagnostics.py. Nothing
 *           is on a timer and nothing is faked: the pauses you see are the
 *           checks actually taking that long, and a line reading FAIL means
 *           that capability genuinely is not working. A wall-mounted unit with
 *           no keyboard needs somewhere to say what is wrong.
 *
 *           Styling follows the Halo palette already defined in
 *           presence/presenceContract.js, so the boot screen and River's orb
 *           come from one set of colours.
 * ============================================================================
 */

import React, { useEffect, useRef } from 'react';
import { PALETTES } from '../presence/presenceContract';

/** Tag shown against each check, and the colour it takes. */
const STATUS_STYLE = {
  ok:   { label: '  OK  ', color: '#78c8e6' },
  warn: { label: ' WARN ', color: '#d4a040' },
  fail: { label: ' FAIL ', color: '#cc5544' },
  skip: { label: ' SKIP ', color: '#3a7090' },
};

/**
 * Boot / self-test screen.
 *
 * @param {object} props
 * @param {object} [props.report] - The self-test report. App owns fetching it
 *        and following the live stream; this component only renders.
 */
export default function Boot({ report }) {
  const scrollRef = useRef(null);

  const results = report?.results || [];
  const complete = report?.complete;

  // Keep the newest line in view as checks complete.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [results.length]);

  const counts = report?.counts || {};
  const failed = (counts.fail || 0) > 0;

  return (
    <div className="boot">
      <div className="boot__scan" aria-hidden="true" />

      <div className="boot__inner">
        {/* Masthead */}
        <div className="boot__head">
          <div className="boot__title">RIVER VORTEX</div>
          <div className="boot__sub">
            SYSTEM INITIALISATION <span className="boot__dim">// SELF-TEST</span>
          </div>
        </div>

        {/* The checks */}
        <div className="boot__log" ref={scrollRef} role="log" aria-live="polite">
          {results.map((r) => {
            const style = STATUS_STYLE[r.status] || STATUS_STYLE.skip;
            return (
              <div className="boot__line" key={r.label}>
                <span className="boot__bracket">[</span>
                <span style={{ color: style.color }}>{style.label}</span>
                <span className="boot__bracket">]</span>
                <span className="boot__label">{r.label}</span>
                <span className="boot__dots" />
                <span className="boot__detail">{r.detail}</span>
                <span className="boot__ms">{r.elapsed_ms}ms</span>
              </div>
            );
          })}

          {!complete && (
            <div className="boot__line boot__line--active">
              <span className="boot__bracket">[</span>
              <span className="boot__spinner">····</span>
              <span className="boot__bracket">]</span>
              <span className="boot__label">SCANNING</span>
            </div>
          )}
        </div>

        {/* Summary */}
        <div className="boot__foot">
          {complete ? (
            <>
              <span
                className="boot__verdict"
                style={{ color: failed ? '#cc5544' : '#78c8e6' }}
              >
                {failed ? 'DEGRADED' : 'ALL SYSTEMS NOMINAL'}
              </span>
              <span className="boot__counts">
                {counts.ok || 0} OK · {counts.warn || 0} WARN ·{' '}
                {counts.fail || 0} FAIL · {counts.skip || 0} SKIP
              </span>
              <span className="boot__counts">{report.elapsed_ms}ms</span>
            </>
          ) : (
            <span className="boot__counts">
              {results.length}
              {report?.total ? ` of ${report.total}` : ''} subsystems verified
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// Referenced so the palette import is not dead: the CSS mirrors these values,
// and this keeps the coupling visible if the palette ever changes.
export const BOOT_PALETTE = PALETTES.halo;
