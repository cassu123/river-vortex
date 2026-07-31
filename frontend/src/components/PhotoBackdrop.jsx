/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/components/PhotoBackdrop.jsx
 * Purpose:  The ambient photo layer. Slowly crossfades through the unit's
 *           photo library behind the clock and weather, the way a Nest Hub
 *           does, and slowly pans each frame so the image is never static.
 *
 *           PERFORMANCE — this runs 16 hours a day on a Pi 4:
 *             - exactly two <img> layers, crossfaded with opacity
 *             - the pan is a transform, so both stay on the compositor
 *             - the next image is preloaded before the swap, so a slow SD
 *               card read never shows as a flash of empty background
 *
 *           Renders nothing at all when the library is empty, leaving the
 *           plain gradient behind it — a unit with no photos should look
 *           deliberate, not broken.
 * ============================================================================
 */

import React, { useEffect, useRef, useState } from 'react';

const PLAYLIST_URL = '/api/vortex/v1/photos';

/** Fallback hold time if the backend does not supply one, in ms. */
const DEFAULT_INTERVAL_MS = 90000;

/**
 * Preload an image so the crossfade never reveals a half-loaded frame.
 *
 * @param {string} url
 * @returns {Promise<void>} Resolves on load, and also on error so one bad
 *          file cannot stall the whole rotation.
 */
function preload(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = resolve;
    img.onerror = resolve;
    img.src = url;
  });
}

/**
 * Ambient photo backdrop.
 *
 * @param {object} props
 * @param {boolean} [props.dimmed=false] - Extra dimming, for screens where
 *        legibility of the overlaid text matters more than the image.
 */
export default function PhotoBackdrop({ dimmed = false }) {
  const [photos, setPhotos] = useState([]);
  const [intervalMs, setIntervalMs] = useState(DEFAULT_INTERVAL_MS);
  const [index, setIndex] = useState(0);
  // Which of the two layers is currently the visible one.
  const [front, setFront] = useState(0);
  const [urls, setUrls] = useState(['', '']);
  const timerRef = useRef(null);

  // Fetch the playlist once on mount. A failure here is not an error worth
  // showing: the unit simply has no photos and falls back to the gradient.
  useEffect(() => {
    let cancelled = false;
    fetch(PLAYLIST_URL)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data || !Array.isArray(data.photos)) return;
        setPhotos(data.photos);
        if (data.interval_seconds) setIntervalMs(data.interval_seconds * 1000);
        if (data.photos.length > 0) {
          setUrls([data.photos[0].url, '']);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Advance the rotation.
  useEffect(() => {
    if (photos.length < 2) return undefined;

    const advance = async () => {
      const nextIndex = (index + 1) % photos.length;
      const nextUrl = photos[nextIndex].url;

      // Load before showing, so the swap is always a clean crossfade.
      await preload(nextUrl);

      const back = front === 0 ? 1 : 0;
      setUrls((prev) => {
        const next = [...prev];
        next[back] = nextUrl;
        return next;
      });
      setFront(back);
      setIndex(nextIndex);
    };

    timerRef.current = setTimeout(advance, intervalMs);
    return () => clearTimeout(timerRef.current);
  }, [photos, index, front, intervalMs]);

  if (photos.length === 0) return null;

  return (
    <div className="photo-backdrop" aria-hidden="true">
      {[0, 1].map((layer) => (
        urls[layer] ? (
          <img
            key={layer}
            className={`photo-backdrop__img${front === layer ? ' is-front' : ''}`}
            src={urls[layer]}
            alt=""
          />
        ) : null
      ))}
      {/* Scrim. Without this, a bright photo makes white text unreadable —
          the clock has to stay legible over whatever image lands. */}
      <div className={`photo-backdrop__scrim${dimmed ? ' is-dimmed' : ''}`} />
    </div>
  );
}
