import React, { useState } from 'react';
import { Search, Brain, Terminal, HelpCircle } from 'lucide-react';
import { Incident } from '../types/incident';

export const MemorySearchView: React.FC = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setHasSearched(true);
    try {
      const res = await fetch(`/api/incidents/search?q=${encodeURIComponent(query)}&limit=10`);
      if (res.ok) {
        const data = await res.json();
        setResults(data);
      }
    } catch (err) {
      console.error('Semantic search failed:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* Search Header */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-title" style={{ marginBottom: '0.75rem' }}>
          <Brain size={20} className="text-emerald" />
          <span>Semantic SRE Vector Memory (Qdrant)</span>
        </div>
        <p className="text-secondary" style={{ fontSize: '0.875rem', marginBottom: '1.25rem' }}>
          Query past incident root causes and learned remediation patterns using natural language.
        </p>

        <form onSubmit={handleSearch} className="flex-row gap-sm">
          <input
            type="text"
            className="input-text"
            placeholder="e.g. 'permission error on postgres databases', 'network timeout caddy', 'OOM crash'..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <button type="submit" className="btn btn-primary" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
            <Search size={16} />
            <span>{loading ? 'Searching...' : 'Search Memory'}</span>
          </button>
        </form>
      </div>

      {/* Search Results */}
      <div>
        {hasSearched && (
          <div className="text-muted" style={{ fontSize: '0.85rem', marginBottom: '1rem' }}>
            Found {results.length} similar resolutions in vector database:
          </div>
        )}

        {results.map(inc => (
          <div key={inc.id} className="card" style={{ marginBottom: '1rem' }}>
            <div className="card-header" style={{ marginBottom: '0.5rem' }}>
              <div className="flex-row gap-sm">
                <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{inc.target_id}</span>
                <span className="badge badge-healthy">{inc.category || 'unknown'}</span>
                <span className="badge badge-info">Score: {((inc.score || 0) * 100).toFixed(1)}%</span>
              </div>
              <span className="badge badge-healthy">{inc.status}</span>
            </div>

            {inc.root_cause && (
              <div style={{ marginBottom: '0.75rem' }}>
                <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                  <HelpCircle size={14} /> Learned Root Cause:
                </div>
                <p style={{ fontSize: '0.875rem' }}>{inc.root_cause}</p>
              </div>
            )}

            {inc.proposed_fix && (
              <div>
                <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                  <Terminal size={14} /> Successful Fix Command:
                </div>
                <div className="code-block">{inc.proposed_fix}</div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
