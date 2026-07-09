import { useState, useEffect, useRef, useCallback } from 'react'
import { Card, Table, Tag, Button, Row, Col, Statistic, Tooltip } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import StatusDot from '../components/common/StatusDot'

// ─── Types ──────────────────────────────────────────────────────────
interface SessionEvent {
  type: string
  data: string
  timestamp?: string
}

interface EventGroup {
  agent: string
  label: string
  color: string
  items: SessionEvent[]
}

interface SessionRow {
  id: string
  version?: string
  agent?: string
  status?: string
  duration?: string
  prompt?: string
  updated_at?: string
}

interface SessionDetail {
  session_id: string
  agent?: string
  version?: string
  status: string
  duration?: string
  git_commit?: string
  startup_params?: { backend?: string }
  prompt?: string
  events?: SessionEvent[]
  diagnostics?: string[]
  answer?: string
}

// ─── Style constants ────────────────────────────────────────────────
const cardStyle: React.CSSProperties = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

const agentTagBase: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
  padding: '4px 10px', borderRadius: 6,
}

const contentBox: React.CSSProperties = {
  background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8,
  padding: '12px 16px', fontSize: 14, lineHeight: 1.6,
}

// ─── 识别每段输出是谁产生的 ───
function classifyEvent(data: string | undefined | null): { agent: string; label: string; color: string } | null {
  if (!data) return { agent: 'unknown', label: 'unknown', color: '#94A3B8' }
  if (data.startsWith('## Claude Code')) return { agent: 'pty_adapter', label: 'PTY 适配器 (启动)', color: '#8B5CF6' }
  if (data.includes('## 🤖 Claude Code 工作输出')) return { agent: 'log_injection', label: 'Claude Code 工作日志 (注入)', color: '#2563EB' }
  if (data.includes('## ✅ 版本') && data.includes('完成')) return { agent: 'hermes', label: 'Hermes Agent (完成总结)', color: '#059669' }
  if (data.includes('## ❌ 版本')) return { agent: 'audit', label: '审计门禁', color: '#DC2626' }
  if (data.includes('## ⏳ 版本')) return { agent: 'hermes', label: 'Hermes Agent (进行中)', color: '#D97706' }
  if (data.includes('启动参数') || data.includes('backend')) return null // 跳过,启动参数单独展示
  return { agent: 'claude_code', label: 'Claude Code (agent-runner)', color: '#2563EB' }
}

// ─── 按来源分组相邻的事件 ───
function groupEvents(events: SessionEvent[] | undefined): EventGroup[] {
  if (!events || events.length === 0) return []
  // 只取 answer_delta 和 diagnostic
  const filtered = events.filter(e => e.type === 'answer_delta' || e.type === 'diagnostic')
  const groups: EventGroup[] = []
  let current: EventGroup | null = null
  for (const e of filtered) {
    const cls = classifyEvent(e.data)
    if (!cls) continue // 跳过
    if (!current || current.agent !== cls.agent) {
      current = { agent: cls.agent, label: cls.label, color: cls.color, items: [] }
      groups.push(current)
    }
    current.items.push(e)
  }
  return groups
}

export default function AgentConsole() {
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const answerRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const detailPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async (keepDetail = false) => {
    if (!keepDetail) setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${API}/api/agent-console/sessions?limit=50`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setSessions(d.sessions || [])
      if (!keepDetail) setLoading(false)
      if (keepDetail && selected) {
        try {
          const r2 = await fetch(`${API}/api/agent-console/sessions/${selected}`)
          if (r2.ok) setDetail(await r2.json())
        } catch { /* ignore polling errors */ }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
      if (!keepDetail) setLoading(false)
    }
  }, [selected])

  useEffect(() => {
    load()
    pollRef.current = setInterval(() => load(true), 5000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [load])

  const showDetail = useCallback(async (sid: string) => {
    setSelected(sid)
    try {
      const r = await fetch(`${API}/api/agent-console/sessions/${sid}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setDetail(await r.json())
    } catch { /* ignore polling errors */ }
  }, [])

  useEffect(() => {
    if (!selected) return
    detailPollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/agent-console/sessions/${selected}`)
        if (r.ok) setDetail(await r.json())
      } catch { /* ignore polling errors */ }
    }, 3000)
    return () => {
      if (detailPollRef.current) clearInterval(detailPollRef.current)
    }
  }, [selected])

  useEffect(() => {
    if (answerRef.current) answerRef.current.scrollTop = answerRef.current.scrollHeight
  }, [detail?.answer])

  const cols = [
    { title: 'Session', dataIndex: 'id', key: 'id', width: 140, render: (v: string) => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 100, render: (v: string) => <Tag color={v === 'claude_code' ? 'blue' : v === 'hermes_auto' ? 'purple' : 'green'}>{v?.split('_')[0] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 70, render: (v: string) => <Tag color={v === 'completed' ? 'success' : v === 'running' ? 'processing' : 'default'}>{v}</Tag> },
    { title: '时长', dataIndex: 'duration', key: 'd', width: 60 },
    { title: 'Prompt', dataIndex: 'prompt', key: 'p', ellipsis: true },
    { title: '时间', dataIndex: 'updated_at', key: 't', width: 100 },
    { title: '操作', key: 'act', width: 70, render: (_: unknown, r: SessionRow) => <Button size="small" type={selected === r.id ? 'primary' : 'default'} onClick={() => showDetail(r.id)}>查看</Button> },
  ]

  // Render grouped events as labeled blocks with inline timeline
  const renderGroupedAnswer = (groups: EventGroup[]) => {
    if (!groups || groups.length === 0) return <span style={{ color: '#94A3B8' }}>无回答</span>
    return groups.map((g: EventGroup, gi: number) => (
      <div key={gi} style={{ marginBottom: 16 }}>
        {/* Agent 标签 */}
        <div style={{
          ...agentTagBase,
          background: g.color + '15',
          borderLeft: `3px solid ${g.color}`,
        }}>
          <StatusDot status="idle" color={g.color} size={10} />
          <span style={{ fontSize: 12, fontWeight: 600, color: g.color }}>{g.label}</span>
          <span style={{ fontSize: 11, color: '#94A3B8' }}>
            {g.items[0]?.timestamp?.slice(11, 19) || ''}
            {g.items.length > 1 ? ` ~ ${g.items[g.items.length-1]?.timestamp?.slice(11,19)}` : ''}
          </span>
        </div>
        {/* 内容 + 内联时间线 */}
        <div style={contentBox}>
          {g.items.map((e: SessionEvent, ei: number) => (
            <div key={ei} style={{ marginBottom: ei < g.items.length - 1 ? 8 : 0 }}>
              {/* 每个事件的时间戳 */}
              {e.timestamp && <div style={{ fontSize: 10, color: '#CBD5E1', marginBottom: 2, fontFamily: 'monospace' }}>▸ {e.timestamp.slice(11, 19)}</div>}
              {e.type === 'diagnostic' ? (
                <div style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'monospace' }}>{e.data}</div>
              ) : (
                <Markdown remarkPlugins={[remarkGfm]}>{e.data || ''}</Markdown>
              )}
            </div>
          ))}
        </div>
      </div>
    ))
  }

  const groups = detail?.events ? groupEvents(detail.events) : []

  return <div className="stagger-fade">
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>💬 Agent Console — Session 列表</span>}
      extra={<Button size="small" onClick={() => load()}>🔄 刷新</Button>} style={cardStyle}>
      {error ? <ErrorState message="加载失败" description={error} onRetry={() => load()} /> : null}
      {loading ? <LoadingState size="large" /> : <Table dataSource={sessions} columns={cols} rowKey="id" size="small"
        pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无 session' }}
        onRow={r => ({
          style: r.status === 'running'
            ? { borderLeft: '3px solid #22C55E', background: '#F0FDF4' }
            : r.id === selected
            ? { background: '#EFF6FF' }
            : {}
        })} />}
    </Card>

    {detail && <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>Session: {detail.session_id?.slice(0,30)}</span>} style={cardStyle}>
      {/* 状态栏 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={3}><Statistic title="Agent" value={detail.agent?.split('_')[0]} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={3}><Statistic title="版本" value={detail.version || '-'} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={3}>
          <Statistic title="状态" value={detail.status} valueStyle={{
            fontSize: 16,
            color: detail.status === 'completed' ? '#059669' : detail.status === 'running' ? '#2563EB' : '#D97706'
          }} />
        </Col>
        <Col span={3}><Statistic title="耗时" value={detail.duration || '-'} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={4}><Statistic title="Git" value={detail.git_commit?.slice(0,7) || '-'} valueStyle={{ fontSize: 12 }} /></Col>
        <Col span={8}><Statistic title="后端" value={detail.startup_params?.backend || '-'} valueStyle={{ fontSize: 14 }} /></Col>
      </Row>

      {/* Prompt */}
      <h4 style={{ color: '#0F172A', marginBottom: 8 }}>📝 Prompt</h4>
      <div style={{ background: '#F8FAFC', padding: 10, borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#64748B' }}>{detail.prompt || '(空)'}</div>

      {/* 工作流进度 */}
      <div style={{ marginBottom: 16 }}>
        <h4 style={{ color: '#0F172A', marginBottom: 8 }}>⚙️ 工作流</h4>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {[
            { step: '创建 session', agent: 'Hermes', done: true },
            { step: 'PTY 适配器', agent: 'PTY', done: groups.some(g => g.agent === 'pty_adapter') },
            { step: 'Agent 运行', agent: 'Claude Code', done: groups.some(g => g.agent === 'claude_code'), running: detail.status === 'running' },
            { step: '日志注入', agent: 'Hermes', done: groups.some(g => g.agent === 'log_injection') },
            { step: '审计', agent: 'Audit', done: groups.some(g => g.agent === 'audit'), failed: groups.some(g => g.agent === 'audit') },
            { step: '完成总结', agent: 'Hermes', done: groups.some(g => g.agent === 'hermes') },
          ].map((s, i) => (
            <Tooltip key={i} title={`${s.step} — ${s.agent}`}>
              <Tag style={{ fontSize: 11, cursor: 'pointer' }} color={
                s.failed ? 'red' : s.done ? 'success' : s.running ? 'processing' : 'default'
              }>{s.step}</Tag>
            </Tooltip>
          ))}
        </div>
      </div>

      {/* 分段回答 */}
      <h4 style={{ color: '#0F172A', marginBottom: 8 }}>📄 回答（按来源分段）</h4>
      <div ref={answerRef} style={{ maxHeight: 500, overflow: 'auto', padding: '0 4px' }}>
        {renderGroupedAnswer(groups)}
      </div>

      {/* 诊断日志 */}
      {detail.diagnostics ? (
        detail.diagnostics.length > 0 && <details style={{ marginTop: 16 }}>
          <summary style={{ color: '#64748B', cursor: 'pointer', fontSize: 12 }}>📋 诊断日志 ({detail.diagnostics.length} 条)</summary>
          <pre style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 10, marginTop: 8, fontSize: 12, maxHeight: 200, overflow: 'auto', color: '#64748B' }}>
            {detail.diagnostics.join('\n')}
          </pre>
        </details>
      ) : null}
    </Card>}
  </div>
}
