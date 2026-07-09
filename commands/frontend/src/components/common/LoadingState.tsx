import React from 'react'
import { Spin, Typography } from 'antd'

interface LoadingStateProps {
  tip?: string
  size?: 'small' | 'default' | 'large'
}

const LoadingState: React.FC<LoadingStateProps> = ({ tip = '加载中...', size = 'large' }) => (
  <div
    style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 48,
      gap: 16,
    }}
  >
    <Spin size={size} aria-label="加载中..." />
    {tip && (
      <Typography.Text type="secondary" style={{ fontSize: 14 }}>
        {tip}
      </Typography.Text>
    )}
  </div>
)

export default LoadingState
