import { useState, useEffect } from 'react'
import { Card, Row, Col, Table, Tag, Spin, Modal, Descriptions, Empty } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [detail, setDetail] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)
  useEffect(() => {
    fetch(`${API}/api/status`).then(r => r.json()).then(setData)
    const t = setInterval(() => fetch(`${API}/api/status`).then(r => r.json()).then(setData), 5000)
    return () => clearInterval(t)
  }, [])

  const showDetail = async (v) => {
    setDetail(v)
    // 查找关联 session
    try {
      const r = await fetch(`${API}/api/agent-console/sessions?limit=200`)
      const d = await r.json()
      const match = (d.sessions || []).find(s => s.prompt?.includes(v.version))
      if (match) {
        const sr = await fetch(`${API}/api/agent-console/sessions/${match.id}`)
        setSessionDetail(await sr.json())
      } else {
        setSessionDetail(null)
      }
    } catch (e) { setSessionDetail(null) }
  }

  if (!data) return <Spin style={{ display: 'block', marginTop: 80 }} />
  const r = data.report || {}; const c = data.cursor || {}
  const h = data.health || {}
  const cols = [
    { title: '版本', dataIndex: 'version', key: 'v', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'n', width: 160 },
    { title: '状态', dataIndex: 'status', key: 's', width: 80,
      render: v => <Tag color={v === 'completed' ? 'success' : v === 'current' ? 'processing' : 'default'}>{v}</Tag> },
    { title: '目标', dataIndex: 'objective', key: 'o', ellipsis: true },
  ]

  return <div>
    <Row gutter={16}>
      <Col span={6}><Card style={cardStyle}><span style={{ color: '#64748B', fontSize: 12 }}>当前版本</span><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{c.current_version || '-'}</div></Card></Col>
      <Col span={6}><Card style={cardStyle}><span style={{ color: '#64748B', fontSize: 12 }}>已完成</span><div style={{ fontSize: 24, fontWeight: 700, color: '#059669' }}>{r.total_completed || 0}</div></Card></Col>
      <Col span={6}><Card style={cardStyle}><span style={{ color: '#64748B', fontSize: 12 }}>失败</span><div style={{ fontSize: 24, fontWeight: 700, color: r.total_failed > 0 ? '#DC2626' : '#0F172A' }}>{r.total_failed || 0}</div></Card></Col>
      <Col span={6}><Card style={cardStyle}><span style={{ color: '#64748B', fontSize: 12 }}>Lock</span><div style={{ fontSize: 24, fontWeight: 700, color: h.lock_status === 'free' ? '#059669' : '#D97706' }}>{h.lock_status || '?'}</div></Card></Col>
    </Row>

    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>📋 版本列表</span>}
      extra={<span style={{ color: '#94A3B8', fontSize: 12 }}>点击版本查看详情</span>} style={cardStyle}>
      <Table dataSource={r.versions || []} columns={cols} rowKey="version" size="small" pagination={{ pageSize: 10 }}
        onRow={v => ({ onClick: () => showDetail(v), style: { cursor: 'pointer' } })} />
    </Card>

    <Modal open={!!detail} onCancel={() => { setDetail(null); setSessionDetail(null) }} footer={null} width={800}
      title={<span style={{ color: '#0F172A', fontWeight: 600 }}>{detail?.version} — {detail?.name}</span>}>
      {detail && <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="版本">{detail.version}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={detail.status === 'completed' ? 'success' : 'default'}>{detail.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="名称" span={2}>{detail.name}</Descriptions.Item>
          <Descriptions.Item label="目标" span={2}>{detail.objective}</Descriptions.Item>
          <Descriptions.Item label="自动允许">{detail.auto_allowed ? '✅' : '❌'}</Descriptions.Item>
          <Descriptions.Item label="交易模式">{detail.trading_mode || 'research'}</Descriptions.Item>
        </Descriptions>

        {sessionDetail && <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#0F172A', marginBottom: 8 }}>🤖 Agent 开发输出</h4>
          {sessionDetail.answer ? <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 16, maxHeight: 300, overflow: 'auto' }}>
            <Markdown remarkPlugins={[remarkGfm]}>{sessionDetail.answer}</Markdown>
          </div> : <span style={{ color: '#94A3B8' }}>关联 session 无输出</span>}

          {sessionDetail.diagnostics?.length > 0 && <details style={{ marginTop: 8 }}>
            <summary style={{ color: '#64748B', fontSize: 12, cursor: 'pointer' }}>📋 诊断 ({sessionDetail.diagnostics.length} 条)</summary>
            <pre style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 10, marginTop: 8, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
              {sessionDetail.diagnostics.join('\n')}
            </pre>
          </details>}
        </div>}

        {detail.version && <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#0F172A', marginBottom: 8 }}>📦 版本完成详情</h4>
          <p style={{ color: '#94A3B8', fontSize: 12 }}>请前往"版本报告"页面查看 Git 提交记录和文件变更。</p>
        </div>}
      </div>}
    </Modal>
  </div>
}
