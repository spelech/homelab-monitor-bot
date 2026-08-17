export interface StackInfo {
  name: string;
  path: string;
  services_count: number;
  containers: string[];
}

export interface CanaryCheck {
  name: string;
  status: 'PASS' | 'FAIL' | 'ERROR';
  detail: string;
}

export interface CanaryResults {
  timestamp?: string;
  overall_status?: 'PASS' | 'FAIL';
  failures_count?: number;
  checks?: CanaryCheck[];
}

export interface UpgradeJob {
  run_id: string;
  status: 'RUNNING' | 'SUCCESS' | 'WARNING' | 'FAILED' | 'CANCELLED';
  targets: string[];
  current_step?: string;
  started_at?: string | null;
  completed_at?: string | null;
  logs: string[];
  canary_results: CanaryResults;
}

export interface UpgradeRunHistory {
  id: string;
  status: string;
  targets: string[];
  canary_results: CanaryResults;
  started_at: string | null;
  completed_at: string | null;
  logs?: string;
}
