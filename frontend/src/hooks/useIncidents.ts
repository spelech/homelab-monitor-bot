import { useState, useEffect, useCallback } from 'react';
import { Incident, DashboardData } from '../types/incident';

export function useIncidents() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch('/api/dashboard');
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setDashboard(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load incidents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    const timer = setInterval(fetchDashboard, 3000);
    return () => clearInterval(timer);
  }, [fetchDashboard]);

  const triggerAction = async (incidentId: string, action: 'fix' | 'defer' | 'ignore' | 'dismiss') => {
    try {
      const res = await fetch(`/api/incidents/${incidentId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      if (!res.ok) throw new Error(`Action failed with status ${res.status}`);
      await fetchDashboard();
      return true;
    } catch (err: any) {
      alert(`Error triggering ${action}: ${err.message}`);
      return false;
    }
  };

  const unignoreTarget = async (targetId: string) => {
    try {
      const res = await fetch(`/api/targets/${targetId}/unignore`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to unignore');
      await fetchDashboard();
      return true;
    } catch (err: any) {
      alert(`Error: ${err.message}`);
      return false;
    }
  };

  return { dashboard, loading, error, refresh: fetchDashboard, triggerAction, unignoreTarget };
}
