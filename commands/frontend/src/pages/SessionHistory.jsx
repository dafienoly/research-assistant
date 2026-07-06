import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, message, Spin, Modal, Descriptions } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12 }

export default function SessionHistory() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null)

  const load = () => {
    setLoading(true)
    fetch(`${API}/api/agent-console/sessions?limit=100`).then(r => r.json()).then(d => {
      setSessions(d.sessions || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const doBackup = async (sid) => {
    await fetch(`${API}/api/agent-console/sessions/${sid}/backup`, { method: 'POST' })
    message.success(`已备份 ${sid.slice(0,16)}...`)
  }

  const cols = [
    { title: 'Session ID', dataIndex: 'id', key: 'id', width: 140, render: v => <code style={{ color: '#7df0bd', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 100, render: v => <Tag color={v === 'claude_code' ? 'blue' : 'green'}>{v?.split('_')[0] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 80, render: v => <Tag color={v === 'completed' ? 'green' : v === 'running' ? 'processing' : v === 'failed' ? 'red' : 'default'}>{v}</Tag> },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '回答预览', dataIndex: 'answer_preview', key: 'ap', ellipsis: true },
    { title: '时间', dataIndex: 'updated_at', key: 't', width: 120 },
    { title: '操作', key: 'act', width: 120, render: (_, r) => <span>
      <Button size="small" onClick={() => setDetail(r)} style={{ marginRight: 4 }}>详情</Button>
      <Button size="small" onClick={() => doBackup(r.id)}>备份</Button>
    </span> },
  ]

  return <div>
    <Card title={<span style={{ color: '#cdd6f8' }}>📜 Session 历史与备份</span>} style={cardStyle}
      extra={<Button size="small" onClick={load}>🔄 刷新</Button>}>
      {loading ? <Spin /> : <Table dataSource={sessions} columns={cols} rowKey="id" size="small" pagination={{ pageSize: 20 }} />}
    </Card>

    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={700}
      title={<span style={{ color: '#cdd6f8' }}>Session: {detail?.id?.slice(0,30)}</span>}>
      {detail && <div>
        <Descriptions column={1} size="small" bordered
          styles={{ label: { background: '#121a35', color: '#9aa7c7' }, content: { background: '#0b1020', color: '#e8ecf8' } }}>
          <Descriptions.Item label="Agent">{detail.agent}</Descriptions.Item>
          <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
          <Descriptions.Item label="Prompt">{detail.prompt}</Descriptions.Item>
          <Descriptions.Item label="时间">{detail.updated_at}</Descriptions.Item>
        </Descriptions>
        <h4 style={{ color: '#cdd6f8', marginTop: 16 }}>回答</h4>
        <div style={{ background: '#080d1c', padding: 12, borderRadius: 8, maxHeight: 300, overflow: 'auto' }}>
          <Markdown remarkPlugins={[remarkGfm]}>{detail.answer_preview || '(无回答)'}</Markdown>
        </div>
        <Button type="primary" style={{ marginTop: 12 }} onClick={() => doBackup(detail.id)}>💾 备份此 Session</Button>
      </div>}
    </Modal>
  </div>
}
