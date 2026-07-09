// @ts-nocheck
import { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Table, Tag, Button, message, Spin, Modal, Descriptions, Tabs, Space, Popconfirm, Typography, Empty } from 'antd'
import { API } from '../App'

// ─── Types ──────────────────────────────────────────────────────────
interface ReportSummary {
  total: number
  recent_7d: number
  total_size_mb: number
  by_type: Record<string, number>
}

interface ReportItem {
  id: string
  type: string
  name?: string
  version?: string
  status?: string
  group?: string
  size_bytes: number
  factor?: string
  created_at?: string
  /** backtest-specific */
  metrics?: Record<string, number | string>
  /** version-specific */
  commits?: Array<{ hash?: string; message?: string }>
  files_changed?: string[]
  has_json?: boolean
  agent?: string
  prompt_preview?: string
}

interface ReportDetail {
  metrics?: Record<string, number | string>
  html_content?: string
  files?: string[]
  data?: Record<string, unknown>
  request?: { agent?: string; version?: string; created_at?: string; prompt?: string }
  summary?: { status?: string }
  answer_full?: string
  content?: Record<string, unknown>
  total_files?: number
  size_bytes?: number
  error?: string
}

// ─── Constants ──────────────────────────────────────────────────────
const CARD: React.CSSProperties = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

function statCardStyle(color: string): React.CSSProperties {
  return {
    background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, padding: 16,
    borderLeft: `4px solid ${color}`,
  }
}

const TYPE_META: Record<string, { color: string; label: string; icon: string }> = {
  backtest: { color: '#2563EB', label: '回测报告', icon: '📊' },
  strategy: { color: '#059669', label: '策略报告', icon: '📈' },
  version:  { color: '#7C3AED', label: '版本报告', icon: '📋' },
  session:  { color: '#D97706', label: 'Session',   icon: '💾' },
  roadmap:  { color: '#64748B', label: '路线图备份', icon: '🗺️' },
}

// ─── StatCard helper ────────────────────────────────────────────────
const StatCard: React.FC<{ color: string; label: string; value: string | number }> = ({ color, label, value }) => (
  <Card style={statCardStyle(color)}>
    <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>{label}</Typography.Text>
    <div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{value}</div>
  </Card>
)

export default function Reports() {
  // ─── State ────────────────────────────────────────────────────────
  const [summary, setSummary] = useState<ReportSummary | null>(null)
  const [reports, setReports] = useState<ReportItem[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [activeType, setActiveType] = useState('all')
  const [detailModal, setDetailModal] = useState<ReportItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailData, setDetailData] = useState<ReportDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  // ─── Data Fetching ────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/reports/summary`)
      if (r.ok) setSummary(await r.json())
    } catch { /* ignore */ }
  }, [])

  const fetchReports = useCallback(async (type: string) => {
    setLoading(true)
    setError(null)
    try {
      const url = type === 'all'
        ? `${API}/api/reports?limit=200`
        : `${API}/api/reports?type=${type}&limit=200`
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setReports(d.reports || [])
      setTotal(d.total || 0)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
      setReports([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSummary(); fetchReports('all') }, [fetchSummary, fetchReports])

  const switchType = useCallback((type: string) => {
    setActiveType(type)
    fetchReports(type)
  }, [fetchReports])

  const openDetail = useCallback(async (record: ReportItem) => {
    setDetailModal(record)
    setDetailData(null)
    setDetailLoading(true)
    try {
      const r = await fetch(`${API}/api/reports/detail/${record.type}/${encodeURIComponent(record.id)}`)
      if (r.ok) setDetailData(await r.json())
    } catch (e: unknown) {
      setDetailData({ error: e instanceof Error ? e.message : '未知错误' })
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const handleDelete = useCallback(async (record: ReportItem) => {
    try {
      const r = await fetch(`${API}/api/reports/${record.type}/${encodeURIComponent(record.id)}`, { method: 'DELETE' })
      const d = await r.json()
      if (d.error) {
        message.error(`删除失败: ${d.error}`)
      } else {
        message.success('报告已删除')
        fetchReports(activeType)
        fetchSummary()
      }
    } catch (e: unknown) {
      message.error(`删除失败: ${e instanceof Error ? e.message : '未知错误'}`)
    }
  }, [activeType, fetchReports, fetchSummary])

  // ── 列定义 ──
  const typeRender = (type: string) => {
    const m = TYPE_META[type] || { color: '#64748B', label: type, icon: '📄' }
    return <Tag color={m.color} style={{ border: 'none', borderRadius: 12, fontSize: 11 }}>{m.icon} {m.label}</Tag>
  }

  const backtestCols = [
    { title: '类型', dataIndex: 'type', width: 90, render: typeRender },
    { title: '名称', dataIndex: 'name', ellipsis: true, render: (v, r) => (
      <a onClick={() => openDetail(r)} style={{ color: '#2563EB', fontWeight: 500 }}>{v || r.id}</a>
    )},
    { title: '夏普', dataIndex: ['metrics', 'sharpe'], width: 70, align: 'right',
      render: v => v != null ? <span style={{ color: v > 1 ? '#059669' : v > 0 ? '#D97706' : '#DC2626', fontWeight: 600 }}>{v}</span> : '-' },
    { title: '年化', dataIndex: ['metrics', 'cagr'], width: 80, align: 'right',
      render: v => v != null ? <span style={{ color: v > 0 ? '#059669' : '#DC2626' }}>{v}%</span> : '-' },
    { title: '最大回撤', dataIndex: ['metrics', 'max_drawdown'], width: 80, align: 'right',
      render: v => v != null ? <span style={{ color: v < -20 ? '#DC2626' : '#D97706' }}>{v}%</span> : '-' },
    { title: '累计收益', dataIndex: ['metrics', 'cumulative_return'], width: 80, align: 'right',
      render: v => v != null ? <span style={{ color: v > 0 ? '#059669' : '#DC2626', fontWeight: 600 }}>{v}%</span> : '-' },
    { title: '因子', dataIndex: 'factor', width: 100, ellipsis: true, render: v => v || '-' },
    { title: '操作', key: 'act', width: 60, render: (_, r) => (
      <Popconfirm title="确认删除此回测报告?" onConfirm={() => handleDelete(r)} okText="删除" cancelText="取消">
        <Button size="small" danger type="text">删除</Button>
      </Popconfirm>
    )},
  ]

  const strategyCols = [
    { title: '类型', dataIndex: 'type', width: 90, render: typeRender },
    { title: '名称', dataIndex: 'name', ellipsis: true, render: (v, r) => (
      <a onClick={() => openDetail(r)} style={{ color: '#2563EB', fontWeight: 500 }}>{v}</a>
    )},
    { title: '分组', dataIndex: 'group', width: 100, render: v => <Tag>{v}</Tag> },
    { title: '大小', dataIndex: 'size_bytes', width: 80, align: 'right',
      render: v => v > 1024*1024 ? `${(v/1024/1024).toFixed(1)}MB` : v > 1024 ? `${(v/1024).toFixed(0)}KB` : `${v}B` },
  ]

  const versionCols = [
    { title: '类型', dataIndex: 'type', width: 90, render: typeRender },
    { title: '版本', dataIndex: 'version', width: 70 },
    { title: '名称', dataIndex: 'name', ellipsis: true, render: (v, r) => (
      <a onClick={() => openDetail(r)} style={{ color: '#2563EB', fontWeight: 500 }}>{v}</a>
    )},
    { title: '状态', dataIndex: 'status', width: 80, render: v => <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag> },
    { title: '提交数', key: 'commits', width: 70, align: 'right',
      render: (_, r) => r.commits?.length || '-' },
    { title: '文件变更', key: 'files', width: 80, ellipsis: true,
      render: (_, r) => r.files_changed?.length ? `${r.files_changed.length} 项` : '-' },
  ]

  const sessionCols = [
    { title: '类型', dataIndex: 'type', width: 90, render: typeRender },
    { title: 'Session', dataIndex: 'id', width: 160, render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0, 26)}</code> },
    { title: 'Agent', dataIndex: 'agent', width: 70, render: v => <Tag>{v || '-'}</Tag> },
    { title: '状态', dataIndex: 'status', width: 70, render: v => <Tag color={v === 'completed' ? 'success' : 'default'}>{v}</Tag> },
    { title: '提示词', dataIndex: 'prompt_preview', ellipsis: true },
  ]

  const roadmapCols = [
    { title: '类型', dataIndex: 'type', width: 90, render: typeRender },
    { title: '名称', dataIndex: 'name', width: 220, render: (v, r) => (
      <a onClick={() => openDetail(r)} style={{ color: '#2563EB', fontWeight: 500 }}>{v}</a>
    )},
    { title: 'JSON', dataIndex: 'has_json', width: 60, render: v => v ? <Tag color="blue">有</Tag> : '-' },
    { title: '大小', dataIndex: 'size_bytes', width: 80, align: 'right',
      render: v => v > 1024*1024 ? `${(v/1024/1024).toFixed(1)}MB` : v > 1024 ? `${(v/1024).toFixed(0)}KB` : `${v}B` },
  ]

  const getColumns = (type) => {
    switch (type) {
      case 'backtest': return backtestCols
      case 'strategy': return strategyCols
      case 'version':  return versionCols
      case 'session':  return sessionCols
      case 'roadmap':  return roadmapCols
      default: return [
        { title: '类型', dataIndex: 'type', width: 80, render: typeRender },
        { title: '名称', dataIndex: 'name', ellipsis: true, render: (v, r) => (
          <a onClick={() => openDetail(r)} style={{ color: '#2563EB', fontWeight: 500 }}>{v || r.id}</a>
        )},
        { title: '日期', dataIndex: 'created_at', width: 160, render: v => v ? new Date(v).toLocaleString('zh-CN') : '-' },
        { title: '大小', dataIndex: 'size_bytes', width: 80, align: 'right',
          render: v => v > 1024*1024 ? `${(v/1024/1024).toFixed(1)}MB` : v > 1024 ? `${(v/1024).toFixed(0)}KB` : `${v}B` },
      ]
    }
  }

  // ── Tab 配置 ──
  const tabItems = [
    { key: 'all',      label: `📁 全部 (${summary?.total ?? '...'})` },
    { key: 'backtest', label: `📊 回测 (${summary?.by_type?.backtest ?? 0})` },
    { key: 'strategy', label: `📈 策略 (${summary?.by_type?.strategy ?? 0})` },
    { key: 'version',  label: `📋 版本 (${summary?.by_type?.version ?? 0})` },
    { key: 'session',  label: `💾 Session (${summary?.by_type?.session ?? 0})` },
    { key: 'roadmap',  label: `🗺️ 路线图 (${summary?.by_type?.roadmap ?? 0})` },
  ]

  // ── 详情弹窗 ──
  const renderDetail = () => {
    if (!detailModal || !detailData) return null
    if (detailData.error) return <div style={{ color: '#DC2626' }}>加载失败: {detailData.error}</div>

    const type = detailModal.type

    if (type === 'backtest') {
      const m = detailData.metrics || {}
      return <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="因子名称">{m.factor_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="策略名称">{m.strategy_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="股票池">{m.universe || '-'}</Descriptions.Item>
          <Descriptions.Item label="基准">{m.benchmark || '-'}</Descriptions.Item>
          <Descriptions.Item label="回测区间">{m.start_date} ~ {m.end_date}</Descriptions.Item>
          <Descriptions.Item label="调仓频率">{m.rebalance_freq || '-'}</Descriptions.Item>
          <Descriptions.Item label="夏普比率"><span style={{ color: (m.sharpe || 0) > 1 ? '#059669' : '#DC2626', fontWeight: 700 }}>{m.sharpe ?? '-'}</span></Descriptions.Item>
          <Descriptions.Item label="年化收益"><span style={{ color: (m.cagr || 0) > 0 ? '#059669' : '#DC2626', fontWeight: 700 }}>{m.cagr ?? '-'}%</span></Descriptions.Item>
          <Descriptions.Item label="累计收益"><span style={{ color: (m.cumulative_return || 0) > 0 ? '#059669' : '#DC2626', fontWeight: 700 }}>{m.cumulative_return ?? '-'}%</span></Descriptions.Item>
          <Descriptions.Item label="最大回撤"><span style={{ color: (m.max_drawdown || 0) < -20 ? '#DC2626' : '#D97706', fontWeight: 700 }}>{m.max_drawdown ?? '-'}%</span></Descriptions.Item>
          <Descriptions.Item label="索提诺比率">{m.sortino ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="卡玛比率">{m.calmar ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="年化波动率">{m.volatility ?? '-'}%</Descriptions.Item>
          <Descriptions.Item label="胜率">{m.win_rate ?? '-'}%</Descriptions.Item>
          <Descriptions.Item label="Beta">{m.beta ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="信息比率">{m.information_ratio ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="有效交易日">{m.total_days ?? '-'}</Descriptions.Item>
        </Descriptions>
        {detailData.html_content && <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#0F172A' }}>📄 报告 HTML 预览</h4>
          <div style={{ border: '1px solid #E2E8F0', borderRadius: 8, maxHeight: 400, overflow: 'auto', padding: 12, background: '#F8FAFC', fontSize: 12 }}>
            <code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{detailData.html_content.slice(0, 3000)}...</code>
          </div>
        </div>}
        {detailData.files?.length > 0 && <div style={{ marginTop: 12 }}>
          <h4 style={{ color: '#0F172A' }}>📁 文件</h4>
          {detailData.files.map(f => <div key={f} style={{ color: '#64748B', fontSize: 12, fontFamily: 'monospace' }}>{f}</div>)}
        </div>}
      </div>
    }

    if (type === 'version') {
      const d = detailData.data || {}
      return <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="版本">{d.version || '-'}</Descriptions.Item>
          <Descriptions.Item label="名称">{d.name || '-'}</Descriptions.Item>
          <Descriptions.Item label="完成时间">{d.completed_at || d.generated_at || '-'}</Descriptions.Item>
        </Descriptions>
        {d.commits?.length > 0 && <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#0F172A' }}>📝 Git 提交记录 ({d.commits.length})</h4>
          {d.commits.map((c, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid #F1F5F9' }}>
              <code style={{ color: '#2563EB', fontSize: 11 }}>{c.hash?.slice(0, 7)}</code>
              <span style={{ color: '#64748B', fontSize: 12 }}>{c.message}</span>
            </div>
          ))}
        </div>}
        {d.files_changed?.length > 0 && <div style={{ marginTop: 12 }}>
          <h4 style={{ color: '#0F172A' }}>📁 文件变更 ({d.files_changed.length})</h4>
          {d.files_changed.map((f, i) => (
            <div key={i} style={{ color: '#64748B', fontSize: 12, fontFamily: 'monospace', padding: '2px 0' }}>{f}</div>
          ))}
        </div>}
        {d.stats?.diff_shortstat && <p style={{ color: '#64748B', fontSize: 12, marginTop: 8 }}>{d.stats.diff_shortstat}</p>}
      </div>
    }

    if (type === 'session') {
      const req = detailData.request || {}
      const sum = detailData.summary || {}
      return <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="Agent">{req.agent || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">{sum.status || '-'}</Descriptions.Item>
          <Descriptions.Item label="版本">{req.version || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{req.created_at || '-'}</Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 12 }}>
          <h4 style={{ color: '#0F172A' }}>提示词</h4>
          <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 12, fontSize: 12, color: '#64748B', maxHeight: 150, overflow: 'auto' }}>{req.prompt || '(无)'}</div>
        </div>
        {detailData.answer_full && <div style={{ marginTop: 12 }}>
          <h4 style={{ color: '#0F172A' }}>回答</h4>
          <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 12, fontSize: 12, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{detailData.answer_full}</div>
        </div>}
      </div>
    }

    if (type === 'strategy') {
      return <div>
        <Descriptions column={1} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="名称">{detailModal.name}</Descriptions.Item>
          <Descriptions.Item label="分组">{detailModal.group || '-'}</Descriptions.Item>
          <Descriptions.Item label="大小">{detailData.size_bytes > 1024*1024 ? `${(detailData.size_bytes/1024/1024).toFixed(1)}MB` : `${(detailData.size_bytes/1024).toFixed(0)}KB`}</Descriptions.Item>
        </Descriptions>
        {detailData.html_content && <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#0F172A' }}>📄 报告 HTML 预览</h4>
          <div style={{ border: '1px solid #E2E8F0', borderRadius: 8, maxHeight: 400, overflow: 'auto', padding: 12, background: '#F8FAFC', fontSize: 12 }}>
            <code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{detailData.html_content.slice(0, 5000)}...</code>
          </div>
        </div>}
      </div>
    }

    if (type === 'roadmap') {
      const contentKeys = Object.keys(detailData.content || {})
      return <div>
        <Descriptions column={1} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="名称">{detailModal.name}</Descriptions.Item>
          <Descriptions.Item label="文件数">{detailData.total_files || 0}</Descriptions.Item>
          <Descriptions.Item label="JSON 文件">{contentKeys.length > 0 ? contentKeys.join(', ') : '无'}</Descriptions.Item>
        </Descriptions>
        {contentKeys.length > 0 && <div style={{ marginTop: 12 }}>
          <h4 style={{ color: '#0F172A' }}>📄 内容预览</h4>
          <pre style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 12, fontSize: 11, maxHeight: 400, overflow: 'auto' }}>
            {JSON.stringify(detailData.content, null, 2).slice(0, 5000)}
          </pre>
        </div>}
      </div>
    }

    return <div style={{ color: '#64748B' }}>暂无详情预览</div>
  }

  // ── 渲染 ──
  return <div>
    {/* 统计卡片 */}
    {summary && <Row gutter={16} style={{ marginBottom: 20 }}>
      <Col span={4}><Card style={statCardStyle('#2563EB')}><Typography.Text style={{ color: '#64748B', fontSize: 12 }}>📁 报告总数</Typography.Text><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{summary.total}</div></Card></Col>
      <Col span={4}><Card style={statCardStyle('#059669')}><Typography.Text style={{ color: '#64748B', fontSize: 12 }}>🆕 近7天新增</Typography.Text><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{summary.recent_7d}</div></Card></Col>
      <Col span={4}><Card style={statCardStyle('#2563EB')}><Typography.Text style={{ color: '#64748B', fontSize: 12 }}>📊 回测报告</Typography.Text><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{summary.by_type?.backtest || 0}</div></Card></Col>
      <Col span={4}><Card style={statCardStyle('#059669')}><Typography.Text style={{ color: '#64748B', fontSize: 12 }}>📈 策略报告</Typography.Text><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{summary.by_type?.strategy || 0}</div></Card></Col>
      <Col span={4}><Card style={statCardStyle('#7C3AED')}><Typography.Text style={{ color: '#64748B', fontSize: 12 }}>📋 版本报告</Typography.Text><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{summary.by_type?.version || 0}</div></Card></Col>
      <Col span={4}><Card style={statCardStyle('#64748B')}><Typography.Text style={{ color: '#64748B', fontSize: 12 }}>💾 存储</Typography.Text><div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{summary.total_size_mb || 0} MB</div></Card></Col>
    </Row>}

    {/* Tab 导航 */}
    <Card style={CARD}>
      <Tabs activeKey={activeType} onChange={switchType} items={tabItems}
        style={{ marginBottom: 0 }} />

      {/* 刷新按钮 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Button size="small" onClick={() => { fetchReports(activeType); fetchSummary() }}
          style={{ color: '#64748B', fontSize: 12 }}>
          刷新
        </Button>
      </div>

      {/* 错误状态 */}
      {error && <div style={{ textAlign: 'center', padding: '32px 0' }}>
        <Typography.Text type="danger">加载失败: {error}</Typography.Text>
        <Button size="small" style={{ marginLeft: 12 }} onClick={() => fetchReports(activeType)}>重试</Button>
      </div>}

      {/* 加载状态 */}
      {loading && !error && <div style={{ textAlign: 'center', padding: '60px 0' }}><Spin tip="加载报告中..." /></div>}

      {/* 空状态 */}
      {!loading && !error && reports.length === 0 && <Empty description={<span style={{ color: '#94A3B8' }}>暂无{activeType === 'all' ? '' : TYPE_META[activeType]?.label}报告</span>} />}

      {/* 报告列表 */}
      {!loading && !error && reports.length > 0 && <Table
        dataSource={reports}
        columns={getColumns(activeType)}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 份报告` }}
        style={{ fontSize: 13 }}
      />}
    </Card>

    {/* 详情弹窗 */}
    <Modal
      open={!!detailModal}
      onCancel={() => { setDetailModal(null); setDetailData(null) }}
      footer={null}
      width={900}
      title={<span style={{ color: '#0F172A', fontWeight: 600 }}>
        {detailModal ? `${TYPE_META[detailModal.type]?.icon || '📄'} ${detailModal.name || detailModal.id}` : ''}
      </span>}
    >
      {detailLoading
        ? <div style={{ textAlign: 'center', padding: '40px' }}><Spin tip="加载详情..." /></div>
        : renderDetail()
      }
    </Modal>
  </div>
}
