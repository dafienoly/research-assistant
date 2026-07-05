import { useState, useEffect } from 'react'
import { Card, Table, Tag, Badge, Spin, Button, message, Modal, Select } from 'antd'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12 }

export default function Roadmap() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const load = () => fetch(`${API}/api/roadmap/versions`).then(r => r.json()).then(setData).catch(() => {}).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  const mark = async (version, status) => {
    await fetch(`${API}/api/roadmap/versions/mark`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version, status })
    })
    message.success(`${version} → ${status}`)
    load()
  }

  if (loading) return <Spin />
  const versions = data?.versions || []
  const cursor = data?.cursor || {}

  const cols = [
    { title: '版本', dataIndex: 'version', key: 'v', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'n', width: 200 },
    { title: '目标', dataIndex: 'objective', key: 'o' },
    { title: '状态', dataIndex: 'status', key: 's', width: 100,
      render: (v, r) => {
        if (r.version === cursor.current_version) return <Tag color="blue">▶ 当前</Tag>
        if (v === 'completed') return <Tag color="green">✅ 完成</Tag>
        if (v === 'failed') return <Tag color="red">❌ 失败</Tag>
        return <Tag color="default">⏳ 待办</Tag>
      }
    },
    { title: '自动', dataIndex: 'auto_allowed', key: 'a', width: 50, render: v => v ? '✅' : '❌' },
    { title: '操作', key: 'action', width: 160,
      render: (_, r) => <span>
        {r.status !== 'completed' && <Button size="small" onClick={() => mark(r.version, 'completed')} style={{ marginRight: 4 }}>完成</Button>}
        {r.status !== 'failed' && <Button size="small" danger onClick={() => mark(r.version, 'failed')}>失败</Button>}
      </span>
    },
  ]

  return <Card style={cardStyle} title={<span style={{ color: '#cdd6f8' }}>🗺️ 固定路线图</span>}>
    <p style={{ color: '#9aa7c7', fontSize: 12, marginBottom: 12 }}>
      当前: {cursor.current_version} | 已完成: {cursor.completed_versions?.length || 0} | 允许至: {cursor.auto_allowed_until}
    </p>
    <Table dataSource={versions} columns={cols} rowKey="version" size="small" pagination={{ pageSize: 15 }}
      style={{ background: 'transparent' }} />
  </Card>
}
