import { useState, useRef, useEffect } from 'react'
import { Card, Button, Select, Tag, Typography, Input } from 'antd'
import { API } from '../App'

const { TextArea } = Input
const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12, marginBottom: 16 }

export default function AgentConsole() {
  const [agent, setAgent] = useState('hermes_research')
  const [prompt, setPrompt] = useState('')
  const [sid, setSid] = useState(null)
  const [answer, setAnswer] = useState('')
  const [diag, setDiag] = useState('')
  const [status, setStatus] = useState('idle')
  const [hint, setHint] = useState('')
  const answerRef = useRef(null)
  const esRef = useRef(null)

  const adapters = {
    hermes_demo: { label: 'Hermes Agent (演示)', hint: '缓冲模式 — dry-run' },
    hermes_research: { label: 'Hermes Agent (研究)', hint: '运行投研命令' },
    claude_code: { label: 'Claude Code', hint: '缓冲模式 — 命令完成后输出' },
  }

  const start = async () => {
    if (!prompt.trim()) return
    setAnswer(''); setDiag(''); setStatus('running')
    const a = adapters[agent] || {}
    setHint(a.hint || '')
    try {
      const r = await fetch(`${API}/api/agent-console/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent, prompt })
      })
      const d = await r.json()
      setSid(d.session_id)
      connectSSE(d.session_id)
    } catch (e) { setStatus('error'); setAnswer('启动失败: ' + e.message) }
  }

  const connectSSE = (sid) => {
    if (esRef.current) esRef.current.close()
    const es = new EventSource(`${API}/api/agent-console/sessions/${sid}/stream`)
    esRef.current = es
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data)
        if (d.type === 'answer_delta') { setAnswer(p => p + d.data) }
        else if (d.type === 'diagnostic') { setDiag(p => p + d.data + '\n') }
        else if (d.type === 'error') { setAnswer(p => p + '\n[错误] ' + d.data) }
        else if (d.type === 'done') { setStatus(d.status || 'completed'); es.close() }
      } catch (e) {}
    }
    es.onerror = () => { setStatus('completed'); es.close() }
  }

  const cancel = async () => {
    if (sid) await fetch(`${API}/api/agent-console/sessions/${sid}/cancel`, { method: 'POST' })
    setStatus('cancelled')
  }

  useEffect(() => { if (answerRef.current) answerRef.current.scrollTop = answerRef.current.scrollHeight }, [answer])

  const tagColor = { idle: 'default', running: 'processing', completed: 'success', error: 'error', cancelled: 'warning' }

  return <div>
    <Card style={cardStyle}>
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Select value={agent} onChange={setAgent} style={{ width: 220 }}
          options={Object.entries(adapters).map(([k, v]) => ({ value: k, label: v.label }))} />
        <span style={{ color: '#9aa7c7', fontSize: 12 }}>{hint}</span>
        <Button type="primary" onClick={start} disabled={status === 'running'}>开始</Button>
        <Button onClick={cancel} disabled={status !== 'running'}>取消</Button>
        <Tag color={tagColor[status]}>{status}</Tag>
      </div>
      <TextArea rows={3} value={prompt} onChange={e => setPrompt(e.target.value)}
        placeholder="输入投研或开发任务..." style={{ background: '#080d1c', color: '#e8ecf8', border: '1px solid #26304f' }} />
    </Card>
    <Card style={cardStyle} title={<span style={{ color: '#cdd6f8' }}>💬 回答</span>}>
      <pre ref={answerRef} style={{ background: '#121a35', color: '#e8ecf8', padding: 16, borderRadius: 8, minHeight: 200, maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.6, border: '1px solid #26304f' }}>{answer || '等待输入...'}</pre>
    </Card>
    {diag && <details style={{ marginTop: 8 }}><summary style={{ color: '#9aa7c7', cursor: 'pointer', fontSize: 12 }}>📋 诊断信息</summary>
      <pre style={{ background: '#080d1c', color: '#9aa7c7', padding: 10, borderRadius: 8, fontSize: 12, maxHeight: 200, overflow: 'auto', marginTop: 8 }}>{diag}</pre>
    </details>}
  </div>
}
