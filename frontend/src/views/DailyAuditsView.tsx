import React, { useState, useMemo } from 'react';
import { 
  Calendar, 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  Layers, 
  Play, 
  Clock, 
  EyeOff, 
  Terminal, 
  CheckSquare, 
  Square, 
  RefreshCw, 
  Filter, 
  HelpCircle,
  ShieldCheck,
  Bot
} from 'lucide-react';
import { useDailyAudits } from '../hooks/useDailyAudits';
import { ActionableAuditItem, StackAuditItem } from '../types/audit';

export const DailyAuditsView: React.FC = () => {
  const {
    reports,
    loading,
    error,
    selectedDate,
    setSelectedDate,
    selectedReport,
    actionInProgress,
    refresh,
    triggerSingleAction,
    triggerBulkAction
  } = useDailyAudits(30);

  const [selectedIncidentIds, setSelectedIncidentIds] = useState<string[]>([]);
  const [stackStatusFilter, setStackStatusFilter] = useState<'all' | 'warning' | 'healthy'>('all');
  const [searchStackQuery, setSearchStackQuery] = useState<string>('');

  const actionableItems = selectedReport?.actionable_items || [];

  // Toggle selection for an incident
  const toggleSelectIncident = (id: string) => {
    setSelectedIncidentIds(prev => 
      prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id]
    );
  };

  // Toggle select all actionable items for this day
  const toggleSelectAll = () => {
    const actionableIds = actionableItems.filter(i => i.can_action).map(i => i.incident_id);
    if (selectedIncidentIds.length === actionableIds.length && actionableIds.length > 0) {
      setSelectedIncidentIds([]);
    } else {
      setSelectedIncidentIds(actionableIds);
    }
  };

  // Handle bulk action execution
  const handleBulkAction = async (action: 'fix' | 'defer' | 'ignore' | 'dismiss') => {
    if (selectedIncidentIds.length === 0) return;
    const ok = await triggerBulkAction(action, selectedIncidentIds);
    if (ok) {
      setSelectedIncidentIds([]);
    }
  };

  // Filtered stacks
  const filteredStacks = useMemo(() => {
    if (!selectedReport) return [];
    return (selectedReport.stack_audits || []).filter(stack => {
      const matchesSearch = !searchStackQuery || 
        stack.stack_name.toLowerCase().includes(searchStackQuery.toLowerCase()) ||
        stack.summary.toLowerCase().includes(searchStackQuery.toLowerCase());
      
      if (!matchesSearch) return false;

      const isWarning = stack.status.toUpperCase() === 'WARNING' || 
        stack.status.toUpperCase() === 'ACTION_REQUIRED' || 
        stack.status.toUpperCase() === 'ERROR';

      if (stackStatusFilter === 'warning') return isWarning;
      if (stackStatusFilter === 'healthy') return !isWarning;
      return true;
    });
  }, [selectedReport, stackStatusFilter, searchStackQuery]);

  return (
    <div style={{ maxWidth: '100%', boxSizing: 'border-box' }}>
      {/* Top Header Card */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header" style={{ marginBottom: '0.75rem' }}>
          <div>
            <div className="flex-row flex-wrap gap-sm">
              <Calendar size={22} className="text-emerald" />
              <h2 style={{ fontSize: '1.25rem', fontWeight: 800 }}>30-Day Daily SRE Audits</h2>
              <span className="badge badge-healthy">{reports.length} Days Recorded</span>
            </div>
            <p className="text-secondary" style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>
              Historical autonomous inspection audits across homelab stacks with actionable remediation controls.
            </p>
          </div>

          <button
            onClick={refresh}
            disabled={loading || actionInProgress}
            className="btn btn-secondary btn-sm"
            title="Refresh daily audits"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>

        {/* 30-Day Timeline Selector Bar */}
        {reports.length > 0 && (
          <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1rem' }}>
            <div className="flex-row flex-wrap gap-xs" style={{ alignItems: 'center', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Select Audit Date:
              </span>
            </div>
            <div 
              style={{ 
                display: 'flex', 
                gap: '0.4rem', 
                overflowX: 'auto', 
                paddingBottom: '0.5rem',
                maxWidth: '100%',
                boxSizing: 'border-box'
              }}
            >
              {reports.map(report => {
                const isSelected = report.date === (selectedReport?.date || selectedDate);
                const hasOutages = report.outages_count > 0;
                const hasWarnings = report.warning_count > 0;
                const actionableCount = report.actionable_items?.length || 0;

                return (
                  <button
                    key={report.date}
                    onClick={() => {
                      setSelectedDate(report.date);
                      setSelectedIncidentIds([]);
                    }}
                    className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      padding: '0.4rem 0.65rem',
                      minWidth: '78px',
                      borderRadius: 'var(--radius-md)',
                      border: isSelected ? '2px solid var(--accent-emerald)' : '1px solid var(--border-subtle)',
                      background: isSelected ? 'var(--accent-emerald-subtle)' : 'var(--bg-surface)',
                      color: isSelected ? 'var(--accent-emerald)' : 'var(--text-secondary)'
                    }}
                  >
                    <span style={{ fontSize: '0.75rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                      {report.date.slice(5)}
                    </span>
                    <div className="flex-row gap-xs" style={{ marginTop: '0.2rem' }}>
                      {hasOutages ? (
                        <span className="pulsing-dot" style={{ background: 'var(--status-danger)', width: 6, height: 6 }} />
                      ) : hasWarnings ? (
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--status-warning)' }} />
                      ) : (
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--status-healthy)' }} />
                      )}
                      {actionableCount > 0 && (
                        <span style={{ fontSize: '0.65rem', fontWeight: 800, color: 'var(--status-warning)' }}>
                          {actionableCount}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {loading && reports.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
          <RefreshCw size={28} className="animate-spin text-emerald" style={{ margin: '0 auto 1rem' }} />
          <div style={{ fontWeight: 600 }}>Loading 30-day daily SRE audit timeline...</div>
        </div>
      )}

      {error && (
        <div className="card" style={{ borderColor: 'var(--status-danger)', padding: '1.5rem', marginBottom: '1.5rem' }}>
          <div className="flex-row gap-sm" style={{ color: 'var(--status-danger)', fontWeight: 700 }}>
            <AlertTriangle size={18} /> Error Loading Audits
          </div>
          <p style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>{error}</p>
        </div>
      )}

      {selectedReport && (
        <>
          {/* Day Metrics Scorecard */}
          <div className="grid-cols-4" style={{ marginBottom: '1.5rem' }}>
            <div className="stat-card">
              <div className="stat-icon">
                <Layers size={22} />
              </div>
              <div>
                <div className="stat-value">{selectedReport.total_stacks}</div>
                <div className="stat-label">Stacks Inspected</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'var(--accent-emerald-subtle)', color: 'var(--status-healthy)' }}>
                <CheckCircle2 size={22} />
              </div>
              <div>
                <div className="stat-value" style={{ color: 'var(--status-healthy)' }}>
                  {selectedReport.healthy_count}
                </div>
                <div className="stat-label">Clean & Healthy</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: 'var(--status-warning)' }}>
                <AlertTriangle size={22} />
              </div>
              <div>
                <div className="stat-value" style={{ color: selectedReport.warning_count > 0 ? 'var(--status-warning)' : 'inherit' }}>
                  {selectedReport.warning_count}
                </div>
                <div className="stat-label">Warnings / Degraded</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: selectedReport.outages_count > 0 ? 'rgba(239, 68, 68, 0.15)' : 'var(--bg-surface)', color: selectedReport.outages_count > 0 ? 'var(--status-danger)' : 'var(--text-muted)' }}>
                <XCircle size={22} />
              </div>
              <div>
                <div className="stat-value" style={{ color: selectedReport.outages_count > 0 ? 'var(--status-danger)' : 'inherit' }}>
                  {selectedReport.outages_count}
                </div>
                <div className="stat-label">Outages / Errors</div>
              </div>
            </div>
          </div>

          {/* Actionable Items Section (Prominent) */}
          <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-emerald)' }}>
            <div className="card-header">
              <div className="flex-row flex-wrap gap-sm">
                <Bot size={20} className="text-emerald" />
                <h3 style={{ fontSize: '1.15rem', fontWeight: 800 }}>
                  Actionable Items ({actionableItems.length})
                </h3>
                <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                  Audit Date: {selectedReport.date}
                </span>
              </div>

              {actionableItems.length > 0 && (
                <button
                  onClick={toggleSelectAll}
                  className="btn btn-secondary btn-sm"
                >
                  {selectedIncidentIds.length === actionableItems.filter(i => i.can_action).length && actionableItems.filter(i => i.can_action).length > 0 ? (
                    <><CheckSquare size={14} /> Deselect All</>
                  ) : (
                    <><Square size={14} /> Select All Actionable</>
                  )}
                </button>
              )}
            </div>

            {/* Bulk Action Controls Toolbar */}
            {selectedIncidentIds.length > 0 && (
              <div 
                className="card" 
                style={{ 
                  background: 'var(--accent-emerald-subtle)', 
                  borderColor: 'var(--accent-emerald)', 
                  marginBottom: '1rem',
                  padding: '0.75rem 1rem'
                }}
              >
                <div className="flex-row flex-wrap gap-md" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                  <div className="flex-row gap-sm">
                    <span style={{ fontWeight: 800, color: 'var(--accent-emerald)', fontSize: '0.9rem' }}>
                      {selectedIncidentIds.length} item(s) selected
                    </span>
                  </div>

                  <div className="flex-row flex-wrap gap-xs">
                    <button
                      onClick={() => handleBulkAction('fix')}
                      disabled={actionInProgress}
                      className="btn btn-primary btn-sm"
                      style={{ background: 'var(--accent-emerald)' }}
                    >
                      <Play size={14} /> Fix Selected
                    </button>
                    <button
                      onClick={() => handleBulkAction('defer')}
                      disabled={actionInProgress}
                      className="btn btn-secondary btn-sm"
                    >
                      <Clock size={14} /> Defer Selected (24h)
                    </button>
                    <button
                      onClick={() => handleBulkAction('ignore')}
                      disabled={actionInProgress}
                      className="btn btn-secondary btn-sm"
                    >
                      <EyeOff size={14} /> Ignore Selected
                    </button>
                    <button
                      onClick={() => handleBulkAction('dismiss')}
                      disabled={actionInProgress}
                      className="btn btn-secondary btn-sm"
                    >
                      Dismiss Selected
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Actionable Items Cards */}
            {actionableItems.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
                <ShieldCheck size={36} color="var(--status-healthy)" style={{ margin: '0 auto 0.5rem' }} />
                <div style={{ fontWeight: 700, fontSize: '1rem' }}>No Actionable Remediation Items</div>
                <p className="text-secondary" style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>
                  All inspected stacks for {selectedReport.date} passed cleanly or are in normal operating parameters.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                {actionableItems.map(item => {
                  const isChecked = selectedIncidentIds.includes(item.incident_id);

                  return (
                    <div 
                      key={item.incident_id}
                      className="card"
                      style={{
                        padding: '1rem',
                        background: isChecked ? 'var(--accent-emerald-subtle)' : 'var(--bg-surface)',
                        borderColor: isChecked ? 'var(--accent-emerald)' : 'var(--border-subtle)',
                        borderLeft: `4px solid ${item.can_action ? 'var(--status-warning)' : 'var(--border-muted)'}`
                      }}
                    >
                      <div className="flex-row flex-wrap gap-md" style={{ justifyContent: 'space-between', marginBottom: '0.6rem' }}>
                        <div className="flex-row flex-wrap gap-sm">
                          {item.can_action && (
                            <button
                              onClick={() => toggleSelectIncident(item.incident_id)}
                              style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 0 }}
                              title={isChecked ? 'Deselect item' : 'Select item for bulk remediation'}
                            >
                              {isChecked ? (
                                <CheckSquare size={18} color="var(--accent-emerald)" />
                              ) : (
                                <Square size={18} color="var(--text-muted)" />
                              )}
                            </button>
                          )}
                          <span style={{ fontWeight: 800, fontFamily: 'var(--font-mono)', fontSize: '1rem' }}>
                            {item.target_id}
                          </span>
                          <span className="badge badge-info">{item.stack_name}</span>
                          <span className="badge badge-healthy">{item.category}</span>
                          <span className={`badge ${item.can_action ? 'badge-warning' : 'badge-healthy'}`}>
                            {item.status}
                          </span>
                        </div>

                        <div className="text-muted" style={{ fontSize: '0.75rem' }}>
                          {item.created_at ? new Date(item.created_at).toLocaleTimeString() : ''}
                        </div>
                      </div>

                      {/* Root Cause */}
                      {item.root_cause && (
                        <div style={{ marginBottom: '0.6rem' }}>
                          <div className="flex-row gap-xs" style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.2rem' }}>
                            <HelpCircle size={13} /> ROOT CAUSE DIAGNOSIS:
                          </div>
                          <p style={{ fontSize: '0.875rem', color: 'var(--text-primary)', lineHeight: 1.4 }}>
                            {item.root_cause}
                          </p>
                        </div>
                      )}

                      {/* Proposed Fix */}
                      {item.proposed_fix && (
                        <div style={{ marginBottom: '0.75rem', maxWidth: '100%', boxSizing: 'border-box' }}>
                          <div className="flex-row gap-xs" style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.2rem' }}>
                            <Terminal size={13} /> PROPOSED REMEDIATION:
                          </div>
                          <div className="code-block" style={{ fontSize: '0.8rem', padding: '0.5rem 0.75rem' }}>
                            {item.proposed_fix}
                          </div>
                        </div>
                      )}

                      {/* Individual Action Buttons */}
                      {item.can_action && (
                        <div className="flex-row flex-wrap gap-xs" style={{ justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                          <button
                            onClick={() => triggerSingleAction(item.incident_id, 'fix')}
                            disabled={actionInProgress}
                            className="btn btn-primary btn-sm"
                            style={{ background: 'var(--accent-emerald)' }}
                          >
                            <Play size={14} /> Apply Fix Now
                          </button>
                          <button
                            onClick={() => triggerSingleAction(item.incident_id, 'defer')}
                            disabled={actionInProgress}
                            className="btn btn-secondary btn-sm"
                          >
                            <Clock size={14} /> Defer 24h
                          </button>
                          <button
                            onClick={() => triggerSingleAction(item.incident_id, 'ignore')}
                            disabled={actionInProgress}
                            className="btn btn-secondary btn-sm"
                          >
                            <EyeOff size={14} /> Ignore Target
                          </button>
                          <button
                            onClick={() => triggerSingleAction(item.incident_id, 'dismiss')}
                            disabled={actionInProgress}
                            className="btn btn-secondary btn-sm"
                          >
                            Dismiss
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Stacks Audit Breakdown for Day */}
          <div className="card">
            <div className="card-header">
              <div className="flex-row flex-wrap gap-sm">
                <Layers size={18} className="text-emerald" />
                <h3 style={{ fontSize: '1.15rem', fontWeight: 800 }}>
                  Inspected Stacks Breakdown ({filteredStacks.length})
                </h3>
              </div>

              {/* Status Filters */}
              <div className="flex-row flex-wrap gap-xs">
                <button
                  onClick={() => setStackStatusFilter('all')}
                  className={`btn btn-sm ${stackStatusFilter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
                  style={stackStatusFilter === 'all' ? { background: 'var(--accent-emerald)' } : {}}
                >
                  All ({selectedReport.stack_audits.length})
                </button>
                <button
                  onClick={() => setStackStatusFilter('warning')}
                  className={`btn btn-sm ${stackStatusFilter === 'warning' ? 'btn-primary' : 'btn-secondary'}`}
                >
                  Warnings ({selectedReport.warning_count + selectedReport.outages_count})
                </button>
                <button
                  onClick={() => setStackStatusFilter('healthy')}
                  className={`btn btn-sm ${stackStatusFilter === 'healthy' ? 'btn-primary' : 'btn-secondary'}`}
                >
                  Clean ({selectedReport.healthy_count})
                </button>
              </div>
            </div>

            {/* Stack List Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '0.85rem' }}>
              {filteredStacks.map(stack => {
                const isHealthy = stack.status.toUpperCase() === 'HEALTHY' || stack.status.toUpperCase() === 'CLEAN';

                return (
                  <div
                    key={stack.id}
                    className="card"
                    style={{
                      padding: '0.85rem 1rem',
                      background: 'var(--bg-surface)',
                      borderLeft: `4px solid ${isHealthy ? 'var(--status-healthy)' : 'var(--status-warning)'}`
                    }}
                  >
                    <div className="flex-row flex-wrap gap-sm" style={{ justifyContent: 'space-between', marginBottom: '0.4rem' }}>
                      <span style={{ fontWeight: 800, fontFamily: 'var(--font-mono)', fontSize: '0.95rem' }}>
                        {stack.stack_name}
                      </span>
                      <span className={`badge ${isHealthy ? 'badge-healthy' : 'badge-warning'}`}>
                        {stack.status}
                      </span>
                    </div>

                    <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', lineHeight: 1.4, marginBottom: '0.4rem' }}>
                      {stack.summary}
                    </p>

                    <div className="flex-row flex-wrap gap-md text-muted" style={{ fontSize: '0.75rem' }}>
                      <span>Containers: {stack.containers_checked}</span>
                      <span>Errors: {stack.error_count}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
