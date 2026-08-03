/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Settings.jsx
 * Purpose:  Device settings — the knobs that belong to THIS BOX.
 *
 *           Volume, brightness, mic mute, how eagerly it wakes. Not per
 *           person: nothing here changes depending on who is standing in
 *           front of it, and nothing here needs an account.
 *
 *           That is exactly why it lives on the device. The moment you most
 *           want to mute the microphone or turn the volume down is the moment
 *           the network is down and the app cannot reach you.
 *
 *           Account and per-device configuration managed centrally — which
 *           room a unit is in, the household wake word — lives in the River
 *           Song app under that device. This is the other half.
 * ============================================================================
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useApp } from '../App';

const SETTINGS_URL = '/api/vortex/v1/settings';

/**
 * A labelled slider sized for a finger, not a mouse.
 *
 * Commits on release rather than on every pixel of travel: dragging a
 * brightness slider would otherwise fire a hundred writes and a hundred
 * profile saves on the way past.
 */
function Slider({ label, value, min, max, step, unit, hint, onCommit, disabled }) {
  const [local, setLocal] = useState(value);

  // Follow the server when it changes underneath us — River Song can push a
  // new value — but never while a finger is mid-drag.
  useEffect(() => { setLocal(value); }, [value]);

  return (
    <div className={`setting ${disabled ? 'setting--off' : ''}`}>
      <div className="setting__row">
        <span className="setting__label">{label}</span>
        <span className="setting__value">
          {typeof local === 'number' ? local.toFixed(step < 1 ? 2 : 0) : local}{unit}
        </span>
      </div>
      <input
        type="range"
        className="setting__slider"
        min={min} max={max} step={step}
        value={local}
        disabled={disabled}
        onChange={(e) => setLocal(Number(e.target.value))}
        onMouseUp={() => onCommit(local)}
        onTouchEnd={() => onCommit(local)}
      />
      {hint && <div className="setting__hint">{hint}</div>}
    </div>
  );
}

/** A big toggle — the kind you can hit without looking. */
function Toggle({ label, hint, on, onChange, disabled, danger }) {
  return (
    <div className={`setting ${disabled ? 'setting--off' : ''}`}>
      <div className="setting__row">
        <span className="setting__label">{label}</span>
        <button
          type="button"
          className={`toggle ${on ? 'toggle--on' : ''} ${danger && on ? 'toggle--danger' : ''}`}
          disabled={disabled}
          aria-pressed={on}
          onClick={() => onChange(!on)}
        >
          <span className="toggle__knob" />
        </button>
      </div>
      {hint && <div className="setting__hint">{hint}</div>}
    </div>
  );
}

/**
 * Device settings page.
 */
export default function Settings() {
  const { navigate } = useApp();
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    fetch(SETTINGS_URL)
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then(setSettings)
      .catch(() => setError('Could not read this unit’s settings.'));
  }, []);

  useEffect(load, [load]);

  const update = useCallback((patch) => {
    // Optimistic: the slider should not spring back while the request flies.
    setSettings((s) => ({ ...s, ...patch }));
    setError('');
    fetch(SETTINGS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
      .then((res) => {
        if (!res.ok) throw new Error();
        return res.json();
      })
      .then((result) => {
        const refused = Object.values(result.refused || {});
        if (refused.length) setError(refused[0]);
      })
      .catch(() => {
        setError('That did not save. Reloading.');
        load();
      });
  }, [load]);

  if (!settings) {
    return (
      <div className="settings">
        <div className="settings__empty">{error || 'Loading…'}</div>
      </div>
    );
  }

  const can = settings.capabilities || {};

  return (
    <div className="settings">
      <div className="settings__head">
        <button type="button" className="settings__back" onClick={() => navigate('dashboard')}>
          ‹ Back
        </button>
        <div className="settings__title">
          {settings.unit_name || 'This unit'}
          {settings.location && <span className="settings__room"> · {settings.location}</span>}
        </div>
      </div>

      {error && <div className="settings__error" role="status">{error}</div>}

      <div className="settings__list">
        {can.volume && (
          <Slider
            label="Volume" value={settings.volume} min={0} max={100} step={5} unit="%"
            onCommit={(v) => update({ volume: v })}
          />
        )}

        {can.brightness && (
          <Slider
            label="Brightness" value={settings.brightness} min={10} max={100} step={5} unit="%"
            hint="The screen still dims and sleeps on its own to protect the panel."
            onCommit={(v) => update({ brightness: v })}
          />
        )}

        {can.wake_word && (
          <Slider
            label="Wake sensitivity"
            value={settings.wake_word_threshold}
            min={0.1} max={0.9} step={0.05} unit=""
            hint={
              `Higher means fewer false wakes and more missed ones. `
              + `Raise it in a noisy room. Listening for “${settings.wake_word || 'nothing'}”.`
            }
            onCommit={(v) => update({ wake_word_threshold: v })}
          />
        )}

        {can.microphone && (
          <Toggle
            label="Microphone muted"
            on={settings.mic_muted}
            danger
            // Locked, not just unhelpful: while the physical switch is on,
            // software genuinely cannot unmute, so a toggle that looked
            // available would be lying about who is in charge.
            disabled={settings.mic_switch_muted}
            hint={settings.mic_switch_muted
              ? 'Held muted by the physical switch on this unit. Flip the switch to listen again.'
              : 'Nothing is heard while this is on, including the wake word. Comes back on after a restart.'}
            onChange={(v) => update({ mic_muted: v })}
          />
        )}

        {can.camera && (
          <Toggle
            label="Camera muted" on={settings.camera_muted} danger
            hint={settings.camera_active
              ? 'The camera is live right now — the indicator is lit.'
              : 'The camera is not in use.'}
            onChange={(v) => update({ camera_muted: v })}
          />
        )}
      </div>

      {/* What someone standing at the panel actually wants to know: which unit
          is this, and is it talking to the server. */}
      <div className="settings__about">
        <div className="settings__fact">
          <span>River Song</span>
          <span className={settings.uplink_connected ? 'ok' : 'bad'}>
            {settings.uplink_connected ? 'Connected' : 'Not connected'}
          </span>
        </div>
        <div className="settings__fact">
          <span>Unit</span><span>{settings.unit_id}</span>
        </div>
        <div className="settings__fact">
          <span>Version</span><span>{settings.version}</span>
        </div>
      </div>
    </div>
  );
}
