import React from 'react'
import { Card, Skeleton, Typography } from 'antd'
import type { MetricColor } from '../../types'

interface MetricCardProps {
  title: string
  value: string | number
  trend?: number
  color?: MetricColor
  loading?: boolean
  suffix?: string
}

const COLOR_MAP: Record<MetricColor, string> = {
  primary: '#2563EB',
  success: '#059669',
  warning: '#D97706',
  error: '#DC2626',
  info: '#7C3AED',
}

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  trend,
  color = 'primary',
  loading = false,
  suffix,
}) => {
  const borderColor = COLOR_MAP[color]

  if (loading) {
    return (
      <Card style={{ borderLeft: `4px solid ${borderColor}`, borderRadius: 10 }}>
        <Skeleton active paragraph={{ rows: 1 }} />
      </Card>
    )
  }

  return (
    <Card
      style={{
        borderLeft: `4px solid ${borderColor}`,
        borderRadius: 10,
        border: '1px solid #E2E8F0',
        boxShadow: '0 1px 3px 0 rgb(0 0 0 / 0.04)',
      }}
    >
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {title}
      </Typography.Text>
      <div style={{ fontSize: 28, fontWeight: 600, color: '#0F172A', marginTop: 4 }}>
        {value}
        {suffix && <span style={{ fontSize: 14, color: '#64748B', marginLeft: 4 }}>{suffix}</span>}
      </div>
      {trend !== undefined && (
        <Typography.Text
          style={{
            color: trend >= 0 ? '#059669' : '#DC2626',
            fontSize: 12,
          }}
        >
          {trend >= 0 ? '↑' : '↓'} {Math.abs(trend).toFixed(1)}%
        </Typography.Text>
      )}
    </Card>
  )
}

export default MetricCard
