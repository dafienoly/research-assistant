/** StatusBadge supported statuses */
export type StatusType = 'running' | 'completed' | 'failed' | 'pending' | 'idle'

/** MetricCard color variants */
export type MetricColor = 'primary' | 'success' | 'warning' | 'error' | 'info'

/** PageHeader data source info */
export interface PageHeaderInfo {
  title: string
  updatedAt?: string
  dataSource?: string
  runId?: string
}
