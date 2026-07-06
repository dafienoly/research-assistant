import { useState, useEffect } from 'react'
import { Card, Row, Col, Statistic, Table, Tag, Spin, Alert, Descriptions, Modal, Typography } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const darkCard = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12, marginBottom: 16 }

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [detail, setDetail] = useState(null)
  const [fetchDetail, setFetchDetail] = useState(null)
  useEffect(() => {
    fetch(`${API}/api/status`).then(r => r.json()).then(setData).catch(() => {})
    const t = setInterval(() => fetch(`${API}/api/status`).then(r => r.json()).then(setData).catch(() => {}), 5000)
    return () => clearInterval(t)
  }, [])
  if (!data) return <Spin style={{ display: 'block', marginTop: 80 }} />

  const s = data.state || {}; const h = data.health || {}; const c = data.cursor || {}
  const r = data.report || {}; const be = data.backend || {}
  const bg = s.level === 'green' ? '#0f3d2e' : s.level === 'red' ? '#4a1620' : '#44380c'
  const fg = s.level === 'green' ? '#7df0bd' : s.level === 'red' ? '#ff8ba0' : '#ffdc7a'

  const cols = [
    { title: '版本', dataIndex: 'version', key: 'v', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'n', width: 160 },
    { title: '状态', dataIndex: 'status', key: 's', width: 80,
      render: v => <Tag color={v === 'completed' ? 'green' : v === 'current' ? 'blue' : v === 'failed' ? 'red' : 'default'}>{v}</Tag> },
    { title: '目标', dataIndex: 'objective', key: 'o', ellipsis: true },
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
        <Row><Col span={12}><Statistic title="当前版本" value={c.current_version || '-'} valueStyle={{ color: '#7df0bd', fontSize: 20 }} /></Col>
        <Col span={12}><Statistic title="已完成" value={r.total_completed || 0} valueStyle={{ color: '#7df0bd', fontSize: 20 }} /></Col></Row>
        <Row><Col span={12}><Statistic title="失败" value={r.total_failed || 0} valueStyle={{ color: r.total_failed > 0 ? '#ff8ba0' : '#e8ecf8', fontSize: 20 }} /></Col>
        <Col span={12}><Statistic title="允许至" value={c.auto_allowed_until || '-'} valueStyle={{ color: '#9aa7c7', fontSize: 16 }} /></Col></Row>
      </Card></Col>
      <Col span={8}><Card style={darkCard}><h3 style={{ color: '#cdd6f8', fontSize: 14, margin: '0 0 12px' }}>🔒 系统状态</h3>
        <Row><Col span={12}><Statistic title="Lock" value={h.lock_status || '?'} valueStyle={{ color: h.lock_status === 'free' ? '#7df0bd' : '#ff8ba0', fontSize: 16 }} /></Col>
        <Col span={12}><Statistic title="Cron" value={h.cron_service_running ? '运行中' : '已停止'} valueStyle={{ color: h.cron_service_running ? '#7df0bd' : '#ff8ba0', fontSize: 16 }} /></Col></Row>
        <Row><Col span={12}><Statistic title="Tick" value={h.tick_count || 0} valueStyle={{ color: '#e8ecf8', fontSize: 16 }} /></Col>
        <Col span={12}><Statistic title="Latest" value={c.current_version || '-'} valueStyle={{ color: '#e8ecf8', fontSize: 16 }} /></Col></Row>
      </Card></Col>
      <Col span={8}><Card style={darkCard}><h3 style={{ color: '#cdd6f8', fontSize: 14, margin: '0 0 12px' }}>⚡ Backend</h3>
        <Row><Col span={24}><Statistic title="Coding Backend" value={be.coding_backend_configured ? '已配置' : '未配置'} valueStyle={{ color: be.coding_backend_configured ? '#7df0bd' : '#ff8ba0', fontSize: 16 }} /></Col></Row>
        <Row><Col span={24} style={{ marginTop: 8 }}><Statistic title="Claude 路径" value={be.claude_bin_path || '未找到'} valueStyle={{ color: '#9aa7c7', fontSize: 12 }} /></Col></Row>
      </Card></Col>
    </Row>
    <Card style={darkCard} title={<span style={{ color: '#cdd6f8' }}>📋 版本列表 <span style={{ fontSize: 12, color: '#9aa7c7' }}>(点击版本查看详情)</span></span>}>
      <Table dataSource={r.versions || []} columns={cols} rowKey="version" size="small" pagination={{ pageSize: 10 }}
        onRow={v => ({ onClick: () => setDetail(v), style: { cursor: 'pointer' } })} />
    </Card>
    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={640}
      title={<span style={{ color: '#cdd6f8' }}>{detail?.version} — {detail?.name}</span>}>
      {detail && <Descriptions column={1} size="small" bordered
        styles={{ label: { background: '#121a35', color: '#9aa7c7' }, content: { background: '#0b1020', color: '#e8ecf8' } }}>
        <Descriptions.Item label="版本">{detail.version}</Descriptions.Item>
        <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
        <Descriptions.Item label="目标">{detail.objective}</Descriptions.Item>
        <Descriptions.Item label="状态"><Tag color={detail.status === 'completed' ? 'green' : detail.status === 'current' ? 'blue' : 'default'}>{detail.status}</Tag></Descriptions.Item>
        <Descriptions.Item label="自动允许">{detail.auto_allowed ? '✅' : '❌'}</Descriptions.Item>
        <Descriptions.Item label="手动门禁">{detail.manual_required ? '⚠️ 需要' : '—'}</Descriptions.Item>
        <Descriptions.Item label="交易模式">{detail.trading_mode || 'research'}</Descriptions.Item>
      </Descriptions>}
    </Modal>
  </div>
}
