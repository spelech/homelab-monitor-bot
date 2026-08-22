import React, { useState } from 'react';
import { useTheme } from './hooks/useTheme';
import { useIncidents } from './hooks/useIncidents';
import { useSettings } from './hooks/useSettings';
import { useUpgrades } from './hooks/useUpgrades';

import { Navbar } from './components/Navbar';
import { StatusHeader } from './components/StatusHeader';
import { TabNavigation, ActiveTab } from './components/TabNavigation';

import { ActiveIncidentsView } from './views/ActiveIncidentsView';
import { StackWatchersView } from './views/StackWatchersView';
import { UpgradeHubView } from './views/UpgradeHubView';
import { SpendTrackerView } from './views/SpendTrackerView';
import { MemorySearchView } from './views/MemorySearchView';
import { TargetsFleetView } from './views/TargetsFleetView';
import { HistoryView } from './views/HistoryView';

export const App: React.FC = () => {
  const { theme, toggleTheme } = useTheme();
  const [activeTab, setActiveTab] = useState<ActiveTab>('incidents');

  const { dashboard, triggerAction, unignoreTarget } = useIncidents();
  const { settings, toggleAutopilot, toggleSilentMode, setMaintenanceDuration } = useSettings();
  const {
    stacks,
    liveJob,
    runs,
    canaryResult,
    loading: upgradeLoading,
    canaryLoading,
    triggerUpgrade,
    cancelUpgrade,
    runCanaryAudit
  } = useUpgrades();

  const activeIncidents = dashboard?.active_incidents || [];
  const historyIncidents = dashboard?.history_incidents || [];

  return (
    <div className="app-container">
      {/* Top Navbar */}
      <Navbar
        theme={theme}
        onToggleTheme={toggleTheme}
        maintenanceActive={settings.maintenance_active}
        maintenanceReason={settings.maintenance_reason}
      />

      {/* System Status Controls Header */}
      <StatusHeader
        maintenanceActive={settings.maintenance_active}
        maintenanceReason={settings.maintenance_reason}
        autopilot={settings.autopilot}
        silentMode={settings.silent_mode}
        onSetMaintenance={setMaintenanceDuration}
        onToggleAutopilot={toggleAutopilot}
        onToggleSilentMode={toggleSilentMode}
      />

      {/* Main Tab Navigation */}
      <TabNavigation
        activeTab={activeTab}
        onTabChange={setActiveTab}
        activeIncidentsCount={activeIncidents.length}
      />

      {/* Active Tab View Rendering */}
      <main>
        {activeTab === 'incidents' && (
          <ActiveIncidentsView
            incidents={activeIncidents}
            onAction={triggerAction}
          />
        )}

        {activeTab === 'stacks' && (
          <StackWatchersView
            onTriggerUpgrade={(targets) => {
              triggerUpgrade(targets);
              setActiveTab('upgrades');
            }}
            onIncidentAction={triggerAction}
          />
        )}

        {activeTab === 'upgrades' && (
          <UpgradeHubView
            stacks={stacks}
            liveJob={liveJob}
            runs={runs}
            canaryResult={canaryResult}
            loading={upgradeLoading}
            canaryLoading={canaryLoading}
            onTriggerUpgrade={triggerUpgrade}
            onCancelUpgrade={cancelUpgrade}
            onRunCanaryAudit={runCanaryAudit}
          />
        )}

        {activeTab === 'spend' && <SpendTrackerView />}

        {activeTab === 'memory' && <MemorySearchView />}

        {activeTab === 'fleet' && (
          <TargetsFleetView onUnignore={unignoreTarget} />
        )}

        {activeTab === 'history' && (
          <HistoryView history={historyIncidents} />
        )}
      </main>
    </div>
  );
};

