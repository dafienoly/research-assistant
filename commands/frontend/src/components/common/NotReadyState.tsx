import React from 'react'
import { Alert, Typography } from 'antd'

interface NotReadyStateProps {
  title?: string
  description?: string
  suggestions?: string[]
}

const NotReadyState: React.FC<NotReadyStateProps> = ({
  title = '功能开发中',
  description = '该功能正在开发中，敬请期待。',
  suggestions,
}) => (
  <Alert
    type="warning"
    message={title}
    description={
      <div>
        <Typography.Paragraph style={{ marginBottom: 8 }}>{description}</Typography.Paragraph>
        {suggestions && suggestions.length > 0 && (
          <div>
            <Typography.Text strong style={{ fontSize: 12 }}>
              修复建议：
            </Typography.Text>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {suggestions.map((s, i) => (
                <li key={i}>
                  <Typography.Text style={{ fontSize: 12 }}>{s}</Typography.Text>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    }
    showIcon
    style={{ marginBottom: 16 }}
  />
)

export default NotReadyState
