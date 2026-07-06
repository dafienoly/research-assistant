import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, message, Descriptions, Modal, Spin } from 'antd'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12 }

export default function Roadmap() {
  const [data, setData] = useState(null)
  const [detail, setDetail] = useState(null)
  const load = () => fetch(`${API}/api/roadmap/versions`).then(r => r.json()).then(setData)
  useEffect(() => { load() }, [])
  const mark = async (version, status) => {
    await fetch(`${API}/api/roadmap/versions/mark`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version, status })
    })
    message.success(`${version} → ${status}`)
    load()
  }
  if (!data) return <Spin />
  const versions = data.versions || []
  const cursor = data.cursor || {}

  const cols = [
    { title: '版本', dataIndex: 'version', key: 'v', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'n', width: 160 },
    { title: '目标', dataIndex: 'objective', key: 'o', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 's', width: 100,
      render: (v, r) => {
        if (r.version === cursor.current_version) return <Tag color="blue">▶ 当前</Tag>
        if (v === 'completed') return <Tag color="green">✅ 完成</Tag>
        if (v === 'failed') return <Tag color="red">❌ 失败</Tag>
        return <Tag color="default">⏳ 待办</Tag>
      }
    },
    { title: '自动', dataIndex: 'auto_allowed', key: 'a', width: 50, render: v => v ? '✅' : '❌' },
    { title: '交易模式', dataIndex: 'trading_mode', key: 'tm', width: 100 },
    { title: '操作', key: 'action', width: 160,
      render: (_, r) => <span>
        {r.status !== 'completed' && <Button size="small" onClick={() => mark(r.version, 'completed')} style={{ marginRight: 4 }}>完成</Button>}
        {r.status !== 'failed' && <Button size="small" danger onClick={() => mark(r.version, 'failed')}>失败</Button>}
      </span>
    },
  ]

  return <Card title={<span style={{ color: '#cdd6f8' }}>🗺️ 固定路线图 <span style={{ fontSize: 12, color: '#9aa7c7' }}>(点击版本查看详情)</span></span>} style={cardStyle}>
    <p style={{ color: '#9aa7c7', fontSize: 12, marginBottom: 12 }}>
      当前: {cursor.current_version} | 已完成: {cursor.completed_versions?.length || 0} | 允许至: {cursor.auto_allowed_until}
    </p>
    <Table dataSource={versions} columns={cols} rowKey="version" size="small" pagination={{ pageSize: 15 }}
      onRow={v => ({ onClick: () => setDetail(v), style: { cursor: 'pointer' } })} />
    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={560}
      title={<span style={{ color: '#cdd6f8' }}>{detail?.version} — {detail?.name}</span>}>
      {detail && <Descriptions column={1} size="small" bordered
        styles={{ label: { background: '#121a35', color: '#9aa7c7' }, content: { background: '#0b1020', color: '#e8ecf8' } }}>
        {Object.entries(detail).map(([k, v]) => (
          <Descriptions.Item label={k} key={k}>{String(v)}</Descriptions.Item>
        ))}
      </Descriptions>}
    </Modal>
  </Card>
}
