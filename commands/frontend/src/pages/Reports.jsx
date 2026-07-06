import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, message, Spin, Row, Col, Statistic } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12 }

export default function Reports() {
  const [report, setReport] = useState(null)
  const [sessions, setSessions] = useState([])
  const [backups, setBackups] = useState([])

  useEffect(() => {
    fetch(`${API}/api/versions/report/detail`).then(r => r.json()).then(setReport)
    fetch(`${API}/api/agent-console/sessions?limit=20`).then(r => r.json()).then(d => setSessions(d.sessions || []))
    fetch(`${API}/api/backups`).then(r => r.json()).then(d => setBackups(d.backups || []))
  }, [])

  const backupSession = async (sid) => {
    await fetch(`${API}/api/agent-console/sessions/${sid}/backup`, { method: 'POST' })
    message.success(`Session ${sid.slice(0,16)}... 已备份`)
  }

  if (!report) return <Spin />
  const vcols = [
    { title: '版本', dataIndex: 'version', key: 'v', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'n', width: 160 },
    { title: '状态', dataIndex: 'status', key: 's', width: 80, render: v => <Tag color={v === 'completed' ? 'green' : 'red'}>{v}</Tag> },
  ]
  const scols = [
    { title: 'Session', dataIndex: 'id', key: 'id', width: 140, render: v => <code style={{ color: '#7df0bd', fontSize: 11 }}>{v.slice(0,24)}</code> },
    { title: 'Agent', dataIndex: 'agent', key: 'a', width: 80, render: v => <Tag color={v === 'claude_code' ? 'blue' : 'green'}>{v?.split('_')[0]}</Tag> },
    { title: '状态', dataIndex: 'status', key: 's', width: 70, render: v => <Tag color={v === 'completed' ? 'green' : v === 'running' ? 'processing' : 'default'}>{v}</Tag> },
    { title: '回答预览', dataIndex: 'answer_preview', key: 'ap', ellipsis: true },
    { title: '操作', key: 'act', width: 80, render: (_, r) => <Button size="small" onClick={() => backupSession(r.id)}>备份</Button> },
  ]
  const bcols = [
    { title: '备份 ID', dataIndex: 'id', key: 'id', render: v => <code style={{ color: '#7df0bd' }}>{v.slice(0,20)}...</code> },
    { title: '版本', dataIndex: 'current_version', key: 'v', width: 80 },
    { title: '已完成', dataIndex: 'completed', key: 'c', width: 80 },
  ]

  return <div>
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col span={8}><Card style={cardStyle}><Statistic title="当前版本" value={report.current_version} valueStyle={{ color: '#7df0bd' }} /></Card></Col>
      <Col span={8}><Card style={cardStyle}><Statistic title="已完成" value={report.total_completed} valueStyle={{ color: '#7df0bd' }} /></Card></Col>
      <Col span={8}><Card style={cardStyle}><Statistic title="失败" value={report.total_failed} valueStyle={{ color: report.total_failed > 0 ? '#ff8ba0' : '#e8ecf8' }} /></Card></Col>
    </Row>

    <Card title={<span style={{ color: '#cdd6f8' }}>📊 版本完成列表</span>} style={{ ...cardStyle, marginBottom: 16 }}>
      <Table dataSource={report.versions || []} columns={vcols} rowKey="version" size="small" pagination={false} />
    </Card>

    {report.agent_outputs?.length > 0 && <Card title={<span style={{ color: '#cdd6f8' }}>📝 Agent 输出报告</span>} style={{ ...cardStyle, marginBottom: 16 }}>
      {report.agent_outputs.map((log, i) => <div key={i} style={{ marginBottom: 12 }}>
        <p style={{ color: '#9aa7c7', fontSize: 12 }}>{log.file} ({log.size} bytes)</p>
        <div style={{ background: '#080d1c', padding: 12, borderRadius: 8, maxHeight: 200, overflow: 'auto' }}>
          <Markdown remarkPlugins={[remarkGfm]}>{log.preview}</Markdown>
        </div>
      </div>)}
    </Card>}

    {/* 版本完成详情 */}
    {report.completion_detail && <Card title={<span style={{ color: '#cdd6f8' }}>📦 版本完成详情 — {report.completion_detail.version} {report.completion_detail.name}</span>} style={{ ...cardStyle, marginBottom: 16 }}>
      {report.completion_detail.commits?.length > 0 && <div style={{ marginBottom: 12 }}>
        <h4 style={{ color: '#cdd6f8' }}>Git 提交记录</h4>
        <Table dataSource={report.completion_detail.commits} columns={[
          { title: 'Hash', dataIndex: 'hash', key: 'h', width: 80, render: v => <code style={{ color: '#7df0bd', fontSize: 11 }}>{v.slice(0,7)}</code> },
          { title: '提交信息', dataIndex: 'message', key: 'm' },
        ]} rowKey="hash" size="small" pagination={false} />
      </div>}
      {report.completion_detail.files_changed?.length > 0 && <div>
        <h4 style={{ color: '#cdd6f8' }}>文件变更</h4>
        {report.completion_detail.files_changed.map((f, i) => <div key={i} style={{ color: '#9aa7c7', fontSize: 12, fontFamily: 'monospace', padding: '2px 0' }}>{f}</div>)}
      </div>}
      {report.completion_detail.stats?.diff_shortstat && <p style={{ color: '#9aa7c7', fontSize: 12, marginTop: 8 }}>{report.completion_detail.stats.diff_shortstat}</p>}
    </Card>}

    <Card title={<span style={{ color: '#cdd6f8' }}>💾 Session 历史 & 备份</span>} style={{ ...cardStyle, marginBottom: 16 }}>
      <Table dataSource={sessions} columns={scols} rowKey="id" size="small" pagination={{ pageSize: 10 }} />
    </Card>

    <Card title={<span style={{ color: '#cdd6f8' }}>💾 版本备份列表</span>} style={cardStyle}>
      <Table dataSource={backups} columns={bcols} rowKey="id" size="small" pagination={false} />
    </Card>
  </div>
}
