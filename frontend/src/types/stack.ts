export interface ContainerDetail {
  id?: string;
  name: string;
  service?: string;
  project?: string;
  working_dir?: string;
  config_files?: string;
  image: string;
  image_id?: string;
  image_tags?: string[];
  repo_digests?: string[];
  status: string; // 'running' | 'exited' | 'restarting' | 'dead' | string
  health?: string; // 'healthy' | 'unhealthy' | 'starting' | 'none' | string
  started_at?: string;
  created_at?: string;
  ports?: string[];
  labels?: Record<string, string>;
  uptime?: string;
  update_available?: boolean;
  update_status?: string; // 'UPDATE_AVAILABLE' | 'UP_TO_DATE' | 'UNKNOWN' | string
  remote_digest?: string | null;
  local_digest?: string | null;
}

export interface StackAuditInfo {
  id?: string;
  stack_name: string;
  status: 'CLEAN' | 'WARNING' | 'ANOMALOUS' | 'ERROR' | 'HEALTHY' | 'UNKNOWN' | string;
  summary: string;
  error_count: string | number;
  containers_checked: string | number;
  created_at?: string | null;
}

export interface StackIncidentInfo {
  id: string;
  target_id: string;
  status: 'DETECTED' | 'INVESTIGATING' | 'PENDING_USER' | 'FIXING' | 'RESOLVED' | 'FAILED' | 'DEFERRED' | 'IGNORED' | 'BLOCKED' | string;
  category: string;
  stack_name?: string | null;
  origin?: string;
  error_logs?: string | null;
  root_cause?: string | null;
  proposed_fix?: string | null;
  execution_log?: string | null;
  deferred_until?: string | null;
  completed_at?: string | null;
  created_at?: string | null;
}

export interface StackSummary {
  name: string;
  path: string;
  working_dir: string;
  config_files?: string;
  status: 'healthy' | 'unhealthy' | 'degraded' | 'stopped' | string;
  total_containers: number;
  running_containers: number;
  healthy_containers: number;
  unhealthy_containers: number;
  updates_available_count: number;
  active_incidents_count: number;
  last_audit?: StackAuditInfo | null;
  containers: ContainerDetail[];
}

export interface StackDetail extends StackSummary {
  audit_history?: StackAuditInfo[];
  incidents?: StackIncidentInfo[];
}

export interface StackCheckUpdatesResult {
  stack_name: string;
  updates_count: number;
  total_checked: number;
  containers: {
    container_name: string;
    image: string;
    status: string;
    update_available: boolean;
    remote_digest?: string | null;
    local_digest?: string | null;
  }[];
}

export interface StackAuditResult {
  stack_name: string;
  status: string;
  error_count: number | string;
  containers_checked: number | string;
  summary: string;
  incident_id?: string | null;
}
