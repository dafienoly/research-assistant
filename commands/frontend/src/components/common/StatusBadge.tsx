import React from 'react'
import StatusDot from './StatusDot'
import type { DotStatus } from './StatusDot'
import type { StatusType } from '../../types'

interface StatusBadgeProps {
  status: StatusType
}

const CONFIG: Record<StatusType, { color: string; bg: string; text: string }> = {
  running:   { color: '#059669', bg: '#D1FAE5', text: '运行中' },
  completed: { color: '#059669', bg: '#D1FAE5', text: '已完成' },
  failed:    { color: '#DC2626', bg: '#FEE2E2', text: '失败' },
  pending:   { color: '#D97706', bg: '#FEF3C7', text: '待定' },
  idle:      { color: '#64748B', bg: '#F1F5F9', text: '空闲' },
}

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const c = CONFIG[status] || CONFIG.idle
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 12,
        color: c.color,
        backgroundColor: c.bg,
      }}
    >
      <StatusDot status={status as DotStatus} size={6} />
      {c.text}
    </span>
  )
}

export default StatusBadge
