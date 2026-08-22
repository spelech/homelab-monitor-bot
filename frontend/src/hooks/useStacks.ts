import { useState, useEffect, useCallback } from 'react';
import {
  StackSummary,
  StackDetail,
  StackAuditResult,
  StackCheckUpdatesResult
} from '../types/stack';

export function useStacks() {
  const [stacks, setStacks] = useState<StackSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [auditingStacks, setAuditingStacks] = useState<Record<string, boolean>>({});
  const [checkingUpdates, setCheckingUpdates] = useState<Record<string, boolean>>({});
  const [auditAllLoading, setAuditAllLoading] = useState<boolean>(false);

  const fetchStacks = useCallback(async () => {
    try {
      const res = await fetch('/api/stacks');
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data: StackSummary[] = await res.json();
      setStacks(data);
      setError(null);
    } catch (err: any) {
      console.error('Failed to load stacks:', err);
      setError(err.message || 'Failed to load stacks');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchStackDetail = useCallback(async (name: string): Promise<StackDetail | null> => {
    try {
      const res = await fetch(`/api/stacks/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      return await res.json();
    } catch (err: any) {
      console.error(`Failed to load stack detail for '${name}':`, err);
      return null;
    }
  }, []);

  const auditStack = useCallback(async (name: string): Promise<StackAuditResult | null> => {
    setAuditingStacks(prev => ({ ...prev, [name]: true }));
    try {
      const res = await fetch(`/api/stacks/${encodeURIComponent(name)}/audit`, {
        method: 'POST'
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Audit failed with HTTP ${res.status}`);
      await fetchStacks();
      return data;
    } catch (err: any) {
      console.error(`Failed to audit stack '${name}':`, err);
      alert(`Error auditing stack '${name}': ${err.message}`);
      return null;
    } finally {
      setAuditingStacks(prev => ({ ...prev, [name]: false }));
    }
  }, [fetchStacks]);

  const checkStackUpdates = useCallback(async (name: string): Promise<StackCheckUpdatesResult | null> => {
    setCheckingUpdates(prev => ({ ...prev, [name]: true }));
    try {
      const res = await fetch(`/api/stacks/${encodeURIComponent(name)}/check-updates`, {
        method: 'POST'
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Check updates failed with HTTP ${res.status}`);
      await fetchStacks();
      return data;
    } catch (err: any) {
      console.error(`Failed to check updates for stack '${name}':`, err);
      alert(`Error checking updates for stack '${name}': ${err.message}`);
      return null;
    } finally {
      setCheckingUpdates(prev => ({ ...prev, [name]: false }));
    }
  }, [fetchStacks]);

  const auditAllStacks = useCallback(async (): Promise<StackAuditResult[] | null> => {
    setAuditAllLoading(true);
    try {
      const res = await fetch('/api/stacks/audit-all', {
        method: 'POST'
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Audit all failed with HTTP ${res.status}`);
      await fetchStacks();
      return data;
    } catch (err: any) {
      console.error('Failed to audit all stacks:', err);
      alert(`Error auditing all stacks: ${err.message}`);
      return null;
    } finally {
      setAuditAllLoading(false);
    }
  }, [fetchStacks]);

  useEffect(() => {
    fetchStacks();
    const interval = setInterval(fetchStacks, 10000);
    return () => clearInterval(interval);
  }, [fetchStacks]);

  return {
    stacks,
    loading,
    error,
    auditingStacks,
    checkingUpdates,
    auditAllLoading,
    fetchStacks,
    fetchStackDetail,
    auditStack,
    checkStackUpdates,
    auditAllStacks
  };
}
