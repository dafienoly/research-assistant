import React from 'react'
import { Alert, Button } from 'antd'

interface ErrorStateProps {
  message?: string
  description?: string
  onRetry?: () => void
}

const ErrorState: React.FC<ErrorStateProps> = ({
  message = '加载失败',
  description,
  onRetry,
}) => (
  <Alert
    type="error"
    message={message}
    description={description}
    showIcon
    closable
    role="alert"
    action={
      onRetry ? (
        <Button size="small" onClick={onRetry}>
          重试
        </Button>
      ) : null
    }
  />
)

export default ErrorState
