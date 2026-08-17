import React, { useState, useEffect } from 'react';
import { TargetItem } from '../types/target';
import { Server, Eye, ShieldAlert, CheckCircle } from 'lucide-react';

interface TargetsFleetViewProps {
  onUnignore: (id: string) => void;
}

export const TargetsFleetView: React.FC<TargetsFleetViewProps> = ({ onUnignore }) => {
  const [targets, setTargets] = useState<TargetItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTargets = async () => {
    try {
      const res = await fetch('/api/targets');
      if (res.ok) {
        const data = await res.json();
        setTargets(data);
      }
    } catch (e) {
      console.error('Failed to load targets:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTargets();
  }, []);

  return (
    <div>
      <div className="card-header" style={{ marginBottom: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>Monitored Fleet Targets ({targets.length})</h2>
          <div className="text-muted" style={{ fontSize: '0.85rem' }}>
            Registered Docker containers and systemd host services
          </div>
        </div>
      </div>

      <div className="grid-cols-3" style={{ gap: '0.75rem' }}>
        {targets.map(t => (
          <div key={t.id} className="card" style={{ padding: '0.85rem 1rem' }}>
            <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span className="font-mono" style={{ fontSize: '0.9rem', fontWeight: 700 }}>{t.id}</span>
              <span className="badge badge-info">{t.type}</span>
            </div>

            <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                {t.is_ignored ? (
                  <span className="badge badge-warning" style={{ fontSize: '0.75rem' }}>
                    <ShieldAlert size={12} /> Ignored
                  </span>
                ) : (
                  <span className="badge badge-healthy" style={{ fontSize: '0.75rem' }}>
                    <CheckCircle size={12} /> Monitored
                  </span>
                )}
              </div>

              {t.is_ignored && (
                <button
                  onClick={async () => {
                    await onUnignore(t.id);
                    await fetchTargets();
                  }}
                  className="btn btn-secondary btn-sm"
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  <Eye size={12} /> Unignore
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
