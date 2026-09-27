export interface StackAuditItem {
  id: string;
  stack_name: string;
  status: string;
  summary: string;
  error_count: string;
  containers_checked: string;
  created_at: string;
}

export interface ActionableAuditItem {
  incident_id: string;
  target_id: string;
  stack_name: string;
  status: string;
  category: string;
  root_cause?: string;
  proposed_fix?: string;
  can_action: boolean;
  created_at: string;
  deferred_until?: string | null;
}

export interface DailyAuditReport {
  date: string;
  total_stacks: number;
  healthy_count: number;
  warning_count: number;
  outages_count: number;
  stack_audits: StackAuditItem[];
  actionable_items: ActionableAuditItem[];
}
