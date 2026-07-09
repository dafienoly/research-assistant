import { useState, useEffect, useCallback } from 'react'
import { Card, Table, Tag, Button, message, Modal, Descriptions } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import StatusDot from '../components/common/StatusDot'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

interface SessionItem {
  id: string
  version?: string
  agent?: string
  status?: string
  prompt?: string
  updated_at?: string
}

interface BackupItem {
  id: string
  version?: string
  agent?: string
  status?: string
  prompt?: string
  backed_up_at?: string
}

interface SessionDetail {
  session_id: string
  agent: string
  status: string
  version?: string
  duration?: string
  git_commit?: string
  prompt: string
  answer: string
}

interface SessionsResponse {
  sessions?: SessionItem[]
}

interface BackupsResponse {
  backups?: BackupItem[]
}

const STATUS_DOT_MAP: Record<string, 'running' | 'idle' | 'error' | 'warning'> = {
  completed: 'idle',
  running: 'running',
  failed: 'error',
  pending: 'warning',
}

export default function SessionHistory() {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [backups, setBackups] = useState<BackupItem[]>([])
  const [loadingS, setLoadingS] = useState(true)
  const [loadingB, setLoadingB] = useState(true)
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoadingS(true); setLoadingB(true); setError(null)
    fetch(`${API}/api/agent-console/sessions?limit=100`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as unknown as SessionsResponse })
      .then(d => { setSessions(d.sessions || []); setLoadingS(false) })
      .catch((e: Error) => { setError(e.message); setLoadingS(false) })
    fetch(`${API}/api/agent-console/backups`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as unknown as BackupsResponse })
      .then(d => { setBackups(d.backups || []); setLoadingB(false) })
      .catch((e: Error) => { setError(e.message); setLoadingB(false) })
  }, [])

  useEffect(() => { load() }, [load])

  const showDetail = async (sid: string) => {
    try {
      const r = await fetch(`${API}/api/agent-console/sessions/${sid}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setDetail(await r.json() as SessionDetail)
    } catch (e) {
      message.error('加载 session 详情失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const doBackup = async (sid: string) => {
    try {
      const r = await fetch(`${API}/api/agent-console/sessions/${sid}/backup`, { method: 'POST' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      message.success('已备份')
      load()
    } catch (e) {
      message.error('备份失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const doRestore = async (bid: string) => {
    try {
      const r = await fetch(`${API}/api/agent-console/backups/${bid}/restore`, { method: 'POST' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      message.success('已恢复')
      load()
    } catch (e) {
      message.error('恢复失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const getDotStatus = (v?: string): 'running' | 'idle' | 'error' | 'warning' =>
    STATUS_DOT_MAP[v || ''] || 'idle'

  const scols = [
    { title: 'Session', dataIndex: 'id', key: 'id', width: 140, render: (v: string) => <code style={{ color: '#2563EB', fontSize: 11 }}>{v?.slice(0, 24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 80, render: (v: string) => <Tag color={v === 'claude_code' ? 'blue' : 'green'}>{v?.split('_')[0] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 80, render: (v: string) => <span><StatusDot status={getDotStatus(v)} size={7} /> <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag></span> },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '时间', dataIndex: 'updated_at', key: 't', width: 100 },
    { title: '操作', key: 'act', width: 140, render: (_: unknown, r: SessionItem) => <span>
      <Button size="small" onClick={() => showDetail(r.id)} style={{ marginRight: 4 }}>详情</Button>
      <Button size="small" onClick={() => doBackup(r.id)}>备份</Button>
    </span> },
  ]

  const bcols = [
    { title: '备份 ID', dataIndex: 'id', key: 'id', width: 140, render: (v: string) => <code style={{ color: '#2563EB', fontSize: 11 }}>{v?.slice(0, 24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 80 },
    { title: '状态', dataIndex: 'status', key: 's', width: 80, render: (v: string) => <span><StatusDot status={getDotStatus(v)} size={7} /> <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag></span> },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '备份时间', dataIndex: 'backed_up_at', key: 'bt', width: 100 },
    { title: '操作', key: 'act', width: 100, render: (_: unknown, r: BackupItem) => <Button size="small" type="primary" onClick={() => doRestore(r.id)}>恢复</Button> },
  ]

  return <div className="stagger-fade">
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>📜 Session 列表</span>}
      extra={<Button size="small" onClick={load}>🔄 刷新</Button>} style={cardStyle}>
      {error ? <ErrorState message="加载失败" description={error} onRetry={load} /> : null}
      {loadingS ? <LoadingState size="small" /> : <Table dataSource={sessions} columns={scols} rowKey="id" size="small" pagination={{ pageSize: 15 }}
        locale={{ emptyText: '暂无 session' }} />}
    </Card>

    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>💾 备份列表</span>}
      extra={<Button size="small" onClick={load}>🔄 刷新</Button>} style={cardStyle}>
      {loadingB ? <LoadingState size="small" /> : <Table dataSource={backups} columns={bcols} rowKey="id" size="small" pagination={{ pageSize: 15 }}
        locale={{ emptyText: '暂无备份' }} />}
    </Card>

    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={700}
      title={<span style={{ color: '#0F172A' }}>Session: {detail?.session_id?.slice(0, 30)}</span>}>
      {detail && <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="Agent">{detail.agent}</Descriptions.Item>
          <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
          <Descriptions.Item label="版本">{detail.version || '-'}</Descriptions.Item>
          <Descriptions.Item label="耗时">{detail.duration || '-'}</Descriptions.Item>
          <Descriptions.Item label="Git">{detail.git_commit?.slice(0, 30) || '-'}</Descriptions.Item>
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
