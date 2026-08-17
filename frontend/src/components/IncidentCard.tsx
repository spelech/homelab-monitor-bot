import React from 'react';
import { Incident } from '../types/incident';
import { Play, Clock, EyeOff, CheckCircle, Terminal, HelpCircle } from 'lucide-react';

interface IncidentCardProps {
  incident: Incident;
  onAction: (id: string, action: 'fix' | 'defer' | 'ignore' | 'dismiss') => void;
  onViewLogs: (incident: Incident) => void;
}

export const IncidentCard: React.FC<IncidentCardProps> = ({
  incident,
  onAction,
  onViewLogs
}) => {
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PENDING_USER':
        return <span className="badge badge-warning">Awaiting Approval</span>;
      case 'INVESTIGATING':
        return <span className="badge badge-info">AI Investigating...</span>;
      case 'FIXING':
        return <span className="badge badge-purple">Applying Fix...</span>;
      case 'BLOCKED':
        return <span className="badge badge-danger">Safety Blocked</span>;
      default:
        return <span className="badge badge-danger">{status}</span>;
    }
  };

  return (
    <div className="card" style={{ marginBottom: '1rem', borderLeft: '4px solid var(--accent-emerald)' }}>
      {/* Header */}
      <div className="card-header" style={{ marginBottom: '0.75rem' }}>
        <div className="flex-row gap-sm">
          <span style={{ fontSize: '1.1rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {incident.target_id}
          </span>
          <span className="badge badge-healthy">{incident.category || 'unknown'}</span>
          {getStatusBadge(incident.status)}
        </div>
        <div className="text-muted" style={{ fontSize: '0.8rem' }}>
          {incident.created_at ? new Date(incident.created_at).toLocaleTimeString() : ''}
        </div>
      </div>

      {/* Root Cause / Diagnosis */}
      {incident.root_cause ? (
        <div style={{ marginBottom: '0.75rem' }}>
          <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
            <HelpCircle size={14} /> AI Root Cause Diagnosis:
          </div>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-primary)', lineHeight: 1.5 }}>
            {incident.root_cause}
          </p>
        </div>
      ) : (
        <div className="text-muted" style={{ fontSize: '0.85rem', marginBottom: '0.75rem' }}>
          {incident.status === 'INVESTIGATING' ? 'Analyzing container crash logs & diagnostics...' : 'Failure detected. Queueing AI investigation...'}
        </div>
      )}

      {/* Proposed Bash Fix */}
      {incident.proposed_fix && (
        <div style={{ marginBottom: '1rem' }}>
          <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
            <Terminal size={14} /> Proposed Remediation:
          </div>
          <div className="code-block" style={{ maxHeight: '120px', overflowY: 'auto' }}>
            {incident.proposed_fix}
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex-row gap-sm" style={{ justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button
          onClick={() => onViewLogs(incident)}
          className="btn btn-secondary btn-sm"
        >
          View Error Logs
        </button>

        {incident.status === 'PENDING_USER' && (
          <>
            <button
              onClick={() => onAction(incident.id, 'defer')}
              className="btn btn-secondary btn-sm"
              title="Defer alert for 24 hours"
            >
              <Clock size={14} /> Defer 24h
            </button>

            <button
              onClick={() => onAction(incident.id, 'ignore')}
              className="btn btn-secondary btn-sm"
              title="Permanently ignore target"
            >
              <EyeOff size={14} /> Ignore Target
            </button>

            <button
              onClick={() => onAction(incident.id, 'dismiss')}
              className="btn btn-secondary btn-sm"
            >
              Dismiss
            </button>

            <button
              onClick={() => onAction(incident.id, 'fix')}
              className="btn btn-primary btn-sm"
              style={{ background: 'var(--accent-emerald)' }}
            >
              <Play size={14} /> Approve & Run Fix
            </button>
          </>
        )}
      </div>
    </div>
  );
};
