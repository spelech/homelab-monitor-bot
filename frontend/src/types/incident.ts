export interface Incident {
  id: string;
  target_id: string;
  status: 'DETECTED' | 'INVESTIGATING' | 'PENDING_USER' | 'FIXING' | 'RESOLVED' | 'FAILED' | 'DEFERRED' | 'IGNORED' | 'BLOCKED';
  category: string;
  error_logs?: string | null;
  root_cause?: string | null;
  proposed_fix?: string | null;
  execution_log?: string | null;
  deferred_until?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  score?: number;
}

export interface DashboardData {
  active_count: number;
  resolved_count: number;
  targets_count: number;
  ignored_count: number;
  active_incidents: Incident[];
  history_incidents: Incident[];
  ignored_targets: { id: string; type: string; ignored_until: string | null }[];
  maintenance_active: boolean;
  maintenance_reason: string;
  autopilot: boolean;
  silent_mode: boolean;
}
