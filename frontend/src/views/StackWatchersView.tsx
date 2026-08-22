import React, { useState, useMemo } from 'react';
import {
  Layers,
  Server,
  Activity,
  ArrowUpCircle,
  RefreshCw,
  Bot,
  AlertTriangle,
  CheckCircle,
  CheckCircle2,
  Clock,
  Terminal,
  FileText,
  Search,
  ChevronDown,
  ChevronUp,
  X,
  Play,
  EyeOff,
  ShieldCheck,
  HelpCircle
} from 'lucide-react';
import {
  StackSummary,
  StackDetail,
  StackAuditResult,
  StackIncidentInfo
} from '../types/stack';
import { useStacks } from '../hooks/useStacks';

interface StackWatchersViewProps {
  onTriggerUpgrade?: (targets?: string[]) => void;
  onIncidentAction?: (id: string, action: 'fix' | 'defer' | 'ignore' | 'dismiss') => void;
}

export const StackWatchersView: React.FC<StackWatchersViewProps> = ({
  onTriggerUpgrade,
  onIncidentAction
}) => {
  const {
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
  } = useStacks();

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'healthy' | 'degraded' | 'updates' | 'incidents'>('all');
  const [expandedStacks, setExpandedStacks] = useState<Record<string, boolean>>({});
  const [selectedAuditResult, setSelectedAuditResult] = useState<StackAuditResult | null>(null);
  const [selectedStackDetail, setSelectedStackDetail] = useState<StackDetail | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<StackIncidentInfo | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);

  // Compute top metrics
  const totalStacks = stacks.length;
  const totalContainers = useMemo(() => {
    return stacks.reduce((sum, s) => sum + (s.total_containers || s.containers?.length || 0), 0);
  }, [stacks]);

  const runningContainers = useMemo(() => {
    return stacks.reduce((sum, s) => sum + (s.running_containers || 0), 0);
  }, [stacks]);

  const healthyContainers = useMemo(() => {
    return stacks.reduce((sum, s) => sum + (s.healthy_containers || 0), 0);
  }, [stacks]);

  const unhealthyContainers = useMemo(() => {
    return stacks.reduce((sum, s) => sum + (s.unhealthy_containers || 0), 0);
  }, [stacks]);

  const totalUpdatesAvailable = useMemo(() => {
    return stacks.reduce((sum, s) => sum + (s.updates_available_count || 0), 0);
  }, [stacks]);

  const totalActiveIncidents = useMemo(() => {
    return stacks.reduce((sum, s) => sum + (s.active_incidents_count || 0), 0);
  }, [stacks]);

  const cleanAuditStacksCount = useMemo(() => {
    return stacks.filter(s => {
      const lastStatus = s.last_audit?.status?.toUpperCase();
      return lastStatus === 'CLEAN' || lastStatus === 'HEALTHY';
    }).length;
  }, [stacks]);

  // Toggle stack accordion
  const toggleStackAccordion = (stackName: string) => {
    setExpandedStacks(prev => ({
      ...prev,
      [stackName]: !prev[stackName]
    }));
  };

  const expandAll = () => {
    const all: Record<string, boolean> = {};
    stacks.forEach(s => {
      all[s.name] = true;
    });
    setExpandedStacks(all);
  };

  const collapseAll = () => {
    setExpandedStacks({});
  };

  // Filter stacks
  const filteredStacks = useMemo(() => {
    return stacks.filter(s => {
      // Status filter
      if (statusFilter === 'healthy' && s.status !== 'healthy') return false;
      if (statusFilter === 'degraded' && s.status !== 'degraded' && s.status !== 'unhealthy') return false;
      if (statusFilter === 'updates' && (!s.updates_available_count || s.updates_available_count === 0)) return false;
      if (statusFilter === 'incidents' && (!s.active_incidents_count || s.active_incidents_count === 0)) return false;

      // Text query filter
      if (!searchQuery.trim()) return true;
      const query = searchQuery.toLowerCase();
      if (s.name.toLowerCase().includes(query)) return true;
      if (s.working_dir?.toLowerCase().includes(query)) return true;
      if (s.containers?.some(c => c.name.toLowerCase().includes(query) || c.image.toLowerCase().includes(query))) {
        return true;
      }
      return false;
    });
  }, [stacks, statusFilter, searchQuery]);

  // Handle single stack audit
  const handleAuditStack = async (stackName: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    const result = await auditStack(stackName);
    if (result) {
      setSelectedAuditResult(result);
    }
  };

  // Handle single stack update check
  const handleCheckUpdates = async (stackName: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    await checkStackUpdates(stackName);
  };

  // Handle single stack upgrade trigger
  const handleUpgradeStack = (stackName: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (onTriggerUpgrade) {
      onTriggerUpgrade([stackName]);
    } else {
      alert(`Autonomous upgrade triggered for stack '${stackName}'`);
    }
  };

  // Open stack detail modal
  const handleOpenStackDetail = async (stackName: string) => {
    setDetailLoading(true);
    const detail = await fetchStackDetail(stackName);
    setDetailLoading(false);
    if (detail) {
      setSelectedStackDetail(detail);
    }
  };

  // Helper for incident actions
  const handleIncidentActionClick = async (
    incidentId: string,
    action: 'fix' | 'defer' | 'ignore' | 'dismiss',
    e?: React.MouseEvent
  ) => {
    if (e) e.stopPropagation();
    if (onIncidentAction) {
      onIncidentAction(incidentId, action);
    } else {
      try {
        const res = await fetch(`/api/incidents/${incidentId}/action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action })
        });
        if (!res.ok) throw new Error(`Action failed with HTTP ${res.status}`);
      } catch (err: any) {
        alert(`Error executing ${action}: ${err.message}`);
      }
    }
    await fetchStacks();
    if (selectedStackDetail) {
      const updated = await fetchStackDetail(selectedStackDetail.name);
      if (updated) setSelectedStackDetail(updated);
    }
    if (selectedIncident && selectedIncident.id === incidentId) {
      setSelectedIncident(null);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case 'healthy':
        return <span className="badge badge-healthy">Healthy</span>;
      case 'degraded':
        return <span className="badge badge-warning">Degraded</span>;
      case 'unhealthy':
        return <span className="badge badge-danger">Unhealthy</span>;
      case 'stopped':
        return <span className="badge badge-danger">Stopped</span>;
      default:
        return <span className="badge badge-info">{status}</span>;
    }
  };

  const getAuditBadge = (status?: string) => {
    if (!status) return null;
    switch (status.toUpperCase()) {
      case 'CLEAN':
      case 'HEALTHY':
        return <span className="badge badge-healthy">SRE Clean</span>;
      case 'WARNING':
        return <span className="badge badge-warning">SRE Warning</span>;
      case 'ANOMALOUS':
      case 'ERROR':
        return <span className="badge badge-danger">SRE Anomalous</span>;
      default:
        return <span className="badge badge-info">SRE {status}</span>;
    }
  };

  return (
    <div>
      {/* Top Metrics Row */}
      <div className="grid-cols-4" style={{ gap: '1rem', marginBottom: '1.5rem' }}>
        {/* Total Stacks */}
        <div className="stat-card">
          <div className="stat-icon">
            <Layers size={22} />
          </div>
          <div>
            <div className="stat-value">{totalStacks}</div>
            <div className="stat-label">Total Docker Stacks</div>
          </div>
        </div>

        {/* Monitored Containers */}
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'var(--accent-emerald-subtle)', color: 'var(--accent-emerald)' }}>
            <Server size={22} />
          </div>
          <div>
            <div className="stat-value">
              {runningContainers} <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>/ {totalContainers}</span>
            </div>
            <div className="stat-label">Running Containers</div>
          </div>
        </div>

        {/* Container Health */}
        <div className="stat-card">
          <div
            className="stat-icon"
            style={{
              background: unhealthyContainers > 0 ? 'rgba(239, 68, 68, 0.15)' : 'var(--accent-emerald-subtle)',
              color: unhealthyContainers > 0 ? 'var(--status-danger)' : 'var(--status-healthy)'
            }}
          >
            <Activity size={22} />
          </div>
          <div>
            <div className="stat-value">
              <span style={{ color: 'var(--status-healthy)' }}>{healthyContainers}</span>
              {unhealthyContainers > 0 && (
                <span style={{ color: 'var(--status-danger)', fontSize: '1rem', marginLeft: '0.4rem' }}>
                  ({unhealthyContainers} degraded)
                </span>
              )}
            </div>
            <div className="stat-label">Container Health Status</div>
          </div>
        </div>

        {/* Updates & Incidents */}
        <div className="stat-card">
          <div
            className="stat-icon"
            style={{
              background: totalUpdatesAvailable > 0 ? 'rgba(245, 158, 11, 0.15)' : 'var(--accent-emerald-subtle)',
              color: totalUpdatesAvailable > 0 ? 'var(--status-warning)' : 'var(--accent-emerald)'
            }}
          >
            <ArrowUpCircle size={22} />
          </div>
          <div>
            <div className="stat-value">
              {totalUpdatesAvailable}
              {totalActiveIncidents > 0 && (
                <span style={{ color: 'var(--status-danger)', fontSize: '0.9rem', marginLeft: '0.4rem' }}>
                  ({totalActiveIncidents} alerts)
                </span>
              )}
            </div>
            <div className="stat-label">Image Updates Available</div>
          </div>
        </div>
      </div>

      {/* Action Header & Global SRE Trigger */}
      <div className="card" style={{ marginBottom: '1.25rem', padding: '1rem 1.25rem' }}>
        <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
            <Bot size={20} className="text-emerald" />
            <div>
              <span style={{ fontWeight: 800, fontSize: '1.1rem' }}>Stack SRE & Container Inventory</span>
              <div className="text-muted" style={{ fontSize: '0.8rem' }}>
                Automated Docker socket discovery, health monitoring, 12h registry image checks, and autonomous SRE log audits
              </div>
            </div>
          </div>

          <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
            <button
              onClick={() => auditAllStacks()}
              disabled={auditAllLoading}
              className="btn btn-primary btn-sm"
              style={{ background: 'var(--accent-emerald)' }}
              title="Trigger SRE AI log analysis across all discovered stacks"
            >
              <RefreshCw size={14} className={auditAllLoading ? 'animate-spin' : ''} />
              {auditAllLoading ? 'Auditing All Stacks...' : 'Audit All Stacks (AI SRE)'}
            </button>

            <button
              onClick={fetchStacks}
              className="btn btn-secondary btn-sm"
              title="Refresh stack inventory"
            >
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </div>

        {/* Filter / Search Bar */}
        <div className="flex-row" style={{ marginTop: '1rem', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div className="flex-row gap-sm" style={{ flex: 1, minWidth: '240px', maxWidth: '420px', position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              className="input-text"
              placeholder="Search stack name, container, or image..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ paddingLeft: '2.25rem', fontSize: '0.85rem' }}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                style={{ position: 'absolute', right: '0.5rem', top: '50%', transform: 'translateY(-50%)', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Filter Pills */}
          <div className="flex-row gap-sm" style={{ flexWrap: 'wrap' }}>
            <button
              onClick={() => setStatusFilter('all')}
              className={`btn btn-sm ${statusFilter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
              style={statusFilter === 'all' ? { background: 'var(--accent-emerald)' } : {}}
            >
              All ({stacks.length})
            </button>
            <button
              onClick={() => setStatusFilter('healthy')}
              className={`btn btn-sm ${statusFilter === 'healthy' ? 'btn-primary' : 'btn-secondary'}`}
            >
              Healthy ({stacks.filter(s => s.status === 'healthy').length})
            </button>
            <button
              onClick={() => setStatusFilter('degraded')}
              className={`btn btn-sm ${statusFilter === 'degraded' ? 'btn-primary' : 'btn-secondary'}`}
            >
              Degraded ({stacks.filter(s => s.status === 'degraded' || s.status === 'unhealthy').length})
            </button>
            <button
              onClick={() => setStatusFilter('updates')}
              className={`btn btn-sm ${statusFilter === 'updates' ? 'btn-primary' : 'btn-secondary'}`}
            >
              Updates ({stacks.filter(s => s.updates_available_count > 0).length})
            </button>
            <button
              onClick={() => setStatusFilter('incidents')}
              className={`btn btn-sm ${statusFilter === 'incidents' ? 'btn-primary' : 'btn-secondary'}`}
            >
              Incidents ({stacks.filter(s => s.active_incidents_count > 0).length})
            </button>

            <div style={{ marginLeft: '0.5rem', display: 'flex', gap: '0.25rem' }}>
              <button onClick={expandAll} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}>
                Expand All
              </button>
              <button onClick={collapseAll} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}>
                Collapse
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Loading state */}
      {loading && stacks.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
          <RefreshCw size={28} className="animate-spin text-emerald" style={{ margin: '0 auto 1rem' }} />
          <div style={{ fontWeight: 600 }}>Discovering Docker stacks from host daemon...</div>
        </div>
      )}

      {/* Empty Filter State */}
      {!loading && filteredStacks.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
          <div className="stat-icon" style={{ margin: '0 auto 1rem', width: 56, height: 56, borderRadius: '50%' }}>
            <Search size={28} />
          </div>
          <h3 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '0.5rem' }}>No Stacks Found</h3>
          <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
            No Docker stacks matched your search filter criteria.
          </p>
        </div>
      )}

      {/* Stack Accordion List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {filteredStacks.map(stack => {
          const isExpanded = expandedStacks[stack.name] ?? false;
          const isAuditing = auditingStacks[stack.name] ?? false;
          const isChecking = checkingUpdates[stack.name] ?? false;

          return (
            <div
              key={stack.name}
              className="card"
              style={{
                borderLeft: `4px solid ${
                  stack.status === 'healthy'
                    ? 'var(--status-healthy)'
                    : stack.status === 'degraded'
                    ? 'var(--status-warning)'
                    : 'var(--status-danger)'
                }`
              }}
            >
              {/* Stack Accordion Header */}
              <div
                className="card-header"
                onClick={() => toggleStackAccordion(stack.name)}
                style={{
                  cursor: 'pointer',
                  marginBottom: isExpanded ? '1rem' : '0',
                  userSelect: 'none'
                }}
              >
                <div className="flex-row gap-sm" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '1.15rem', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
                    {stack.name}
                  </span>

                  {getStatusBadge(stack.status)}

                  <span className="badge badge-info" style={{ fontSize: '0.75rem' }}>
                    {stack.running_containers} / {stack.total_containers} running
                  </span>

                  {stack.updates_available_count > 0 && (
                    <span className="badge badge-warning" style={{ fontSize: '0.75rem' }}>
                      <ArrowUpCircle size={12} /> {stack.updates_available_count} Updates Available
                    </span>
                  )}

                  {stack.active_incidents_count > 0 && (
                    <span className="badge badge-danger" style={{ fontSize: '0.75rem' }}>
                      <AlertTriangle size={12} /> {stack.active_incidents_count} Alerts
                    </span>
                  )}

                  {stack.last_audit && getAuditBadge(stack.last_audit.status)}
                </div>

                <div className="flex-row gap-sm" style={{ alignItems: 'center' }} onClick={e => e.stopPropagation()}>
                  {/* Action Buttons */}
                  <button
                    onClick={e => handleAuditStack(stack.name, e)}
                    disabled={isAuditing}
                    className="btn btn-secondary btn-sm"
                    title="Run AI SRE log error inspection on this stack"
                  >
                    <Bot size={14} className={isAuditing ? 'animate-spin' : ''} />
                    {isAuditing ? 'Auditing...' : 'Audit Logs (AI SRE)'}
                  </button>

                  <button
                    onClick={e => handleCheckUpdates(stack.name, e)}
                    disabled={isChecking}
                    className="btn btn-secondary btn-sm"
                    title="Check remote registry for fresh container images"
                  >
                    <RefreshCw size={14} className={isChecking ? 'animate-spin' : ''} />
                    {isChecking ? 'Checking...' : 'Check Updates'}
                  </button>

                  <button
                    onClick={e => handleUpgradeStack(stack.name, e)}
                    className="btn btn-primary btn-sm"
                    style={{ background: 'var(--accent-emerald)' }}
                    title="Trigger rolling restart & image pull for this stack"
                  >
                    <ArrowUpCircle size={14} /> Upgrade Stack
                  </button>

                  <button
                    onClick={() => toggleStackAccordion(stack.name)}
                    className="btn btn-secondary btn-sm"
                    style={{ padding: '0.3rem 0.5rem' }}
                  >
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                </div>
              </div>

              {/* Working Dir & Subtitle preview when collapsed */}
              {!isExpanded && stack.working_dir && (
                <div className="text-muted" style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', marginTop: '-0.5rem' }}>
                  {stack.working_dir}
                </div>
              )}

              {/* Expanded Accordion Body */}
              {isExpanded && (
                <div>
                  {/* Stack Path and Details */}
                  {stack.working_dir && (
                    <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.75rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      <span>Path: <strong className="font-mono text-primary">{stack.working_dir}</strong></span>
                      <button
                        onClick={() => handleOpenStackDetail(stack.name)}
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                      >
                        <FileText size={12} /> Full SRE Audit History
                      </button>
                    </div>
                  )}

                  {/* Last SRE Audit banner if available */}
                  {stack.last_audit && (
                    <div
                      style={{
                        padding: '0.6rem 0.85rem',
                        marginBottom: '1rem',
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: '0.85rem'
                      }}
                    >
                      <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                        <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                          <Bot size={15} color="var(--accent-emerald)" />
                          <strong style={{ fontSize: '0.8rem' }}>Latest SRE Log Review:</strong>
                          {getAuditBadge(stack.last_audit.status)}
                        </div>
                        <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                          {stack.last_audit.created_at ? new Date(stack.last_audit.created_at).toLocaleString() : ''}
                        </span>
                      </div>
                      <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4, fontSize: '0.825rem' }}>
                        {stack.last_audit.summary}
                      </div>
                    </div>
                  )}

                  {/* Container Inventory Table */}
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                          <th style={{ padding: '0.5rem 0.75rem' }}>CONTAINER</th>
                          <th style={{ padding: '0.5rem 0.75rem' }}>STATUS</th>
                          <th style={{ padding: '0.5rem 0.75rem' }}>IMAGE & TAG</th>
                          <th style={{ padding: '0.5rem 0.75rem' }}>PORTS</th>
                          <th style={{ padding: '0.5rem 0.75rem' }}>UPDATE STATUS</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stack.containers && stack.containers.length > 0 ? (
                          stack.containers.map(c => {
                            const isRunning = c.status?.toLowerCase() === 'running';
                            const isHealthy = c.health?.toLowerCase() === 'healthy';
                            const isUnhealthy = c.health?.toLowerCase() === 'unhealthy';

                            return (
                              <tr key={c.name} style={{ borderBottom: '1px solid var(--border-muted)' }}>
                                {/* Container Name */}
                                <td style={{ padding: '0.5rem 0.75rem' }}>
                                  <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                                    <span
                                      className="pulsing-dot"
                                      style={{
                                        background: isRunning
                                          ? isUnhealthy
                                            ? 'var(--status-danger)'
                                            : 'var(--status-healthy)'
                                          : 'var(--status-danger)'
                                      }}
                                    />
                                    <span className="font-mono" style={{ fontWeight: 700 }}>{c.name}</span>
                                    {c.service && c.service !== c.name && (
                                      <span className="text-muted" style={{ fontSize: '0.75rem' }}>({c.service})</span>
                                    )}
                                  </div>
                                </td>

                                {/* Status & Health */}
                                <td style={{ padding: '0.5rem 0.75rem' }}>
                                  <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                                    <span className={`badge ${isRunning ? 'badge-healthy' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>
                                      {c.status}
                                    </span>
                                    {c.health && c.health !== 'none' && (
                                      <span className={`badge ${isHealthy ? 'badge-healthy' : isUnhealthy ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.7rem' }}>
                                        {c.health}
                                      </span>
                                    )}
                                  </div>
                                </td>

                                {/* Image Tag */}
                                <td style={{ padding: '0.5rem 0.75rem' }}>
                                  <span className="font-mono text-secondary" style={{ fontSize: '0.8rem' }} title={c.image}>
                                    {c.image.length > 40 ? c.image.substring(0, 38) + '...' : c.image}
                                  </span>
                                </td>

                                {/* Ports */}
                                <td style={{ padding: '0.5rem 0.75rem' }}>
                                  <span className="text-muted font-mono" style={{ fontSize: '0.75rem' }}>
                                    {c.ports && c.ports.length > 0 ? c.ports.slice(0, 2).join(', ') + (c.ports.length > 2 ? ` +${c.ports.length - 2}` : '') : '-'}
                                  </span>
                                </td>

                                {/* Update Status */}
                                <td style={{ padding: '0.5rem 0.75rem' }}>
                                  {c.update_available ? (
                                    <span className="badge badge-warning" style={{ fontSize: '0.7rem' }}>
                                      <ArrowUpCircle size={12} /> Update Available
                                    </span>
                                  ) : c.update_status === 'UP_TO_DATE' ? (
                                    <span className="badge badge-healthy" style={{ fontSize: '0.7rem' }}>
                                      <CheckCircle size={12} /> Up to Date
                                    </span>
                                  ) : (
                                    <span className="badge badge-info" style={{ fontSize: '0.7rem' }}>
                                      {c.update_status || 'Current'}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          })
                        ) : (
                          <tr>
                            <td colSpan={5} className="text-muted" style={{ padding: '1rem', textAlign: 'center' }}>
                              No container details recorded for this stack.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* SRE Audit Result Modal */}
      {selectedAuditResult && (
        <div className="modal-backdrop" onClick={() => setSelectedAuditResult(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                <Bot size={20} color="var(--accent-emerald)" />
                <span style={{ fontWeight: 800, fontSize: '1.1rem' }}>
                  AI SRE Log Audit — {selectedAuditResult.stack_name}
                </span>
                {getAuditBadge(selectedAuditResult.status)}
              </div>
              <button onClick={() => setSelectedAuditResult(null)} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.5rem' }}>
                <X size={16} />
              </button>
            </div>

            <div className="modal-body">
              <div className="grid-cols-2" style={{ gap: '1rem', marginBottom: '1rem' }}>
                <div className="card" style={{ padding: '0.75rem' }}>
                  <div className="text-muted" style={{ fontSize: '0.75rem' }}>CONTAINERS INSPECTED</div>
                  <div className="font-mono" style={{ fontSize: '1.1rem', fontWeight: 700 }}>
                    {selectedAuditResult.containers_checked}
                  </div>
                </div>
                <div className="card" style={{ padding: '0.75rem' }}>
                  <div className="text-muted" style={{ fontSize: '0.75rem' }}>ERROR / WARNING COUNT</div>
                  <div className="font-mono" style={{ fontSize: '1.1rem', fontWeight: 700, color: Number(selectedAuditResult.error_count) > 0 ? 'var(--status-danger)' : 'var(--status-healthy)' }}>
                    {selectedAuditResult.error_count}
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: '1.25rem' }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                  AI SRE AUDIT SUMMARY
                </div>
                <div
                  style={{
                    padding: '0.85rem 1rem',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '0.9rem',
                    lineHeight: 1.5
                  }}
                >
                  {selectedAuditResult.summary}
                </div>
              </div>

              {selectedAuditResult.incident_id && (
                <div
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(239, 68, 68, 0.12)',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between'
                  }}
                >
                  <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                    <AlertTriangle size={16} color="var(--status-danger)" />
                    <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                      Actionable incident created ({selectedAuditResult.incident_id.substring(0, 8)}...)
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedAuditResult(null);
                      // Switch to incidents tab or open incident
                    }}
                    className="btn btn-danger btn-sm"
                  >
                    View in Incidents Queue
                  </button>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button onClick={() => setSelectedAuditResult(null)} className="btn btn-secondary btn-sm">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stack Full Detail / Audit History Modal */}
      {selectedStackDetail && (
        <div className="modal-backdrop" onClick={() => setSelectedStackDetail(null)}>
          <div className="modal-content" style={{ maxWidth: '820px' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                <Layers size={20} color="var(--accent-emerald)" />
                <span style={{ fontWeight: 800, fontSize: '1.1rem', fontFamily: 'var(--font-mono)' }}>
                  Stack SRE Profile: {selectedStackDetail.name}
                </span>
                {getStatusBadge(selectedStackDetail.status)}
              </div>
              <button onClick={() => setSelectedStackDetail(null)} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.5rem' }}>
                <X size={16} />
              </button>
            </div>

            <div className="modal-body">
              {/* Stack Info */}
              <div className="card" style={{ padding: '0.75rem 1rem', marginBottom: '1.25rem' }}>
                <div className="flex-row" style={{ justifyContent: 'space-between', fontSize: '0.85rem' }}>
                  <span>Working Directory: <strong className="font-mono">{selectedStackDetail.working_dir || 'N/A'}</strong></span>
                  <span>Containers: <strong>{selectedStackDetail.running_containers}/{selectedStackDetail.total_containers}</strong></span>
                </div>
              </div>

              {/* Incidents on this stack */}
              <div style={{ marginBottom: '1.5rem' }}>
                <div className="flex-row gap-sm" style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                  <AlertTriangle size={15} /> Active & Historical Incidents ({selectedStackDetail.incidents?.length || 0})
                </div>

                {selectedStackDetail.incidents && selectedStackDetail.incidents.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {selectedStackDetail.incidents.map(inc => (
                      <div
                        key={inc.id}
                        className="card"
                        style={{
                          padding: '0.75rem 1rem',
                          background: 'var(--bg-surface)',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center'
                        }}
                      >
                        <div>
                          <div className="flex-row gap-sm" style={{ alignItems: 'center', marginBottom: '0.25rem' }}>
                            <span className="font-mono" style={{ fontWeight: 700, fontSize: '0.85rem' }}>{inc.target_id}</span>
                            <span className={`badge ${inc.status === 'RESOLVED' ? 'badge-healthy' : inc.status === 'PENDING_USER' ? 'badge-warning' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>
                              {inc.status}
                            </span>
                            <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                              {inc.created_at ? new Date(inc.created_at).toLocaleString() : ''}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
                            {inc.root_cause || inc.category || 'Incident logged'}
                          </div>
                        </div>

                        <div className="flex-row gap-sm">
                          <button
                            onClick={() => setSelectedIncident(inc)}
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.75rem' }}
                          >
                            View Diagnosis
                          </button>
                          {inc.status === 'PENDING_USER' && (
                            <button
                              onClick={e => handleIncidentActionClick(inc.id, 'fix', e)}
                              className="btn btn-primary btn-sm"
                              style={{ fontSize: '0.75rem', background: 'var(--accent-emerald)' }}
                            >
                              <Play size={12} /> Approve Fix
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-muted" style={{ fontSize: '0.85rem', padding: '0.5rem 0' }}>
                    No recorded incidents for this stack.
                  </div>
                )}
              </div>

              {/* SRE Audit History */}
              <div>
                <div className="flex-row gap-sm" style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                  <Bot size={15} /> Recent SRE Log Audits ({selectedStackDetail.audit_history?.length || 0})
                </div>

                {selectedStackDetail.audit_history && selectedStackDetail.audit_history.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {selectedStackDetail.audit_history.map(a => (
                      <div
                        key={a.id || a.created_at}
                        className="card"
                        style={{ padding: '0.75rem 1rem', background: 'var(--bg-surface)' }}
                      >
                        <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                          <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                            {getAuditBadge(a.status)}
                            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                              {a.containers_checked} containers checked &bull; {a.error_count} errors
                            </span>
                          </div>
                          <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                            {a.created_at ? new Date(a.created_at).toLocaleString() : ''}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
                          {a.summary}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-muted" style={{ fontSize: '0.85rem', padding: '0.5rem 0' }}>
                    No prior audit records for this stack.
                  </div>
                )}
              </div>
            </div>

            <div className="modal-footer">
              <button onClick={() => setSelectedStackDetail(null)} className="btn btn-secondary btn-sm">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Incident Detail Modal */}
      {selectedIncident && (
        <div className="modal-backdrop" onClick={() => setSelectedIncident(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="flex-row gap-sm">
                <span style={{ fontWeight: 800, fontSize: '1.1rem', fontFamily: 'var(--font-mono)' }}>
                  {selectedIncident.target_id}
                </span>
                <span className="badge badge-healthy">{selectedIncident.status}</span>
              </div>
              <button onClick={() => setSelectedIncident(null)} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.5rem' }}>
                <X size={16} />
              </button>
            </div>

            <div className="modal-body">
              <div className="grid-cols-2" style={{ marginBottom: '1.25rem', gap: '0.75rem' }}>
                <div className="card" style={{ padding: '0.75rem' }}>
                  <div className="text-muted" style={{ fontSize: '0.75rem' }}>INCIDENT ID</div>
                  <div className="font-mono" style={{ fontSize: '0.8rem' }}>{selectedIncident.id}</div>
                </div>
                <div className="card" style={{ padding: '0.75rem' }}>
                  <div className="text-muted" style={{ fontSize: '0.75rem' }}>CATEGORY / ORIGIN</div>
                  <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>{selectedIncident.category} ({selectedIncident.origin || 'sre_audit'})</div>
                </div>
              </div>

              {selectedIncident.root_cause && (
                <div style={{ marginBottom: '1.25rem' }}>
                  <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                    <HelpCircle size={14} /> ROOT CAUSE DIAGNOSIS
                  </div>
                  <p style={{ fontSize: '0.9rem', lineHeight: 1.5 }}>{selectedIncident.root_cause}</p>
                </div>
              )}

              {selectedIncident.proposed_fix && (
                <div style={{ marginBottom: '1.25rem' }}>
                  <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                    <Terminal size={14} /> PROPOSED REMEDIATION
                  </div>
                  <div className="code-block">{selectedIncident.proposed_fix}</div>
                </div>
              )}

              {selectedIncident.error_logs && (
                <div>
                  <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                    <FileText size={14} /> ERROR LOGS
                  </div>
                  <div className="code-block" style={{ color: '#fca5a5', maxHeight: '200px', overflowY: 'auto' }}>
                    {selectedIncident.error_logs}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              {selectedIncident.status === 'PENDING_USER' && (
                <button
                  onClick={e => handleIncidentActionClick(selectedIncident.id, 'fix', e)}
                  className="btn btn-primary btn-sm"
                  style={{ background: 'var(--accent-emerald)' }}
                >
                  <Play size={14} /> Approve & Run Fix
                </button>
              )}
              <button onClick={() => setSelectedIncident(null)} className="btn btn-secondary btn-sm">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
