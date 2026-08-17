import React from 'react';
import { Incident } from '../types/incident';
import { X, Terminal, FileText } from 'lucide-react';

interface IncidentModalProps {
  incident: Incident | null;
  onClose: () => void;
}

export const IncidentModal: React.FC<IncidentModalProps> = ({ incident, onClose }) => {
  if (!incident) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="modal-header">
          <div className="flex-row gap-sm">
            <span style={{ fontWeight: 800, fontSize: '1.1rem', fontFamily: 'var(--font-mono)' }}>
              {incident.target_id}
            </span>
            <span className="badge badge-healthy">{incident.status}</span>
          </div>
          <button onClick={onClose} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.5rem' }}>
            <X size={16} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="modal-body">
          {/* Metadata */}
          <div className="grid-cols-2" style={{ marginBottom: '1.25rem' }}>
            <div className="card" style={{ padding: '0.75rem' }}>
              <div className="text-muted" style={{ fontSize: '0.75rem' }}>INCIDENT ID</div>
              <div className="font-mono" style={{ fontSize: '0.8rem' }}>{incident.id}</div>
            </div>
            <div className="card" style={{ padding: '0.75rem' }}>
              <div className="text-muted" style={{ fontSize: '0.75rem' }}>CATEGORY</div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>{incident.category || 'unknown'}</div>
            </div>
          </div>

          {/* Root cause */}
          {incident.root_cause && (
            <div style={{ marginBottom: '1.25rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                ROOT CAUSE DIAGNOSIS
              </div>
              <p style={{ fontSize: '0.9rem', lineHeight: 1.5 }}>{incident.root_cause}</p>
            </div>
          )}

          {/* Proposed fix */}
          {incident.proposed_fix && (
            <div style={{ marginBottom: '1.25rem' }}>
              <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                <Terminal size={14} /> PROPOSED REMEDIATION
              </div>
              <div className="code-block">{incident.proposed_fix}</div>
            </div>
          )}

          {/* Execution Log */}
          {incident.execution_log && (
            <div style={{ marginBottom: '1.25rem' }}>
              <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                <Terminal size={14} /> REMEDIATION EXECUTION LOG
              </div>
              <div className="code-block" style={{ color: '#6ee7b7' }}>{incident.execution_log}</div>
            </div>
          )}

          {/* Error Logs */}
          {incident.error_logs && (
            <div>
              <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                <FileText size={14} /> DOCKER CRASH LOGS
              </div>
              <div className="code-block" style={{ color: '#fca5a5' }}>{incident.error_logs}</div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="modal-footer">
          <button onClick={onClose} className="btn btn-secondary btn-sm">
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
