/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/Weather.jsx
 * Purpose:  Weather display component for ambient and dashboard modes.
 *           Renders current conditions, temperature, and a short forecast
 *           from data provided by the backend (sourced from River Song API).
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-05-25
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React from 'react';
import { useApp } from '../App';

/**
 * Maps weather condition strings to emoji icons.
 * @param {string} condition
 * @returns {string}
 */
function weatherIcon(condition = '') {
  const c = condition.toLowerCase();
  if (c.includes('clear') || c.includes('sunny'))  return '☀️';
  if (c.includes('partly cloudy'))                  return '⛅';
  if (c.includes('cloud'))                          return '☁️';
  if (c.includes('rain') || c.includes('drizzle'))  return '🌧️';
  if (c.includes('thunder') || c.includes('storm')) return '⛈️';
  if (c.includes('snow'))                           return '❄️';
  if (c.includes('fog') || c.includes('mist'))      return '🌫️';
  if (c.includes('wind'))                           return '💨';
  return '🌡️';
}

/**
 * Weather component.
 *
 * @param {object} props
 * @param {boolean} [props.compact=false] - Compact single-line layout for dashboard.
 */
export default function Weather({ compact = false }) {
  const { state } = useApp();
  const weather = state.ambient?.weather || {};

  const {
    temperature,
    feels_like,
    condition = '',
    humidity,
    location = '',
    unit = '°F',
    forecast = [],
  } = weather;

  // No data yet
  if (!condition && temperature === undefined) {
    return (
      <div style={styles.empty}>
        <span style={styles.emptyIcon}>🌡️</span>
        <span style={styles.emptyText}>Weather loading…</span>
      </div>
    );
  }

  if (compact) {
    return (
      <div style={styles.compact}>
        <span style={styles.compactIcon}>{weatherIcon(condition)}</span>
        <span style={styles.compactTemp}>
          {temperature !== undefined ? `${Math.round(temperature)}${unit}` : '—'}
        </span>
        <span style={styles.compactCondition}>{condition}</span>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Current conditions */}
      <div style={styles.current}>
        <span style={styles.icon}>{weatherIcon(condition)}</span>
        <div style={styles.currentDetails}>
          <span style={styles.temp}>
            {temperature !== undefined ? `${Math.round(temperature)}${unit}` : '—'}
          </span>
          <span style={styles.condition}>{condition}</span>
          {feels_like !== undefined && (
            <span style={styles.feelsLike}>Feels like {Math.round(feels_like)}{unit}</span>
          )}
          {humidity !== undefined && (
            <span style={styles.humidity}>💧 {humidity}%</span>
          )}
        </div>
      </div>

      {/* Location */}
      {location && <div style={styles.location}>{location}</div>}

      {/* Short forecast */}
      {forecast.length > 0 && (
        <div style={styles.forecast}>
          {forecast.slice(0, 4).map((day, i) => (
            <div key={i} style={styles.forecastDay}>
              <span style={styles.forecastLabel}>{day.label || day.day}</span>
              <span style={styles.forecastIcon}>{weatherIcon(day.condition)}</span>
              <span style={styles.forecastTemp}>
                {day.high !== undefined ? `${Math.round(day.high)}°` : '—'}
              </span>
            </div>
          ))}
        </div>
      )}
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
    gap: 12,
  },
  current: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
  },
  icon: {
    fontSize: 'clamp(36px, 6vw, 56px)',
    lineHeight: 1,
  },
  currentDetails: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  temp: {
    fontSize: 'clamp(28px, 5vw, 48px)',
    fontWeight: 200,
    color: '#e8e8f8',
    lineHeight: 1,
  },
  condition: {
    fontSize: 'clamp(13px, 2vw, 18px)',
    color: '#9090b8',
    fontWeight: 300,
  },
  feelsLike: {
    fontSize: 12,
    color: '#666688',
  },
  humidity: {
    fontSize: 12,
    color: '#666688',
  },
  location: {
    fontSize: 12,
    color: '#555577',
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
  forecast: {
    display: 'flex',
    gap: 16,
    marginTop: 4,
  },
  forecastDay: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 4,
    minWidth: 44,
  },
  forecastLabel: {
    fontSize: 11,
    color: '#666688',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  forecastIcon: {
    fontSize: 18,
  },
  forecastTemp: {
    fontSize: 13,
    color: '#a0a0c0',
    fontWeight: 300,
  },
  // Compact variant
  compact: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  compactIcon: {
    fontSize: 20,
  },
  compactTemp: {
    fontSize: 18,
    fontWeight: 300,
    color: '#e0e0f0',
  },
  compactCondition: {
    fontSize: 13,
    color: '#7070a0',
  },
  // Empty state
  empty: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    opacity: 0.4,
  },
  emptyIcon: {
    fontSize: 20,
  },
  emptyText: {
    fontSize: 14,
    color: '#7070a0',
  },
};
