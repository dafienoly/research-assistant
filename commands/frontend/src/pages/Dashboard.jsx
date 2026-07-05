import { useState, useEffect } from 'react'
import { Card, Row, Col, Statistic, Table, Tag, Spin, Alert, Descriptions } from 'antd'
import { API } from '../App'

const darkCard = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12, marginBottom: 16 }
const labelStyle = { color: '#9aa7c7', fontSize: 12 }
const valStyle = { color: '#e8ecf8', fontSize: 13, fontFamily: 'monospace' }

function Metric({ label, value, color }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #25304c' }}>
    <span style={labelStyle}>{label}</span>
    <span style={{ ...valStyle, color: color || '#e8ecf8' }}>{String(value ?? '-')}</span>
  </div>
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    fetch(`${API}/api/status`).then(r => r.json()).then(setData).catch(e => setErr(e.message))
    const t = setInterval(() => fetch(`${API}/api/status`).then(r => r.json()).then(setData).catch(() => {}), 5000)
    return () => clearInterval(t)
  }, [])
  if (err) return <Alert type="error" message={`无法连接 FastAPI (${API})`} description={err} />
  if (!data) return <Spin style={{ display: 'block', marginTop: 80 }} />

  const s = data.state || {}
  const h = data.health || {}
  const c = data.cursor || {}
  const l = data.latest || {}
  const r = data.report || {}
  const be = data.backend || {}
  const bg = s.level === 'green' ? '#0f3d2e' : s.level === 'red' ? '#4a1620' : '#44380c'
  const fg = s.level === 'green' ? '#7df0bd' : s.level === 'red' ? '#ff8ba0' : '#ffdc7a'

  const cols = [
    { title: '版本', dataIndex: 'version', key: 'v' },
    { title: '名称', dataIndex: 'name', key: 'n' },
    { title: '状态', dataIndex: 'status', key: 's',
      render: v => <Tag color={v === 'completed' ? 'green' : v === 'current' ? 'blue' : v === 'failed' ? 'red' : 'default'}>{v}</Tag> },
    { title: '自动', dataIndex: 'auto_allowed', key: 'a', render: v => v ? '✅' : '❌' },
    { title: '人工', dataIndex: 'manual_required', key: 'm', render: v => v ? '⚠️' : '—' },
  ]

  return <div>
    <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
      <span style={{ background: bg, color: fg, padding: '6px 14px', borderRadius: 999, fontWeight: 700, fontSize: 13 }}>
        {s.level === 'green' ? '✅ 正常' : s.level === 'red' ? '❌ 异常' : '⚠️ 警告'}
      </span>
      <span style={{ color: '#9aa7c7', fontSize: 12 }}>{h.checked_at || ''}</span>
    </div>

    <Row gutter={16}>
      <Col span={8}><Card style={darkCard}><h3 style={{ color: '#cdd6f8', fontSize: 14, margin: '0 0 12px' }}>🚀 版本推进</h3>
        <Metric label="当前版本" value={c.current_version} />
        <Metric label="已完成" value={r.total_completed} />
        <Metric label="失败的版本" value={r.total_failed} color={r.total_failed > 0 ? '#ff8ba0' : undefined} />
        <Metric label="自动允许至" value={c.auto_allowed_until} />
      </Card></Col>
      <Col span={8}><Card style={darkCard}><h3 style={{ color: '#cdd6f8', fontSize: 14, margin: '0 0 12px' }}>🔒 系统状态</h3>
        <Metric label="Lock" value={h.lock_status} color={h.lock_status === 'free' ? '#7df0bd' : '#ff8ba0'} />
        <Metric label="Cron" value={h.cron_service_running ? '✅ running' : '❌ stopped'} />
        <Metric label="Tick 计数" value={h.tick_count} />
        <Metric label="Latest.json" value={l.current || '-'} />
      </Card></Col>
      <Col span={8}><Card style={darkCard}><h3 style={{ color: '#cdd6f8', fontSize: 14, margin: '0 0 12px' }}>⚡ Backend</h3>
        <Metric label="后端" value={be.claude_bin_path || 'dry-run'} />
        <Metric label="Coding Backend" value={be.coding_backend_configured ? '✅ 已配置' : '❌ 未配置'} />
        <Metric label="Cron Safe" value={be.cron_safe ? '✅' : '❌'} />
      </Card></Col>
    </Row>

    <Card style={darkCard} title={<span style={{ color: '#cdd6f8' }}>📋 版本列表</span>}>
      <Table dataSource={r.versions || []} columns={cols} rowKey="version" pagination={false}
        size="small" style={{ background: 'transparent' }}
        locale={{ emptyText: <span style={{ color: '#9aa7c7' }}>无数据</span> }} />
    </Card>
  </div>
}
