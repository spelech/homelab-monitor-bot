import React, { useEffect, useState } from 'react';
import { Incident } from '../types/incident';
import { X, Terminal, FileText, Cpu, Activity, CheckCircle2, AlertTriangle, ShieldAlert } from 'lucide-react';

interface IncidentModalProps {
  incident: Incident | null;
  onClose: () => void;
}

interface TranscriptEvent {
  timestamp: string;
  type: string;
  data: Record<string, any>;
}

export const IncidentModal: React.FC<IncidentModalProps> = ({ incident, onClose }) => {
  const [transcript, setTranscript] = useState<TranscriptEvent[]>([]);
  const [loadingTranscript, setLoadingTranscript] = useState(false);
  const [showRawJson, setShowRawJson] = useState<Record<number, boolean>>({});

  useEffect(() => {
    if (!incident) {
      setTranscript([]);
      return;
    }

    setLoadingTranscript(true);
    fetch(`/api/incidents/${incident.id}/transcript`)
      .then(res => res.json())
      .then(data => {
        if (data && Array.isArray(data.events)) {
          setTranscript(data.events);
        } else {
          setTranscript([]);
        }
      })
      .catch(err => {
        console.error('Failed to load incident transcript:', err);
        setTranscript([]);
      })
      .finally(() => {
        setLoadingTranscript(false);
      });
  }, [incident]);

  if (!incident) return null;

  const toggleRaw = (idx: number) => {
    setShowRawJson(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  const getEventBadge = (type: string) => {
    switch (type) {
      case 'PROMPT_GENERATED':
        return { label: 'PROMPT', color: '#60a5fa', icon: <FileText size={12} /> };
      case 'AI_THINKING_RAW':
        return { label: 'AI THINKING / RAW', color: '#a78bfa', icon: <Cpu size={12} /> };
      case 'DIAGNOSIS_PARSED':
        return { label: 'PARSED DIAGNOSIS', color: '#34d399', icon: <Activity size={12} /> };
      case 'REMEDIATION_EXECUTION':
        return { label: 'EXECUTION', color: '#fbbf24', icon: <Terminal size={12} /> };
      case 'POST_VERIFICATION':
        return { label: 'VERIFICATION', color: '#38bdf8', icon: <CheckCircle2 size={12} /> };
      case 'REMEDIATION_BLOCKED':
        return { label: 'BLOCKED', color: '#f87171', icon: <ShieldAlert size={12} /> };
      default:
        return { label: type, color: '#9ca3af', icon: <AlertTriangle size={12} /> };
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" style={{ maxWidth: '850px', maxHeight: '90vh' }} onClick={e => e.stopPropagation()}>
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
        <div className="modal-body" style={{ overflowY: 'auto' }}>
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

          {/* AI Thinking & Action Transcript */}
          <div style={{ marginBottom: '1.25rem' }}>
            <div className="flex-row gap-sm" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
              <Cpu size={14} /> AI THINKING & ACTION TRANSCRIPT
            </div>
            
            {loadingTranscript ? (
              <div className="text-muted font-mono" style={{ fontSize: '0.8rem', padding: '0.5rem' }}>
                Loading transcript events...
              </div>
            ) : transcript.length === 0 ? (
              <div className="text-muted font-mono" style={{ fontSize: '0.8rem', padding: '0.5rem', background: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                No detailed transcript events recorded for this incident yet.
              </div>
            ) : (
              <div className="flex-col gap-sm">
                {transcript.map((evt, idx) => {
                  const badge = getEventBadge(evt.type);
                  const isExpanded = !!showRawJson[idx];
                  return (
                    <div key={idx} className="card" style={{ padding: '0.6rem 0.8rem', background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255,255,255,0.07)' }}>
                      <div className="flex-row justify-between" style={{ marginBottom: '0.4rem', cursor: 'pointer' }} onClick={() => toggleRaw(idx)}>
                        <div className="flex-row gap-sm" style={{ alignItems: 'center' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                              fontSize: '0.7rem',
                              fontWeight: 700,
                              color: badge.color,
                              background: 'rgba(255,255,255,0.05)',
                              padding: '0.15rem 0.45rem',
                              borderRadius: '4px',
                              border: `1px solid ${badge.color}33`,
                              fontFamily: 'var(--font-mono)'
                            }}
                          >
                            {badge.icon}
                            {badge.label}
                          </span>
                          <span className="font-mono text-muted" style={{ fontSize: '0.75rem' }}>
                            {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ''}
                          </span>
                        </div>
                        <span className="text-muted font-mono" style={{ fontSize: '0.7rem' }}>
                          {isExpanded ? 'Collapse ▲' : 'Expand Details ▼'}
                        </span>
                      </div>

                      {/* Content summary */}
                      {evt.type === 'AI_THINKING_RAW' && evt.data?.raw_output && (
                        <div className="code-block" style={{ maxHeight: isExpanded ? '400px' : '100px', overflowY: 'auto', fontSize: '0.78rem', color: '#c4b5fd' }}>
                          {evt.data.raw_output}
                        </div>
                      )}

                      {evt.type === 'PROMPT_GENERATED' && evt.data?.prompt && (
                        <div className="code-block" style={{ maxHeight: isExpanded ? '400px' : '80px', overflowY: 'auto', fontSize: '0.75rem', color: '#93c5fd' }}>
                          {evt.data.prompt}
                        </div>
                      )}

                      {evt.type === 'REMEDIATION_EXECUTION' && (
                        <div className="code-block" style={{ fontSize: '0.78rem', color: evt.data.exit_code === 0 ? '#6ee7b7' : '#fca5a5' }}>
                          <div>$ {evt.data.command}</div>
                          {evt.data.stdout && <div style={{ color: '#a7f3d0', marginTop: '0.25rem' }}>{evt.data.stdout}</div>}
                          {evt.data.stderr && <div style={{ color: '#fca5a5', marginTop: '0.25rem' }}>{evt.data.stderr}</div>}
                        </div>
                      )}

                      {evt.type === 'POST_VERIFICATION' && (
                        <div className="font-mono" style={{ fontSize: '0.8rem', color: evt.data.is_healthy ? '#6ee7b7' : '#fca5a5' }}>
                          Verification result: {evt.data.status_detail}
                        </div>
                      )}

                      {/* Full Raw JSON when expanded */}
                      {isExpanded && (
                        <div style={{ marginTop: '0.5rem', borderTop: '1px dashed rgba(255,255,255,0.1)', paddingTop: '0.4rem' }}>
                          <div className="text-muted font-mono" style={{ fontSize: '0.7rem', marginBottom: '0.2rem' }}>RAW EVENT DATA:</div>
                          <pre className="code-block" style={{ maxHeight: '250px', overflowY: 'auto', fontSize: '0.72rem' }}>
                            {JSON.stringify(evt.data, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

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
