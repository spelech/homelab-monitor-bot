export interface AIUsageLogItem {
  id: string;
  incident_id: string | null;
  executor: string;
  model_id: string;
  prompt_tokens: string;
  completion_tokens: string;
  total_tokens: string;
  cost_usd: string;
  duration_sec: string;
  status: string;
  created_at: string | null;
}

export interface AIUsageSummary {
  total_calls: number;
  total_tokens: number;
  total_cost_usd: number;
  model_counts: Record<string, number>;
  executor_counts: Record<string, number>;
  litellm_status: string;
  recent_logs: AIUsageLogItem[];
}
