import { useState, useEffect, useCallback, useMemo } from 'react';
import { DailyAuditReport } from '../types/audit';

export function useDailyAudits(days: number = 30) {
  const [reports, setReports] = useState<DailyAuditReport[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [actionInProgress, setActionInProgress] = useState<boolean>(false);

  const fetchReports = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/audits/daily?days=${days}`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data: DailyAuditReport[] = await res.json();
      setReports(data);
      setError(null);
      if (data.length > 0 && !selectedDate) {
        setSelectedDate(data[0].date);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load daily audit reports');
    } finally {
      setLoading(false);
    }
  }, [days, selectedDate]);

  useEffect(() => {
    fetchReports();
  }, [days]);

  const selectedReport = useMemo(() => {
    if (!reports || reports.length === 0) return null;
    if (!selectedDate) return reports[0];
    return reports.find(r => r.date === selectedDate) || reports[0];
  }, [reports, selectedDate]);

  const triggerSingleAction = async (incidentId: string, action: 'fix' | 'defer' | 'ignore' | 'dismiss') => {
    try {
      setActionInProgress(true);
      const res = await fetch(`/api/incidents/${incidentId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      if (!res.ok) throw new Error(`Action failed with HTTP ${res.status}`);
      await fetchReports();
      return true;
    } catch (err: any) {
      alert(`Error triggering ${action}: ${err.message}`);
      return false;
    } finally {
      setActionInProgress(false);
    }
  };

  const triggerBulkAction = async (action: 'fix' | 'defer' | 'ignore' | 'dismiss', incidentIds: string[]) => {
    if (incidentIds.length === 0) return false;
    try {
      setActionInProgress(true);
      const res = await fetch('/api/audits/actions/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, incident_ids: incidentIds })
      });
      if (!res.ok) throw new Error(`Bulk action failed with HTTP ${res.status}`);
      await fetchReports();
      return true;
    } catch (err: any) {
      alert(`Error running bulk ${action}: ${err.message}`);
      return false;
    } finally {
      setActionInProgress(false);
    }
  };

  return {
    reports,
    loading,
    error,
    selectedDate,
    setSelectedDate,
    selectedReport,
    actionInProgress,
    refresh: fetchReports,
    triggerSingleAction,
    triggerBulkAction
  };
}
