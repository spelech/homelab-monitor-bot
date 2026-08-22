import React from 'react';
import { AlertTriangle, Layers, ArrowUpCircle, DollarSign, Search, Server, History } from 'lucide-react';

export type ActiveTab = 'incidents' | 'stacks' | 'upgrades' | 'spend' | 'memory' | 'fleet' | 'history';

interface TabNavigationProps {
  activeTab: ActiveTab;
  onTabChange: (tab: ActiveTab) => void;
  activeIncidentsCount: number;
}

export const TabNavigation: React.FC<TabNavigationProps> = ({
  activeTab,
  onTabChange,
  activeIncidentsCount
}) => {
  return (
    <div className="tab-bar">
      <button
        className={`tab-btn ${activeTab === 'incidents' ? 'active' : ''}`}
        onClick={() => onTabChange('incidents')}
      >
        <AlertTriangle size={16} />
        <span>Active Incidents</span>
        {activeIncidentsCount > 0 && (
          <span className="badge badge-danger" style={{ padding: '0.1rem 0.45rem', fontSize: '0.7rem' }}>
            {activeIncidentsCount}
          </span>
        )}
      </button>

      <button
        className={`tab-btn ${activeTab === 'stacks' ? 'active' : ''}`}
        onClick={() => onTabChange('stacks')}
      >
        <Layers size={16} />
        <span>Stack SRE</span>
      </button>

      <button
        className={`tab-btn ${activeTab === 'upgrades' ? 'active' : ''}`}
        onClick={() => onTabChange('upgrades')}
      >
        <ArrowUpCircle size={16} />
        <span>Upgrade & Canary Hub</span>
      </button>

      <button
        className={`tab-btn ${activeTab === 'spend' ? 'active' : ''}`}
        onClick={() => onTabChange('spend')}
      >
        <DollarSign size={16} />
        <span>AI Spend Tracker</span>
      </button>

      <button
        className={`tab-btn ${activeTab === 'memory' ? 'active' : ''}`}
        onClick={() => onTabChange('memory')}
      >
        <Search size={16} />
        <span>Semantic Memory</span>
      </button>

      <button
        className={`tab-btn ${activeTab === 'fleet' ? 'active' : ''}`}
        onClick={() => onTabChange('fleet')}
      >
        <Server size={16} />
        <span>Target Fleet</span>
      </button>

      <button
        className={`tab-btn ${activeTab === 'history' ? 'active' : ''}`}
        onClick={() => onTabChange('history')}
      >
        <History size={16} />
        <span>Incident History</span>
      </button>
    </div>
  );
};

