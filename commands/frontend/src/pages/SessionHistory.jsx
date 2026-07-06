import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, message, Spin, Modal, Descriptions } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

export default function SessionHistory() {
  const [sessions, setSessions] = useState([])
  const [backups, setBackups] = useState([])
  const [loadingS, setLoadingS] = useState(true)
  const [loadingB, setLoadingB] = useState(true)
  const [detail, setDetail] = useState(null)

  const load = () => {
    setLoadingS(true); setLoadingB(true)
    fetch(`${API}/api/agent-console/sessions?limit=100`).then(r => r.json()).then(d => { setSessions(d.sessions || []); setLoadingS(false) })
    fetch(`${API}/api/agent-console/backups`).then(r => r.json()).then(d => { setBackups(d.backups || []); setLoadingB(false) })
  }

  useEffect(() => { load() }, [])

  const showDetail = async (sid) => {
    const r = await fetch(`${API}/api/agent-console/sessions/${sid}`)
    setDetail(await r.json())
  }

  const doBackup = async (sid) => {
    await fetch(`${API}/api/agent-console/sessions/${sid}/backup`, { method: 'POST' })
    message.success(`已备份`)
    load()
  }

  const doRestore = async (bid) => {
    await fetch(`${API}/api/agent-console/backups/${bid}/restore`, { method: 'POST' })
    message.success(`已恢复`)
    load()
  }

  const scols = [
    { title: 'Session', dataIndex: 'id', key: 'id', width: 140, render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 80, render: v => <Tag color={v === 'claude_code' ? 'blue' : 'green'}>{v?.split('_')[0] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 70, render: v => <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag> },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '时间', dataIndex: 'updated_at', key: 't', width: 100 },
    { title: '操作', key: 'act', width: 140, render: (_, r) => <span>
      <Button size="small" onClick={() => showDetail(r.id)} style={{ marginRight: 4 }}>详情</Button>
      <Button size="small" onClick={() => doBackup(r.id)}>备份</Button>
    </span> },
  ]

  const bcols = [
    { title: '备份 ID', dataIndex: 'id', key: 'id', width: 140, render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 80 },
    { title: '状态', dataIndex: 'status', key: 's', width: 70, render: v => <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag> },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '备份时间', dataIndex: 'backed_up_at', key: 'bt', width: 100 },
    { title: '操作', key: 'act', width: 100, render: (_, r) => <Button size="small" type="primary" onClick={() => doRestore(r.id)}>恢复</Button> },
  ]

  return <div>
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>📜 Session 列表</span>}
      extra={<Button size="small" onClick={load}>🔄 刷新</Button>} style={cardStyle}>
      {loadingS ? <Spin /> : <Table dataSource={sessions} columns={scols} rowKey="id" size="small" pagination={{ pageSize: 15 }}
        locale={{ emptyText: '暂无 session' }} />}
    </Card>

    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>💾 备份列表</span>}
      extra={<Button size="small" onClick={load}>🔄 刷新</Button>} style={cardStyle}>
      {loadingB ? <Spin /> : <Table dataSource={backups} columns={bcols} rowKey="id" size="small" pagination={{ pageSize: 15 }}
        locale={{ emptyText: '暂无备份' }} />}
    </Card>

    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={700}
      title={<span style={{ color: '#0F172A' }}>Session: {detail?.session_id?.slice(0,30)}</span>}>
      {detail && <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="Agent">{detail.agent}</Descriptions.Item>
          <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
          <Descriptions.Item label="版本">{detail.version || '-'}</Descriptions.Item>
          <Descriptions.Item label="耗时">{detail.duration || '-'}</Descriptions.Item>
          <Descriptions.Item label="Git">{detail.git_commit?.slice(0,30) || '-'}</Descriptions.Item>
          <Descriptions.Item label="Prompt" span={2}>{detail.prompt}</Descriptions.Item>
        </Descriptions>
        <h4 style={{ color: '#0F172A', marginTop: 16 }}>回答</h4>
        <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 12, maxHeight: 300, overflow: 'auto', marginTop: 8 }}>
          <Markdown remarkPlugins={[remarkGfm]}>{detail.answer || '(无回答)'}</Markdown>
        </div>
      </div>}
    </Modal>
  </div>
}
