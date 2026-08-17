import React, { useState } from 'react';
import { Incident } from '../types/incident';
import { IncidentCard } from '../components/IncidentCard';
import { IncidentModal } from '../components/IncidentModal';
import { CheckCircle2, ShieldCheck, AlertTriangle } from 'lucide-react';

interface ActiveIncidentsViewProps {
  incidents: Incident[];
  onAction: (id: string, action: 'fix' | 'defer' | 'ignore' | 'dismiss') => void;
}

export const ActiveIncidentsView: React.FC<ActiveIncidentsViewProps> = ({ incidents, onAction }) => {
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);

  if (incidents.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '3.5rem 1.5rem' }}>
        <div
          className="stat-icon"
          style={{
            margin: '0 auto 1.25rem',
            width: 64,
            height: 64,
            borderRadius: '50%',
            background: 'var(--accent-emerald-subtle)',
            color: 'var(--accent-emerald)'
          }}
        >
          <ShieldCheck size={36} />
        </div>
        <h2 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '0.5rem' }}>
          All Systems Operational
        </h2>
        <p className="text-secondary" style={{ maxWidth: '480px', margin: '0 auto', fontSize: '0.95rem' }}>
          Zero active incidents detected. MonitorBot event watcher is continuously monitoring Docker containers and systemd host services.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '1rem' }}>
        <div className="flex-row gap-sm">
          <AlertTriangle size={18} color="var(--status-danger)" />
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>
            Active Incident Stream ({incidents.length})
          </h2>
        </div>
        <div className="text-muted" style={{ fontSize: '0.85rem' }}>
          Real-time AI diagnosis & remediation queue
        </div>
      </div>

      {incidents.map(inc => (
        <IncidentCard
          key={inc.id}
          incident={inc}
          onAction={onAction}
          onViewLogs={setSelectedIncident}
        />
      ))}

      <IncidentModal
        incident={selectedIncident}
        onClose={() => setSelectedIncident(null)}
      />
    </div>
  );
};
