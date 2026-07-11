import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Modal, Row, Spin, Table, Tabs, Tag, Typography } from 'antd'
import { API } from '../App'

interface Summary { total: number; recent_7d: number; total_size_mb: number; by_type: Record<string, number> }
interface ReportItem { id: string; type: 'backtest' | 'strategy'; name: string; group?: string; factor?: string; created_at: string; size_bytes: number; metrics?: Record<string, number | null> }

function unwrap<T>(value: { data?: T } | T): T { return ((value as { data?: T }).data ?? value) as T }

export default function Reports() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [reports, setReports] = useState<ReportItem[]>([])
  const [type, setType] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)

  const load = useCallback(async (selected = type) => {
    setLoading(true); setError('')
    try {
      const suffix = selected === 'all' ? '' : `?type=${selected}`
      const [summaryResponse, reportsResponse] = await Promise.all([
        fetch(`${API}/api/reports/summary`), fetch(`${API}/api/reports${suffix}`),
      ])
      if (!summaryResponse.ok || !reportsResponse.ok) throw new Error('报告 API 返回异常')
      setSummary(unwrap<Summary>(await summaryResponse.json()))
      setReports(unwrap<{ reports: ReportItem[] }>(await reportsResponse.json()).reports || [])
    } catch (reason) { setError(reason instanceof Error ? reason.message : '报告加载失败') }
    finally { setLoading(false) }
  }, [type])

  useEffect(() => { load(type) }, [load, type])

  const open = async (row: ReportItem) => {
    const response = await fetch(`${API}/api/reports/detail/${row.type}/${encodeURIComponent(row.id)}`)
    if (response.ok) setDetail(unwrap<Record<string, unknown>>(await response.json()))
  }

  const columns = [
    { title: '类型', dataIndex: 'type', key: 'type', render: (value: string) => <Tag color={value === 'backtest' ? 'blue' : 'green'}>{value === 'backtest' ? '回测' : '策略'}</Tag> },
    { title: '名称', dataIndex: 'name', key: 'name', render: (value: string, row: ReportItem) => <Button type="link" onClick={() => open(row)}>{value}</Button> },
    { title: '因子/分组', key: 'source', render: (_: unknown, row: ReportItem) => row.factor || row.group || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (value: string) => value ? new Date(value).toLocaleString('zh-CN') : '-' },
    { title: '大小', dataIndex: 'size_bytes', key: 'size_bytes', render: (value: number) => `${Math.max(0, value / 1024).toFixed(1)} KB` },
  ]

  return <div>
    {summary && <Row gutter={16} style={{ marginBottom: 16 }}>
      {[['报告总数', summary.total], ['近 7 天', summary.recent_7d], ['回测报告', summary.by_type.backtest || 0], ['策略报告', summary.by_type.strategy || 0]].map(([label, value]) => (
        <Col span={6} key={String(label)}><Card><Typography.Text type="secondary">{label}</Typography.Text><div style={{ fontSize: 24, fontWeight: 700 }}>{value}</div></Card></Col>
      ))}
    </Row>}
    <Card>
      <Tabs activeKey={type} onChange={setType} items={[
        { key: 'all', label: '全部' }, { key: 'backtest', label: '回测' }, { key: 'strategy', label: '策略' },
      ]} />
      {error && <Alert type="error" message={error} showIcon />}
      {loading ? <Spin /> : reports.length ? <Table rowKey={(row) => `${row.type}:${row.id}`} dataSource={reports} columns={columns} /> : <Empty description="暂无投研报告" />}
    </Card>
    <Modal open={Boolean(detail)} onCancel={() => setDetail(null)} footer={null} title="报告详情" width={800}>
      <pre style={{ maxHeight: 560, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{detail ? JSON.stringify(detail, null, 2) : ''}</pre>
    </Modal>
  </div>
}
