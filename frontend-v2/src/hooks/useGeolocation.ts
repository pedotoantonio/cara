// On-demand geolocation hook — non-watching by default.
// Per il watch-mode (geofence reminders), useremo un'API diversa.

import { useCallback, useState } from 'react';

export interface GeoPosition {
  lat: number;
  lon: number;
  accuracy: number;
  timestamp: number;
}

export interface GeoState {
  position: GeoPosition | null;
  loading: boolean;
  error: string | null;
}

export function useGeolocation() {
  const [state, setState] = useState<GeoState>({ position: null, loading: false, error: null });

  const getOnce = useCallback(async (highAccuracy = false): Promise<GeoPosition | null> => {
    if (!('geolocation' in navigator)) {
      setState({ position: null, loading: false, error: 'Geolocazione non supportata' });
      return null;
    }
    setState({ position: null, loading: true, error: null });
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const p: GeoPosition = {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            timestamp: pos.timestamp,
          };
          setState({ position: p, loading: false, error: null });
          resolve(p);
        },
        (err) => {
          const msg =
            err.code === err.PERMISSION_DENIED
              ? 'Permesso negato'
              : err.code === err.POSITION_UNAVAILABLE
                ? 'Posizione non disponibile'
                : err.code === err.TIMEOUT
                  ? 'Timeout localizzazione'
                  : 'Errore localizzazione';
          setState({ position: null, loading: false, error: msg });
          resolve(null);
        },
        { enableHighAccuracy: highAccuracy, timeout: 8000, maximumAge: 60_000 },
      );
    });
  }, []);

  return { ...state, getOnce };
}
