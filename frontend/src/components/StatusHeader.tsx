import React from 'react';
import { Pause, Play, Zap, BellOff, Bell } from 'lucide-react';

interface StatusHeaderProps {
  maintenanceActive: boolean;
  maintenanceReason: string;
  autopilot: boolean;
  silentMode: boolean;
  onSetMaintenance: (duration: string) => void;
  onToggleAutopilot: () => void;
  onToggleSilentMode: () => void;
}

export const StatusHeader: React.FC<StatusHeaderProps> = ({
  maintenanceActive,
  maintenanceReason,
  autopilot,
  silentMode,
  onSetMaintenance,
  onToggleAutopilot,
  onToggleSilentMode
}) => {
  return (
    <div className="card" style={{ marginBottom: '1.5rem', padding: '1rem 1.25rem' }}>
      <div className="flex-row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
        
        {/* Maintenance Controls */}
        <div className="flex-row gap-sm" style={{ flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', marginRight: '0.25rem' }}>
            Maintenance:
          </span>
          {maintenanceActive ? (
            <button
              onClick={() => onSetMaintenance('resume')}
              className="btn btn-primary btn-sm"
              style={{ background: 'var(--status-healthy)' }}
            >
              <Play size={14} /> Resume Monitoring
            </button>
          ) : (
            <>
              <button onClick={() => onSetMaintenance('15m')} className="btn btn-secondary btn-sm">15m</button>
              <button onClick={() => onSetMaintenance('30m')} className="btn btn-secondary btn-sm">30m</button>
              <button onClick={() => onSetMaintenance('1h')} className="btn btn-secondary btn-sm">1h</button>
              <button onClick={() => onSetMaintenance('2h')} className="btn btn-secondary btn-sm">2h</button>
              <button onClick={() => onSetMaintenance('12h')} className="btn btn-secondary btn-sm">12h</button>
              <button onClick={() => onSetMaintenance('indefinite')} className="btn btn-warning btn-sm">
                <Pause size={14} /> Indefinite
              </button>
            </>
          )}
        </div>

        {/* System Mode Toggles */}
        <div className="flex-row gap-lg" style={{ flexWrap: 'wrap' }}>
          {/* Autopilot Switch */}
          <div className="toggle-switch" onClick={onToggleAutopilot} title="Autopilot: Automatically executes safe remediations without manual user confirmation.">
            <div className={`toggle-track ${autopilot ? 'active' : ''}`}>
              <div className="toggle-thumb"></div>
            </div>
            <div className="flex-row gap-sm" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
              <Zap size={15} color={autopilot ? 'var(--status-warning)' : 'var(--text-muted)'} />
              <span>Autopilot {autopilot ? 'ON' : 'OFF'}</span>
            </div>
          </div>

          {/* Silent Mode Switch */}
          <div className="toggle-switch" onClick={onToggleSilentMode} title="Silent Mode: Suppresses external push notifications (ntfy/telegram).">
            <div className={`toggle-track ${silentMode ? 'active' : ''}`}>
              <div className="toggle-thumb"></div>
            </div>
            <div className="flex-row gap-sm" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
              {silentMode ? <BellOff size={15} color="var(--status-danger)" /> : <Bell size={15} color="var(--text-muted)" />}
              <span>Silent Mode {silentMode ? 'ON' : 'OFF'}</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
