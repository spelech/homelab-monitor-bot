import { useState, useEffect, useCallback } from 'react';
import { AIUsageSummary } from '../types/usage';

export function useUsage() {
  const [summary, setSummary] = useState<AIUsageSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch('/api/usage/summary');
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
      }
    } catch (e) {
      console.error('Failed to load AI usage summary:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSummary();
    const timer = setInterval(fetchSummary, 5000);
    return () => clearInterval(timer);
  }, [fetchSummary]);

  return { summary, loading, refresh: fetchSummary };
}
