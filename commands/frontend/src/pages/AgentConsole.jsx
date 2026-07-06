import { useState, useEffect, useRef } from 'react'
import { Card, Table, Tag, Button, Row, Col, Statistic, Spin, Descriptions, Empty } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

export default function AgentConsole() {
  const [sessions, setSessions] = useState([])
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const answerRef = useRef(null)

  const load = () => {
    setLoading(true)
    fetch(`${API}/api/agent-console/sessions?limit=50`).then(r => r.json()).then(d => {
      setSessions(d.sessions || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [])

  const showDetail = async (sid) => {
    const r = await fetch(`${API}/api/agent-console/sessions/${sid}`)
    const d = await r.json()
    setDetail(d)
    setSelected(sid)
  }

  useEffect(() => { if (answerRef.current) answerRef.current.scrollTop = answerRef.current.scrollHeight }, [detail?.answer])

  const cols = [
    { title: 'Session', dataIndex: 'id', key: 'id', width: 140, render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 100, render: v => <Tag color={v === 'claude_code' ? 'blue' : v === 'hermes_auto' ? 'purple' : 'green'}>{v?.split('_')[0] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 70, render: v => <Tag color={v === 'completed' ? 'success' : v === 'running' ? 'processing' : 'default'}>{v}</Tag> },
    { title: '时长', dataIndex: 'duration', key: 'd', width: 60 },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '时间', dataIndex: 'updated_at', key: 't', width: 100 },
    { title: '操作', key: 'act', width: 70, render: (_, r) => <Button size="small" type={selected === r.id ? 'primary' : 'default'} onClick={() => showDetail(r.id)}>查看</Button> },
  ]

  return <div>
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>💬 Agent Console — Session 列表</span>}
      extra={<Button size="small" onClick={load}>🔄 刷新</Button>} style={cardStyle}>
      {loading ? <Spin /> : <Table dataSource={sessions} columns={cols} rowKey="id" size="small"
        pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无 session' }} />}
    </Card>

    {detail && <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>Session: {detail.session_id?.slice(0,30)}</span>} style={cardStyle}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}><Statistic title="Agent" value={detail.agent} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={5}><Statistic title="版本" value={detail.version || '-'} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={5}><Statistic title="状态" value={detail.status} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={5}><Statistic title="耗时" value={detail.duration || '-'} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={5}><Statistic title="Git" value={detail.git_commit?.slice(0,7) || '-'} valueStyle={{ fontSize: 12 }} /></Col>
      </Row>

      <h4 style={{ color: '#0F172A', marginBottom: 8 }}>Prompt</h4>
      <div style={{ background: '#F8FAFC', padding: 10, borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#64748B' }}>{detail.prompt || '(空)'}</div>

      <h4 style={{ color: '#0F172A', marginBottom: 8 }}>回答</h4>
      <div ref={answerRef} style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 16, minHeight: 200, maxHeight: 400, overflow: 'auto' }}>
        {detail.answer ? <Markdown remarkPlugins={[remarkGfm]}>{detail.answer}</Markdown> : <span style={{ color: '#94A3B8' }}>无回答</span>}
      </div>

      {detail.diagnostics?.length > 0 && <details style={{ marginTop: 16 }}>
        <summary style={{ color: '#64748B', cursor: 'pointer', fontSize: 12 }}>📋 诊断日志 ({detail.diagnostics.length} 条)</summary>
        <pre style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 10, marginTop: 8, fontSize: 12, maxHeight: 200, overflow: 'auto', color: '#64748B' }}>
          {detail.diagnostics.join('\n')}
        </pre>
      </details>}
    </Card>}
  </div>
}
