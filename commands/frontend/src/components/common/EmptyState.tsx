import React from 'react'
import { Empty, Typography } from 'antd'

interface EmptyStateProps {
  description?: string
  image?: React.ReactNode
}

const EmptyState: React.FC<EmptyStateProps> = ({
  description = '暂无数据',
}) => (
  <div style={{ padding: 48 }}>
    <Empty description={description} />
  </div>
)

export default EmptyState
