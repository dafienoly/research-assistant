import { get, post } from './client'

export type VNextRecord = Record<string, unknown>

export interface VNextComponent {
  status?: string
  as_of?: string
  updated_at?: string
  confidence?: number
  evidence?: string[]
  missing_evidence?: string[]
  data_sources?: string[]
  payload?: VNextRecord
  [key: string]: unknown
}

export interface ApprovalList {
  items: VNextRecord[]
  total: number
}

const dated = (path: string, date?: string) => get<VNextComponent>(path, date ? { date } : undefined)

export const vnextApi = {
  status: (date?: string) => dated('/api/vnext/status', date),
  dataHealth: (date?: string) => dated('/api/vnext/data-health', date),
  regime: (date?: string) => dated('/api/vnext/regime', date),
  policyPut: (date?: string) => dated('/api/vnext/policy-put', date),
  semiMainline: (date?: string) => dated('/api/vnext/semi-mainline', date),
  candidates: (date?: string) => dated('/api/vnext/candidates', date),
  portfolioRisk: (date?: string) => dated('/api/vnext/portfolio-risk', date),
  mlRanker: (date?: string) => dated('/api/vnext/ml-ranker', date),
  backtests: () => get<VNextComponent>('/api/vnext/backtests'),
  paper: (date?: string) => dated('/api/vnext/paper', date),
  shadow: (date?: string) => dated('/api/vnext/shadow', date),
  approvals: () => get<ApprovalList>('/api/vnext/approvals'),
  approval: (id: string) => get<VNextComponent>(`/api/vnext/approvals/${encodeURIComponent(id)}`),
  executionStatus: (date?: string) => dated('/api/vnext/execution-status', date),
  antifragileReview: (date?: string) => dated('/api/vnext/antifragile-review', date),
  reports: (date?: string) => dated('/api/vnext/reports', date),
  decideApproval: (
    id: string,
    action: 'approve' | 'reject' | 'delay' | 'modify',
    body: { approver: string; reason: string; modifications?: VNextRecord },
  ) => post<VNextComponent>(`/api/vnext/approvals/${encodeURIComponent(id)}/${action}`, body),
}

export const reportDownloadUrl = (date: string, format: 'md' | 'json' | 'csv' = 'md') =>
  `/api/vnext/reports/download?date=${encodeURIComponent(date)}&format=${format}`
