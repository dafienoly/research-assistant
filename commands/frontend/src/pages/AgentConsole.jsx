import { useState, useRef, useEffect } from 'react'
import { Card, Button, Tag, Space, Typography, Empty, Spin, Badge } from 'antd'
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  StopOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import useSSE from '../hooks/useSSE'

const { Text, Paragraph } = Typography

const SEVERITY_COLORS = {
  info: 'default',
  success: 'success',
  warning: 'warning',
  error: 'error',
  debug: 'geekblue',
}

export default function AgentConsole() {
  const [logs, setLogs] = useState([])
  const [paused, setPaused] = useState(false)
  const logEndRef = useRef(null)
  const logContainerRef = useRef(null)
  const autoScrollRef = useRef(true)

  const SSE_URL = '/api/agents/events'

  const { data: sseData, isConnected, connect, disconnect } = useSSE(SSE_URL, {
    events: ['agent_log', 'agent_status', 'message'],
    autoConnect: false,
    reconnectDelay: 2000,
  })

  // Incoming SSE data
  useEffect(() => {
    if (!sseData) return
    const { event, data } = sseData

    if (event === 'agent_log') {
      const entry = {
        id: Date.now() + Math.random(),
        timestamp: new Date().toLocaleTimeString(),
        agent: data.agent || 'system',
        level: data.level || 'info',
        message: data.message || '',
      }
      setLogs((prev) => (paused ? prev : [...prev.slice(-500), entry]))
    } else if (event === 'agent_status') {
      const entry = {
        id: Date.now() + Math.random(),
        timestamp: new Date().toLocaleTimeString(),
        agent: data.agent || 'system',
        level: 'info',
        message: `[状态变更] ${data.agent} → ${data.status}`,
      }
      setLogs((prev) => (paused ? prev : [...prev.slice(-500), entry]))
    }
  }, [sseData, paused])

  // Auto-scroll
  useEffect(() => {
    if (autoScrollRef.current && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs])

  const handleScroll = () => {
    const el = logContainerRef.current
    if (!el) return
    const threshold = 40
    autoScrollRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold
  }

  const handleConnect = () => {
    setLogs((prev) => [
      ...prev,
      {
        id: Date.now(),
        timestamp: new Date().toLocaleTimeString(),
        agent: 'system',
        level: 'info',
        message: '正在连接 SSE 事件流...',
      },
    ])
    connect()
  }

  const handleDisconnect = () => {
    disconnect()
    setLogs((prev) => [
      ...prev,
      {
        id: Date.now(),
        timestamp: new Date().toLocaleTimeString(),
        agent: 'system',
        level: 'warning',
        message: '已断开 SSE 连接',
      },
    ])
  }

  const handleClear = () => {
    setLogs([])
  }

  // Simulate a log when not connected (development fallback)
  const handleSimulate = () => {
    const agents = ['Research Agent', 'Strategy Agent', 'Data Agent', 'Monitor Agent']
    const levels = ['info', 'success', 'warning', 'error']
    const messages = [
      '正在执行任务分析...',
      '数据提取完成',
      'API 响应延迟较高',
      '任务调度异常，正在重试',
      '策略回测已完成',
      '知识库索引更新中',
      '新事件已捕获',
      '模型推理完成',
    ]
    setLogs((prev) => [
      ...prev,
      {
        id: Date.now(),
        timestamp: new Date().toLocaleTimeString(),
        agent: agents[Math.floor(Math.random() * agents.length)],
        level: levels[Math.floor(Math.random() * levels.length)],
        message: messages[Math.floor(Math.random() * messages.length)],
      },
    ])
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>
          <RobotOutlined style={{ marginRight: 8 }} />
          智能体控制台
        </h2>
        <Space>
          <Badge status={isConnected ? 'success' : 'default'} text={isConnected ? '已连接' : '未连接'} />
          {!isConnected ? (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleConnect}>
              连接
            </Button>
          ) : (
            <Button danger icon={<StopOutlined />} onClick={handleDisconnect}>
              断开
            </Button>
          )}
          <Button
            icon={paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? '继续' : '暂停'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={handleClear}>
            清空
          </Button>
          <Button onClick={handleSimulate}>模拟日志</Button>
        </Space>
      </div>

      <Card
        style={{
          background: '#1a1a2e',
          borderRadius: 8,
          fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace",
          fontSize: 13,
        }}
        bodyStyle={{ padding: 0 }}
      >
        <div
          ref={logContainerRef}
          onScroll={handleScroll}
          style={{
            height: 'calc(100vh - 220px)',
            overflow: 'auto',
            padding: '12px 16px',
          }}
        >
          {logs.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <Text style={{ color: '#888' }}>
                  暂无日志，点击「连接」或「模拟日志」开始
                </Text>
              }
            />
          ) : (
            logs.map((entry) => (
              <div
                key={entry.id}
                style={{
                  display: 'flex',
                  gap: 12,
                  padding: '2px 0',
                  lineHeight: '22px',
                  color:
                    entry.level === 'error'
                      ? '#ff4d4f'
                      : entry.level === 'warning'
                      ? '#faad14'
                      : entry.level === 'success'
                      ? '#52c41a'
                      : '#e0e0e0',
                }}
              >
                <span style={{ color: '#666', flexShrink: 0, width: 80 }}>
                  {entry.timestamp}
                </span>
                <Tag
                  color={SEVERITY_COLORS[entry.level] || 'default'}
                  style={{ fontSize: 11, lineHeight: '18px', flexShrink: 0 }}
                >
                  {entry.agent}
                </Tag>
                <span style={{ wordBreak: 'break-all' }}>{entry.message}</span>
              </div>
            ))
          )}
          <div ref={logEndRef} />
        </div>
      </Card>
    </div>
  )
}
