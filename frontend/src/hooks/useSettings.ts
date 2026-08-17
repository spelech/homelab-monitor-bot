import { useState, useEffect, useCallback } from 'react';

export function useSettings() {
  const [settings, setSettings] = useState<{
    silent_mode: boolean;
    autopilot: boolean;
    maintenance_mode: string;
    maintenance_active: boolean;
    maintenance_reason: string;
  }>({
    silent_mode: false,
    autopilot: false,
    maintenance_mode: 'false',
    maintenance_active: false,
    maintenance_reason: ''
  });

  const fetchSettings = useCallback(async () => {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        setSettings(data);
      }
    } catch (e) {
      console.error('Failed to load settings:', e);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
    const timer = setInterval(fetchSettings, 4000);
    return () => clearInterval(timer);
  }, [fetchSettings]);

  const toggleAutopilot = async () => {
    const nextVal = !settings.autopilot;
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ autopilot: nextVal })
      });
      await fetchSettings();
    } catch (e) {
      console.error('Failed to toggle autopilot:', e);
    }
  };

  const toggleSilentMode = async () => {
    const nextVal = !settings.silent_mode;
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ silent_mode: nextVal })
      });
      await fetchSettings();
    } catch (e) {
      console.error('Failed to toggle silent mode:', e);
    }
  };

  const setMaintenanceDuration = async (duration: string) => {
    try {
      const res = await fetch('/api/maintenance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration })
      });
      if (res.ok) {
        await fetchSettings();
      }
    } catch (e) {
      console.error('Failed to set maintenance mode:', e);
    }
  };

  return { settings, toggleAutopilot, toggleSilentMode, setMaintenanceDuration, refresh: fetchSettings };
}
