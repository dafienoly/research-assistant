import React, { useEffect, useState, useCallback } from 'react'
import { Space, Tag, Typography, Button } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import StatusDot from '../../components/common/StatusDot'

type BackendStatus = 'checking' | 'ok' | 'error'

const TopStatusBar: React.FC = () => {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('checking')
  const [retryCount, setRetryCount] = useState(0)

  const checkBackend = useCallback(async (silent = false) => {
    if (!silent) setBackendStatus('checking')
    try {
      const r = await fetch('/api/status')
      if (r.ok) {
        setBackendStatus('ok')
      } else {
        throw new Error(`HTTP ${r.status}`)
      }
    } catch {
      setBackendStatus('error')
    }
  }, [])

  // Initial check + polling every 30s
  useEffect(() => {
    checkBackend()
    const timer = setInterval(() => checkBackend(true), 30_000)
    return () => clearInterval(timer)
  }, [checkBackend])

  const handleRetry = () => {
    setRetryCount((c) => c + 1)
    checkBackend()
  }

  return (
    <div
      style={{
        height: 32,
        background: '#FFFFFF',
        borderBottom: '1px solid #E2E8F0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        padding: '0 16px',
        animation: 'fadeIn 0.2s ease',
      }}
    >
      <Space size={12}>
        {backendStatus === 'checking' && (
          <Tag icon={<SyncOutlined spin />} color="default" style={{ margin: 0 }}>
            检查连接...
          </Tag>
        )}
        {backendStatus === 'ok' && (
          <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0 }}>
            后端在线
          </Tag>
        )}
        {backendStatus === 'error' && (
          <Space size={4}>
            <Tag
              icon={<CloseCircleOutlined />}
              color="error"
              style={{ margin: 0 }}
              closable={false}
            >
              后端离线
            </Tag>
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              onClick={handleRetry}
              style={{ fontSize: 11, color: '#DC2626', padding: '0 4px' }}
            >
              重试
            </Button>
          </Space>
        )}

        {/* Small status dot indicator */}
        <StatusDot
          status={
            backendStatus === 'ok'
              ? 'running'
              : backendStatus === 'error'
                ? 'error'
                : 'idle'
          }
          size={6}
          pulse={backendStatus === 'checking'}
        />

        <Typography.Text style={{ fontSize: 12, color: '#94A3B8' }}>
          Hermes V5 投研系统
        </Typography.Text>
      </Space>
    </div>
  )
}

export default TopStatusBar
