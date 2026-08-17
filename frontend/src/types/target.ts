export interface TargetItem {
  id: string;
  type: string;
  is_ignored: boolean;
  ignored_until: string | null;
  docker_status?: string;
  docker_health?: string;
}
