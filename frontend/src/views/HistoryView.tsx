import React, { useState } from 'react';
import { Incident } from '../types/incident';
import { IncidentModal } from '../components/IncidentModal';
import { History, Filter } from 'lucide-react';

interface HistoryViewProps {
  history: Incident[];
}

export const HistoryView: React.FC<HistoryViewProps> = ({ history }) => {
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);

  const filtered = history.filter(inc => {
    if (filterCategory !== 'all' && inc.category !== filterCategory) return false;
    if (filterStatus !== 'all' && inc.status !== filterStatus) return false;
    return true;
  });

  const categories = Array.from(new Set(history.map(i => i.category || 'unknown')));
  const statuses = Array.from(new Set(history.map(i => i.status)));

  return (
    <div>
      <div className="card-header" style={{ marginBottom: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>Incident History Archive</h2>
          <div className="text-muted" style={{ fontSize: '0.85rem' }}>
            Resolved, failed, and deferred incident logs
          </div>
        </div>

        {/* Filter Controls */}
        <div className="flex-row gap-sm">
          <select
            className="input-text"
            style={{ width: 'auto', padding: '0.35rem 0.65rem', fontSize: '0.8rem' }}
            value={filterCategory}
            onChange={e => setFilterCategory(e.target.value)}
          >
            <option value="all">All Categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          <select
            className="input-text"
            style={{ width: 'auto', padding: '0.35rem 0.65rem', fontSize: '0.8rem' }}
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
          >
            <option value="all">All Statuses</option>
            {statuses.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem 0' }}>
          <div className="text-muted" style={{ fontSize: '0.9rem' }}>No historical incidents match the selected filter.</div>
        </div>
      ) : (
        <div className="card" style={{ padding: '0.5rem' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '0.6rem 0.75rem' }}>TARGET</th>
                <th style={{ padding: '0.6rem 0.75rem' }}>STATUS</th>
                <th style={{ padding: '0.6rem 0.75rem' }}>CATEGORY</th>
                <th style={{ padding: '0.6rem 0.75rem' }}>ROOT CAUSE</th>
                <th style={{ padding: '0.6rem 0.75rem' }}>COMPLETED</th>
                <th style={{ padding: '0.6rem 0.75rem', textAlign: 'right' }}>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(inc => (
                <tr key={inc.id} style={{ borderBottom: '1px solid var(--border-muted)' }}>
                  <td className="font-mono" style={{ padding: '0.6rem 0.75rem', fontWeight: 700 }}>
                    {inc.target_id}
                  </td>
                  <td style={{ padding: '0.6rem 0.75rem' }}>
                    <span className={`badge ${inc.status === 'RESOLVED' ? 'badge-healthy' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>
                      {inc.status}
                    </span>
                  </td>
                  <td style={{ padding: '0.6rem 0.75rem' }}>
                    <span className="badge badge-info" style={{ fontSize: '0.7rem' }}>{inc.category || 'unknown'}</span>
                  </td>
                  <td style={{ padding: '0.6rem 0.75rem', maxWidth: '300px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    <span className="text-secondary" style={{ fontSize: '0.8rem' }}>{inc.root_cause || '-'}</span>
                  </td>
                  <td style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {inc.completed_at ? new Date(inc.completed_at).toLocaleString() : '-'}
                  </td>
                  <td style={{ padding: '0.6rem 0.75rem', textAlign: 'right' }}>
                    <button
                      onClick={() => setSelectedIncident(inc)}
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                    >
                      Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <IncidentModal
        incident={selectedIncident}
        onClose={() => setSelectedIncident(null)}
      />
    </div>
  );
};
