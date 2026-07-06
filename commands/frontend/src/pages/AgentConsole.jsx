import { useState, useEffect, useRef } from 'react'
import { Card, Tag, Spin } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12, marginBottom: 16 }

export default function AgentConsole() {
  const [status, setStatus] = useState(null)
  const [answer, setAnswer] = useState('')
  const [diag, setDiag] = useState('')
  const [agent, setAgent] = useState('?')
  const answerRef = useRef(null)
  const [autoConnected, setAutoConnected] = useState(false)

  // 轮询状态，检测运行中 session
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/status`);
        const d = await r.json();
        setStatus(d);
        // 有 running lock 时自动连接最新 session
        if (d.health?.lock_status === 'running' && !autoConnected) {
          tryConnectLatest();
        }
      } catch (e) {}
    }, 3000);
    return () => clearInterval(t);
  }, [autoConnected]);

  const tryConnectLatest = async () => {
    try {
      const r = await fetch(`${API}/api/agent-console/sessions?limit=5`);
      const d = await r.json();
      if (d.sessions?.length > 0) {
        // 找 running 状态的 session
        const running = d.sessions.find(s => s.status === 'running') || d.sessions[0];
        setAgent(running.agent || '?');
        setAutoConnected(true);
        // 开始轮询 session 内容
        pollSession(running.id);
      }
    } catch (e) {}
  };

  const pollSession = (sid) => {
    const t = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/agent-console/sessions/${sid}`);
        const d = await r.json();
        if (d.answer) setAnswer(d.answer);
        if (d.events) {
          const last = d.events[d.events.length - 1];
          if (last.type === 'done' || last.status === 'completed') {
            setAutoConnected(false);
            clearInterval(t);
          }
          // 显示最近的诊断
          const diags = d.events.filter(e => e.type === 'diagnostic').slice(-20);
          if (diags.length) setDiag(diags.map(e => e.data).join('\n'));
        }
      } catch (e) {}
    }, 2000);
  };

  useEffect(() => { if (answerRef.current) answerRef.current.scrollTop = answerRef.current.scrollHeight }, [answer]);

  const h = status?.health || {};
  const isRunning = h.lock_status === 'running';
  const agentLabel = { hermes_demo: 'Hermes Agent (演示)', hermes_research: 'Hermes Agent (研究)', claude_code: 'Claude Code (缓冲)' };

  return <div>
    <Card style={cardStyle}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <Tag color={isRunning ? 'processing' : 'default'} style={{ fontSize: 13, padding: '4px 12px' }}>
          {isRunning ? '⚡ 版本推进中' : '⏸️ 空闲'}
        </Tag>
        <Tag color={agent === 'claude_code' ? 'blue' : 'green'}>{agentLabel[agent] || agent}</Tag>
        <span style={{ color: '#9aa7c7', fontSize: 12 }}>Lock: {h.lock_status}</span>
        <span style={{ color: '#9aa7c7', fontSize: 12 }}>tick: {h.tick_count}</span>
        {autoConnected && <span style={{ color: '#7df0bd', fontSize: 12 }}>🔄 自动追踪中</span>}
      </div>
    </Card>

    <Card style={cardStyle} title={<span style={{ color: '#cdd6f8' }}>💬 Agent 实时回答</span>}>
      {!answer && !isRunning && <p style={{ color: '#9aa7c7' }}>等待版本推进任务开始，页面将自动追踪 Agent 输出...</p>}
      <div ref={answerRef} style={{
        background: '#080d1c', padding: 16, borderRadius: 8,
        minHeight: 300, maxHeight: 500, overflow: 'auto',
        border: '1px solid #26304f'
      }}>
        {answer ? <Markdown remarkPlugins={[remarkGfm]} components={{
          code: ({ children }) => <code style={{ background: '#1a2340', padding: '2px 6px', borderRadius: 4, color: '#e8ecf8' }}>{children}</code>,
          pre: ({ children }) => <pre style={{ background: '#0b1020', padding: 12, borderRadius: 8, overflow: 'auto' }}>{children}</pre>,
        }}>{answer}</Markdown> : (isRunning ? <p style={{ color: '#9aa7c7' }}>⏳ 等待 Agent 输出...</p> : '')}
      </div>
    </Card>

    <details style={{ marginBottom: 16 }}>
      <summary style={{ color: '#9aa7c7', cursor: 'pointer', fontSize: 12, padding: '8px 0' }}>
        📋 诊断/日志 {diag ? `(${diag.split('\n').length} 行)` : ''}
      </summary>
      <pre style={{ background: '#080d1c', color: '#9aa7c7', padding: 10, borderRadius: 8, fontSize: 12, maxHeight: 300, overflow: 'auto', marginTop: 8, border: '1px solid #26304f' }}>{diag || '无日志'}</pre>
    </details>
  </div>
}
