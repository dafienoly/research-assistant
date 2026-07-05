import { useState, useEffect } from 'react'
import { Card, Table, Tag, Spin } from 'antd'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12 }

export default function SessionHistory() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 通过 FastAPI 获取 session 列表
    setLoading(false)
    // TODO: 添加 /api/agent-console/sessions 列表端点
  }, [])

  const cols = [
    { title: 'Session ID', dataIndex: 'id', key: 'id' },
    { title: '状态', dataIndex: 'status', key: 'status', render: v => <Tag color={v === 'completed' ? 'green' : v === 'failed' ? 'red' : 'default'}>{v}</Tag> },
    { title: '时间', dataIndex: 'updated_at', key: 't' },
  ]

  return <Card title={<span style={{ color: '#cdd6f8' }}>📜 Session 历史</span>} style={cardStyle}>
    <p style={{ color: '#9aa7c7', fontSize: 13 }}>需要 FastAPI 添加 `/api/agent-console/sessions` GET 列表端点。</p>
    <Table dataSource={sessions} columns={cols} rowKey="id" size="small" locale={{ emptyText: <span style={{ color: '#9aa7c7' }}>暂无数据</span> }} />
  </Card>
}
