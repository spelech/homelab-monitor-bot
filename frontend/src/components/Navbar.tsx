import React from 'react';
import { Activity, Moon, Sun, ShieldCheck } from 'lucide-react';
import { Theme } from '../hooks/useTheme';

interface NavbarProps {
  theme: Theme;
  onToggleTheme: () => void;
  maintenanceActive: boolean;
  maintenanceReason: string;
}

export const Navbar: React.FC<NavbarProps> = ({
  theme,
  onToggleTheme,
  maintenanceActive,
  maintenanceReason
}) => {
  return (
    <header className="card" style={{ marginBottom: '1.25rem', padding: '0.85rem 1.25rem' }}>
      <div className="flex-row" style={{ justifyContent: 'space-between' }}>
        {/* Brand & Logo */}
        <div className="flex-row gap-md">
          <div className="stat-icon" style={{ background: 'var(--accent-emerald-subtle)', color: 'var(--accent-emerald)', width: 38, height: 38 }}>
            <Activity size={22} />
          </div>
          <div>
            <div className="flex-row gap-sm">
              <span style={{ fontWeight: 800, fontSize: '1.2rem', letterSpacing: '-0.02em' }}>
                AutoHeal <span className="text-emerald">SRE</span>
              </span>
              <span className="badge badge-healthy" style={{ fontSize: '0.7rem' }}>v2.0.0</span>
            </div>
            <div className="text-muted" style={{ fontSize: '0.75rem' }}>
              Autonomous Homelab SRE & Canary Controller
            </div>
          </div>
        </div>

        {/* System Status & Theme Controls */}
        <div className="flex-row gap-md">
          {maintenanceActive ? (
            <div className="badge badge-warning" style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}>
              <span className="pulsing-dot" style={{ background: 'var(--status-warning)' }}></span>
              <span>PAUSED: {maintenanceReason}</span>
            </div>
          ) : (
            <div className="badge badge-healthy" style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}>
              <span className="pulsing-dot"></span>
              <span>SYSTEM ACTIVE & PROTECTED</span>
            </div>
          )}

          <button
            onClick={onToggleTheme}
            className="btn btn-secondary btn-sm"
            title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Green Theme`}
            style={{ padding: '0.45rem 0.75rem' }}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        </div>
      </div>
    </header>
  );
};
