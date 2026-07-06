import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, message, Spin, Row, Col, Statistic, Modal, Descriptions } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

export default function Reports() {
  const [report, setReport] = useState(null)
  const [sessions, setSessions] = useState([])
  const [backups, setBackups] = useState([])
  const [detail, setDetail] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/versions/report/detail`).then(r => r.json()).then(setReport)
    fetch(`${API}/api/agent-console/sessions?limit=50`).then(r => r.json()).then(d => setSessions(d.sessions || []))
    fetch(`${API}/api/backups`).then(r => r.json()).then(d => setBackups(d.backups || []))
  }, [])

  const showVersionDetail = async (v) => {
    setDetail(v)
    setSessionDetail(null)
    try {
      const r = await fetch(`${API}/api/agent-console/sessions?limit=200`)
      const d = await r.json()
      const match = (d.sessions || []).find(s => s.prompt?.includes(v.version))
      if (match) {
        const sr = await fetch(`${API}/api/agent-console/sessions/${match.id}`)
        setSessionDetail(await sr.json())
      }
    } catch (e) {}
  }

  const backupSession = async (sid) => {
    await fetch(`${API}/api/agent-console/sessions/${sid}/backup`, { method: 'POST' })
    message.success(`Session 已备份`)
  }

  if (!report) return <Spin />
  const vcols = [
    { title: '版本', dataIndex: 'version', key: 'v', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'n', width: 160 },
    { title: '状态', dataIndex: 'status', key: 's', width: 80, render: v => <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag> },
    { title: '目标', dataIndex: 'objective', key: 'o', ellipsis: true },
  ]
  const scols = [
    { title: 'Session', dataIndex: 'id', key: 'id', width: 140, render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: '版本', dataIndex: 'version', key: 'ver', width: 60 },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 80, render: v => <Tag color={v === 'claude_code' ? 'blue' : 'green'}>{v?.split('_')[0] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 70, render: v => <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag> },
    { title: '回答', dataIndex: 'answer_preview', key: 'ap', ellipsis: true },
    { title: '操作', key: 'act', width: 80, render: (_, r) => <Button size="small" onClick={() => backupSession(r.id)}>备份</Button> },
  ]

  return <div>
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col span={8}><Card style={cardStyle}><Statistic title="当前版本" value={report.current_version} valueStyle={{ color: '#0F172A' }} /></Card></Col>
      <Col span={8}><Card style={cardStyle}><Statistic title="已完成" value={report.total_completed} valueStyle={{ color: '#059669' }} /></Card></Col>
      <Col span={8}><Card style={cardStyle}><Statistic title="失败" value={report.total_failed} valueStyle={{ color: report.total_failed > 0 ? '#DC2626' : '#0F172A' }} /></Card></Col>
    </Row>

    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>📊 版本完成列表</span>}
      extra={<span style={{ color: '#94A3B8', fontSize: 12 }}>点击版本查看完整详情</span>} style={cardStyle}>
      <Table dataSource={report.versions || []} columns={vcols} rowKey="version" size="small" pagination={false}
        onRow={v => ({ onClick: () => showVersionDetail(v), style: { cursor: 'pointer' } })} />
    </Card>

    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={800}
      title={<span style={{ color: '#0F172A', fontWeight: 600 }}>{detail?.version} — {detail?.name}</span>}>
      {detail && <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="版本">{detail.version}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={detail.status === 'completed' ? 'success' : 'default'}>{detail.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="名称" span={2}>{detail.name}</Descriptions.Item>
          <Descriptions.Item label="目标" span={2}>{detail.objective}</Descriptions.Item>
        </Descriptions>

        {sessionDetail && <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#0F172A' }}>🤖 Agent 开发回答</h4>
          <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 16, maxHeight: 300, overflow: 'auto', marginTop: 8 }}>
            {sessionDetail.answer ? <Markdown remarkPlugins={[remarkGfm]}>{sessionDetail.answer}</Markdown> : <span style={{ color: '#94A3B8' }}>无回答</span>}
          </div>
        </div>}
      </div>}
    </Modal>

    {report.completion_detail && <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>📦 版本完成详情 — {report.completion_detail.version}</span>} style={cardStyle}>
      {report.completion_detail.commits?.length > 0 && <div style={{ marginBottom: 12 }}>
        <h4 style={{ color: '#0F172A', fontSize: 14 }}>Git 提交记录</h4>
        <Table dataSource={report.completion_detail.commits} columns={[
          { title: 'Hash', dataIndex: 'hash', key: 'h', width: 80, render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0,7)}</code> },
          { title: '提交信息', dataIndex: 'message', key: 'm' },
        ]} rowKey="hash" size="small" pagination={false} />
      </div>}
      {report.completion_detail.files_changed?.length > 0 && <div>
        <h4 style={{ color: '#0F172A', fontSize: 14 }}>文件变更</h4>
        {report.completion_detail.files_changed.map((f, i) => <div key={i} style={{ color: '#64748B', fontSize: 12, fontFamily: 'monospace', padding: '2px 0' }}>{f}</div>)}
      </div>}
      {report.completion_detail.stats?.diff_shortstat && <p style={{ color: '#64748B', fontSize: 12, marginTop: 8 }}>{report.completion_detail.stats.diff_shortstat}</p>}
    </Card>}

    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>💾 Session 历史与备份</span>} style={cardStyle}>
      <Table dataSource={sessions} columns={scols} rowKey="id" size="small" pagination={{ pageSize: 10 }} />
    </Card>
  </div>
}
