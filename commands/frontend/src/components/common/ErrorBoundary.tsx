import React from 'react'
import { Alert, Button, Typography } from 'antd'

interface ErrorBoundaryProps {
  children: React.ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 48, maxWidth: 600, margin: '0 auto' }}>
          <Alert
            type="error"
            message="页面渲染异常"
            description={
              <div>
                <Typography.Paragraph>
                  很抱歉，页面遇到了一个意外错误。请尝试刷新页面或联系管理员。
                </Typography.Paragraph>
                {this.state.error && (
                  <pre style={{ fontSize: 12, background: '#FEE2E2', padding: 8, borderRadius: 6 }}>
                    {this.state.error.message}
                  </pre>
                )}
              </div>
            }
            showIcon
            action={
              <Button onClick={this.handleReset} type="primary" size="small">
                重试
              </Button>
            }
          />
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
