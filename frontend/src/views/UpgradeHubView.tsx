import React, { useState } from 'react';
import { StackInfo, UpgradeJob, UpgradeRunHistory, CanaryResults } from '../types/upgrade';
import { CanaryAuditCard } from '../components/CanaryAuditCard';
import { TerminalView } from '../components/TerminalView';
import { ArrowUpCircle, Layers, CheckSquare, Square, StopCircle, RefreshCw, Bot, AlertTriangle } from 'lucide-react';

interface UpgradeHubViewProps {
  stacks: StackInfo[];
  liveJob: UpgradeJob | null;
  runs: UpgradeRunHistory[];
  canaryResult: CanaryResults | null;
  loading: boolean;
  canaryLoading: boolean;
  onTriggerUpgrade: (targets?: string[]) => void;
  onCancelUpgrade: () => void;
  onRunCanaryAudit: () => void;
}

export const UpgradeHubView: React.FC<UpgradeHubViewProps> = ({
  stacks,
  liveJob,
  runs,
  canaryResult,
  loading,
  canaryLoading,
  onTriggerUpgrade,
  onCancelUpgrade,
  onRunCanaryAudit
}) => {
  const [selectedStacks, setSelectedStacks] = useState<string[]>([]);
  const [activeRunLogModal, setActiveRunLogModal] = useState<UpgradeRunHistory | null>(null);

  const toggleStack = (name: string) => {
    setSelectedStacks(prev =>
      prev.includes(name) ? prev.filter(s => s !== name) : [...prev, name]
    );
  };

  const selectAll = () => {
    if (selectedStacks.length === stacks.length) {
      setSelectedStacks([]);
    } else {
      setSelectedStacks(stacks.map(s => s.name));
    }
  };

  const isRunning = liveJob?.status === 'RUNNING';

  return (
    <div>
      {/* 4-Phase Canary Health Card */}
      <CanaryAuditCard
        canary={canaryResult || liveJob?.canary_results || null}
        loading={canaryLoading}
        onRunAudit={onRunCanaryAudit}
      />

      {/* Upgrade Controls & Stack Picker */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header">
          <div className="card-title">
            <ArrowUpCircle size={20} className="text-emerald" />
            <span style={{ fontWeight: 800 }}>Autonomous Container Upgrades</span>
          </div>

          <div className="flex-row gap-sm">
            {isRunning ? (
              <button
                onClick={onCancelUpgrade}
                className="btn btn-danger btn-sm"
              >
                <StopCircle size={15} /> Cancel Running Upgrade
              </button>
            ) : (
              <>
                <button
                  onClick={() => onTriggerUpgrade(['all'])}
                  disabled={loading}
                  className="btn btn-primary btn-sm"
                  style={{ background: 'var(--accent-emerald)' }}
                >
                  <ArrowUpCircle size={15} /> Upgrade All Infrastructure
                </button>

                {selectedStacks.length > 0 && (
                  <button
                    onClick={() => onTriggerUpgrade(selectedStacks)}
                    disabled={loading}
                    className="btn btn-secondary btn-sm"
                  >
                    Upgrade Selected ({selectedStacks.length})
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {/* Stack checkboxes */}
        <div style={{ marginBottom: '1rem' }}>
          <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span className="text-secondary" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
              Available Stacks ({stacks.length}):
            </span>
            <button
              onClick={selectAll}
              className="btn btn-secondary btn-sm"
              style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
            >
              {selectedStacks.length === stacks.length ? 'Deselect All' : 'Select All'}
            </button>
          </div>

          <div className="grid-cols-4" style={{ gap: '0.5rem' }}>
            {stacks.map(s => {
              const isChecked = selectedStacks.includes(s.name);
              return (
                <div
                  key={s.name}
                  onClick={() => !isRunning && toggleStack(s.name)}
                  className="card"
                  style={{
                    padding: '0.6rem 0.85rem',
                    cursor: isRunning ? 'not-allowed' : 'pointer',
                    background: isChecked ? 'var(--accent-emerald-subtle)' : 'var(--bg-surface)',
                    borderColor: isChecked ? 'var(--accent-emerald)' : 'var(--border-subtle)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between'
                  }}
                >
                  <div className="flex-row gap-sm">
                    {isChecked ? <CheckSquare size={16} color="var(--accent-emerald)" /> : <Square size={16} color="var(--text-muted)" />}
                    <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{s.name}</span>
                  </div>
                  <span className="badge badge-info" style={{ fontSize: '0.7rem' }}>
                    {s.services_count} svcs
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Live Terminal Streaming View */}
        <div>
          <div className="text-secondary" style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>
            Live Execution Logs:
          </div>
          <TerminalView
            logs={liveJob?.logs || []}
            currentStep={liveJob?.current_step}
            status={liveJob?.status}
          />
        </div>
      </div>

      {/* Upgrade History Log */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">
            <Layers size={18} />
            <span>Upgrade Execution History</span>
          </div>
        </div>

        {runs.length === 0 ? (
          <div className="text-muted" style={{ textAlign: 'center', padding: '1.5rem 0', fontSize: '0.85rem' }}>
            No previous upgrade runs recorded in database.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.6rem 0.75rem' }}>RUN ID</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>STATUS</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>TARGETS</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>STARTED</th>
                  <th style={{ padding: '0.6rem 0.75rem' }}>CANARY RESULT</th>
                  <th style={{ padding: '0.6rem 0.75rem', textAlign: 'right' }}>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} style={{ borderBottom: '1px solid var(--border-muted)' }}>
                    <td className="font-mono" style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem' }}>
                      {r.id.substring(0, 8)}...
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      <span className={`badge ${r.status === 'SUCCESS' ? 'badge-healthy' : r.status === 'RUNNING' ? 'badge-info' : 'badge-warning'}`}>
                        {r.status}
                      </span>
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {Array.isArray(r.targets) ? r.targets.slice(0, 3).join(', ') + (r.targets.length > 3 ? ` +${r.targets.length - 3}` : '') : r.targets}
                      </span>
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {r.started_at ? new Date(r.started_at).toLocaleString() : '-'}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      {r.canary_results?.overall_status ? (
                        <span className={`badge ${r.canary_results.overall_status === 'PASS' ? 'badge-healthy' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>
                          CANARY: {r.canary_results.overall_status}
                        </span>
                      ) : '-'}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'right' }}>
                      <button
                        onClick={async () => {
                          const res = await fetch(`/api/upgrades/runs/${r.id}`);
                          if (res.ok) {
                            const data = await res.json();
                            setActiveRunLogModal(data);
                          }
                        }}
                        className="btn btn-secondary btn-sm"
                      >
                        View Logs
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Historical Log Viewer Modal */}
      {activeRunLogModal && (
        <div className="modal-backdrop" onClick={() => setActiveRunLogModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span style={{ fontWeight: 800 }}>Upgrade Run Logs ({activeRunLogModal.id})</span>
              <button onClick={() => setActiveRunLogModal(null)} className="btn btn-secondary btn-sm">Close</button>
            </div>
            <div className="modal-body">
              <div className="code-block" style={{ maxHeight: '450px', overflowY: 'auto' }}>
                {activeRunLogModal.logs || 'No log output captured.'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
