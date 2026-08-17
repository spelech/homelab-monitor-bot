import React from 'react';
import { CanaryResults } from '../types/upgrade';
import { CheckCircle2, XCircle, AlertCircle, RefreshCw } from 'lucide-react';

interface CanaryAuditCardProps {
  canary: CanaryResults | null;
  loading: boolean;
  onRunAudit: () => void;
}

export const CanaryAuditCard: React.FC<CanaryAuditCardProps> = ({ canary, loading, onRunAudit }) => {
  return (
    <div className="card" style={{ marginBottom: '1.5rem' }}>
      <div className="card-header">
        <div>
          <div className="card-title">
            <span style={{ fontWeight: 800 }}>4-Phase Canary Health & Routing Audit</span>
            {canary && (
              canary.overall_status === 'PASS' ? (
                <span className="badge badge-healthy">ALL CHECKS PASSED</span>
              ) : (
                <span className="badge badge-danger">{canary.failures_count || 1} CHECK(S) FAILED</span>
              )
            )}
          </div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>
            Automated verification: Crashloop check, container healthcheck, Caddyfile validator, and HTTPS endpoint probe.
          </div>
        </div>

        <button
          onClick={onRunAudit}
          disabled={loading}
          className="btn btn-secondary btn-sm"
        >
          <RefreshCw size={14} className={loading ? 'spinning' : ''} />
          <span>{loading ? 'Auditing...' : 'Run Audit Now'}</span>
        </button>
      </div>

      {canary && canary.checks ? (
        <div className="grid-cols-2" style={{ gap: '0.75rem' }}>
          {canary.checks.map((check, idx) => {
            const isPass = check.status === 'PASS';
            return (
              <div
                key={idx}
                className="card"
                style={{
                  padding: '0.85rem 1rem',
                  borderLeft: `4px solid ${isPass ? 'var(--status-healthy)' : 'var(--status-danger)'}`,
                  background: 'var(--bg-surface)'
                }}
              >
                <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                  <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>{check.name}</span>
                  {isPass ? (
                    <span className="flex-row gap-sm text-emerald" style={{ fontSize: '0.8rem', fontWeight: 700 }}>
                      <CheckCircle2 size={15} /> PASS
                    </span>
                  ) : (
                    <span className="flex-row gap-sm" style={{ color: 'var(--status-danger)', fontSize: '0.8rem', fontWeight: 700 }}>
                      <XCircle size={15} /> FAIL
                    </span>
                  )}
                </div>
                <div className="text-secondary" style={{ fontSize: '0.8rem' }}>
                  {check.detail}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-muted" style={{ textAlign: 'center', padding: '1.5rem 0', fontSize: '0.85rem' }}>
          Click "Run Audit Now" to perform an immediate 4-phase canary inspection across all stacks.
        </div>
      )}
    </div>
  );
};
