import React from 'react';
import { useUsage } from '../hooks/useUsage';
import { DollarSign, Cpu, Zap, Activity, RefreshCw } from 'lucide-react';

export const SpendTrackerView: React.FC = () => {
  const { summary, loading, refresh } = useUsage();

  return (
    <div>
      {/* Header */}
      <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '1.25rem' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>OpenCode & AI Spend Tracker</h2>
          <div className="text-muted" style={{ fontSize: '0.85rem' }}>
            Real-time token analytics and dollar cost estimation for SRE investigations
          </div>
        </div>

        <button onClick={refresh} className="btn btn-secondary btn-sm" disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spinning' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="grid-cols-4" style={{ marginBottom: '1.5rem' }}>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: 'var(--accent-emerald)' }}>
            <DollarSign size={22} />
          </div>
          <div>
            <div className="stat-value text-emerald">
              ${summary?.total_cost_usd?.toFixed(4) || '0.0000'}
            </div>
            <div className="stat-label">Estimated Total Spend</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(6, 182, 212, 0.15)', color: 'var(--status-info)' }}>
            <Cpu size={22} />
          </div>
          <div>
            <div className="stat-value">
              {summary?.total_tokens?.toLocaleString() || '0'}
            </div>
            <div className="stat-label">Total Tokens Consumed</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(168, 85, 247, 0.15)', color: 'var(--status-purple)' }}>
            <Zap size={22} />
          </div>
          <div>
            <div className="stat-value">
              {summary?.total_calls || 0}
            </div>
            <div className="stat-label">AI SRE Invocations</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: 'var(--status-warning)' }}>
            <Activity size={22} />
          </div>
          <div>
            <div className="stat-value" style={{ fontSize: '1.1rem' }}>
              {summary?.litellm_status === 'healthy' ? (
                <span className="text-emerald">Online (:8448)</span>
              ) : (
                <span className="text-muted">Local Direct</span>
              )}
            </div>
            <div className="stat-label">LiteLLM Gateway Status</div>
          </div>
        </div>
      </div>

      {/* Model Breakdown */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-title" style={{ marginBottom: '1rem' }}>
          <span>Model Usage Distribution</span>
        </div>

        <div className="grid-cols-3" style={{ gap: '0.75rem' }}>
          {summary?.model_counts && Object.keys(summary.model_counts).length > 0 ? (
            Object.entries(summary.model_counts).map(([model, count]) => (
              <div key={model} className="card" style={{ padding: '0.75rem 1rem', background: 'var(--bg-surface)' }}>
                <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                  <span className="font-mono" style={{ fontSize: '0.85rem', fontWeight: 600 }}>{model}</span>
                  <span className="badge badge-healthy">{count} calls</span>
                </div>
                <div className="text-muted" style={{ fontSize: '0.75rem' }}>
                  Default executor: OpenCode / Gemini
                </div>
              </div>
            ))
          ) : (
            <div className="text-muted" style={{ fontSize: '0.85rem' }}>No AI calls recorded yet.</div>
          )}
        </div>
      </div>

      {/* Recent Investigation Invocations */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: '1rem' }}>
          <span>Recent AI Investigation Costs</span>
        </div>

        {!summary?.recent_logs || summary.recent_logs.length === 0 ? (
          <div className="text-muted" style={{ textAlign: 'center', padding: '1.5rem 0', fontSize: '0.85rem' }}>
            No investigation logs found in database.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.6rem 0.75rem' }}>TIMESTAMP</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>EXECUTOR</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>MODEL</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>TOKENS (IN/OUT)</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>TOTAL TOKENS</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>EST. COST ($)</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {summary.recent_logs.map(log => (
                  <tr key={log.id} style={{ borderBottom: '1px solid var(--border-muted)' }}>
                    <td style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {log.created_at ? new Date(log.created_at).toLocaleTimeString() : '-'}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      <span className="badge badge-purple" style={{ fontSize: '0.7rem' }}>{log.executor}</span>
                    </td>
                    <td className="font-mono" style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem' }}>
                      {log.model_id || 'unknown'}
                    </td>
                    <td className="font-mono" style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem' }}>
                      {log.prompt_tokens} / {log.completion_tokens}
                    </td>
                    <td className="font-mono" style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem', fontWeight: 600 }}>
                      {log.total_tokens}
                    </td>
                    <td className="font-mono text-emerald" style={{ padding: '0.6rem 0.75rem', fontWeight: 700 }}>
                      ${log.cost_usd}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      <span className={`badge ${log.status === 'SUCCESS' ? 'badge-healthy' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>
                        {log.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
