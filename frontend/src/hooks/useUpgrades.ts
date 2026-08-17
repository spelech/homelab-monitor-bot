import { useState, useEffect, useCallback } from 'react';
import { StackInfo, UpgradeJob, UpgradeRunHistory, CanaryResults } from '../types/upgrade';

export function useUpgrades() {
  const [stacks, setStacks] = useState<StackInfo[]>([]);
  const [liveJob, setLiveJob] = useState<UpgradeJob | null>(null);
  const [runs, setRuns] = useState<UpgradeRunHistory[]>([]);
  const [canaryResult, setCanaryResult] = useState<CanaryResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [canaryLoading, setCanaryLoading] = useState(false);

  const fetchStacks = useCallback(async () => {
    try {
      const res = await fetch('/api/upgrades/stacks');
      if (res.ok) {
        const data = await res.json();
        setStacks(data);
      }
    } catch (e) {
      console.error('Failed to load stacks:', e);
    }
  }, []);

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch('/api/upgrades/runs');
      if (res.ok) {
        const data = await res.json();
        setRuns(data);
      }
    } catch (e) {
      console.error('Failed to load upgrade runs:', e);
    }
  }, []);

  const pollLiveStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/upgrades/live');
      if (res.ok) {
        const data = await res.json();
        if (data.job) {
          setLiveJob(data.job);
        } else {
          setLiveJob(null);
        }
      }
    } catch (e) {
      console.error('Failed to poll live upgrade status:', e);
    }
  }, []);

  useEffect(() => {
    fetchStacks();
    fetchRuns();
    pollLiveStatus();

    const timer = setInterval(() => {
      pollLiveStatus();
      fetchRuns();
    }, 2000);

    return () => clearInterval(timer);
  }, [fetchStacks, fetchRuns, pollLiveStatus]);

  const triggerUpgrade = async (targets?: string[]) => {
    setLoading(true);
    try {
      const res = await fetch('/api/upgrades/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targets: targets || ['all'] })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to start upgrade');
      await pollLiveStatus();
      return data;
    } catch (err: any) {
      alert(`Error starting upgrade: ${err.message}`);
      return null;
    } finally {
      setLoading(false);
    }
  };

  const cancelUpgrade = async () => {
    try {
      const res = await fetch('/api/upgrades/cancel', { method: 'POST' });
      await pollLiveStatus();
      return await res.json();
    } catch (e: any) {
      alert(`Error cancelling upgrade: ${e.message}`);
    }
  };

  const runCanaryAudit = async () => {
    setCanaryLoading(true);
    try {
      const res = await fetch('/api/upgrades/canary', { method: 'POST' });
      const data = await res.json();
      setCanaryResult(data);
      return data;
    } catch (e: any) {
      alert(`Error running canary audit: ${e.message}`);
      return null;
    } finally {
      setCanaryLoading(false);
    }
  };

  return {
    stacks,
    liveJob,
    runs,
    canaryResult,
    loading,
    canaryLoading,
    triggerUpgrade,
    cancelUpgrade,
    runCanaryAudit,
    refreshRuns: fetchRuns
  };
}
