/**
 * V5.15 事件研报与语义增强入口 (Events.tsx)
 *
 * 模块：
 *   1. 公告事件流表格 — 日期/代码/名称/事件类型/方向(pos/neg)/强度/来源
 *   2. 事件详情(行点击→Modal) — 事件描述/产品/客户/产能/风险标记/LLM摘要
 *   3. 事件频率统计 — 近30日/90日各类型事件数
 *   4. 事件因子表现 — 事件后1/5/20日收益 vs 同池等权
 *
 * 数据：
 *   GET /api/events
 *   GET /api/events/{id}
 *
 * 要求：
 *   - 所有事件有来源
 *   - 所有公告有披露时间
 *   - 不允许未来函数
 *   - 三态: 不使用 mock 数据
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Table, Tag, Button, Modal, Descriptions,
  Space, Typography, Skeleton,
} from 'antd'
import {
  ReloadOutlined, FileTextOutlined, WarningOutlined,
} from '@ant-design/icons'
import { API } from '../App'
import PageHeader from '../components/common/PageHeader'
import LoadingState from '../components/common/LoadingState'
import EmptyState from '../components/common/EmptyState'
import MetricCard from '../components/common/MetricCard'
import type {
  EventItem, EventDetail, EventStats, EventFactorPerformance,
} from '../api/schemas'

// ═════════════════════════════════════════════════════════════════
// 样式常量
// ═════════════════════════════════════════════════════════════════
const CARD: React.CSSProperties = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
  marginBottom: 16,
}

// ═════════════════════════════════════════════════════════════════
// 事件方向配置
// ═════════════════════════════════════════════════════════════════
const DIRECTION_META: Record<string, { color: string; bg: string; label: string; icon: string }> = {
  positive: { color: '#059669', bg: '#D1FAE5', label: '正面', icon: '🟢' },
  negative: { color: '#DC2626', bg: '#FEE2E2', label: '负面', icon: '🔴' },
  neutral:  { color: '#64748B', bg: '#F1F5F9', label: '中性', icon: '⚪' },
}

// ═════════════════════════════════════════════════════════════════
// 事件方向 Badge
// ═════════════════════════════════════════════════════════════════
const DirectionBadge: React.FC<{ direction: string }> = ({ direction }) => {
  const m = DIRECTION_META[direction] || DIRECTION_META.neutral
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '2px 8px', borderRadius: 999, fontSize: 12,
        color: m.color, backgroundColor: m.bg,
      }}
    >
      {m.icon} {m.label}
    </span>
  )
}

// ═════════════════════════════════════════════════════════════════
// 强度指示器
// ═════════════════════════════════════════════════════════════════
const StrengthBadge: React.FC<{ strength: number }> = ({ strength }) => {
  const color = strength >= 4 ? '#DC2626' : strength >= 3 ? '#D97706' : '#64748B'
  return (
    <span style={{ color, fontFamily: 'monospace', fontWeight: 600, fontSize: 13 }}>
      {'★'.repeat(strength)}{'☆'.repeat(5 - strength)}
    </span>
  )
}

// ═════════════════════════════════════════════════════════════════
// 事件类型 Tag
// ═════════════════════════════════════════════════════════════════
const EVENT_TYPE_COLORS: Record<string, string> = {
  '订单': '#2563EB', '中标': '#2563EB', '扩产': '#7C3AED', '投资': '#7C3AED',
  '定增': '#D97706', '回购': '#059669', '减持': '#DC2626',
  '业绩预告': '#0891B2', '业绩快报': '#0891B2',
  '资产重组': '#9333EA', '监管函': '#DC2626',
  '大基金入股': '#059669', '国产替代突破': '#2563EB', '客户认证': '#059669',
  '限售解禁': '#D97706', '分红': '#059669',
}

const EventTypeTag: React.FC<{ type: string }> = ({ type }) => {
  const color = EVENT_TYPE_COLORS[type] || '#64748B'
  return <Tag color={color} style={{ borderRadius: 8, fontSize: 11, border: 'none' }}>{type}</Tag>
}

// ═════════════════════════════════════════════════════════════════
// 通用 fetch helper (unified API response)
// ═════════════════════════════════════════════════════════════════
async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(`${API}${url}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (json && typeof json === 'object' && 'ok' in json) {
    if (!json.ok) throw new Error(json.error?.message || `API 错误 (${url})`)
    return json.data as T
  }
  return json as T
}

// ═════════════════════════════════════════════════════════════════
// Main Component
// ═════════════════════════════════════════════════════════════════
export default function Events() {
  // ─── 状态 ────────────────────────────────────────────────────
  const [events, setEvents] = useState<EventItem[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<EventStats | null>(null)
  const [factorPerformance, setFactorPerformance] = useState<EventFactorPerformance[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 详情弹窗
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailData, setDetailData] = useState<EventDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)

  // 筛选
  const filterType = ''
  const filterDirection = ''

  // ─── 数据加载 ───────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ limit: '200' })
      if (filterType) params.set('event_type', filterType)
      if (filterDirection) params.set('direction', filterDirection)

      const data = await fetchJson<{
        events: EventItem[]
        total: number
        stats?: EventStats
        factor_performance?: EventFactorPerformance[]
      }>(`/api/events?${params.toString()}`)

      setEvents(data.events || [])
      setTotal(data.total || 0)
      setStats(data.stats || null)
      setFactorPerformance(data.factor_performance || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载事件数据失败')
      setEvents([])
      setTotal(0)
      setStats(null)
      setFactorPerformance([])
    } finally {
      setLoading(false)
    }
  }, [filterType, filterDirection])

  useEffect(() => { load() }, [load])

  // ─── 详情加载 ───────────────────────────────────────────────
  const openDetail = useCallback(async (id: string) => {
    setDetailId(id)
    setDetailData(null)
    setDetailError(null)
    setDetailLoading(true)
    try {
      const data = await fetchJson<EventDetail>(`/api/events/${id}`)
      setDetailData(data)
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : '加载事件详情失败')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const closeDetail = useCallback(() => {
    setDetailId(null)
    setDetailData(null)
    setDetailError(null)
  }, [])

  // ─── 统计汇总 ───────────────────────────────────────────────
  const positiveCount = events.filter(e => e.event_direction === 'positive').length
  const negativeCount = events.filter(e => e.event_direction === 'negative').length
  const neutralCount = events.filter(e => e.event_direction === 'neutral').length
  const total30d = stats ? Object.values(stats.by_type_30d).reduce((a, b) => a + b, 0) : 0
  const total90d = stats ? Object.values(stats.by_type_90d).reduce((a, b) => a + b, 0) : 0

  // ═══════════════════════════════════════════════════════════════
  // 列定义
  // ═══════════════════════════════════════════════════════════════
  const columns = [
    {
      title: '日期', dataIndex: 'event_date', key: 'date', width: 110,
      render: (v: string) => (
        <span style={{ color: '#64748B', fontSize: 12, fontFamily: 'monospace' }}>{v}</span>
      ),
      sorter: (a: EventItem, b: EventItem) => (a.event_date || '').localeCompare(b.event_date || ''),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 110,
      render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
    },
    {
      title: '名称', dataIndex: 'name', key: 'name', width: 140, ellipsis: true,
    },
    {
      title: '事件类型', dataIndex: 'event_type', key: 'type', width: 100,
      render: (v: string) => <EventTypeTag type={v} />,
      filters: Object.keys(EVENT_TYPE_COLORS).map(t => ({ text: t, value: t })),
      filterMultiple: true,
      onFilter: (value: unknown, record: EventItem) => record.event_type === value,
    },
    {
      title: '标题', dataIndex: 'title', key: 'title', ellipsis: true,
      render: (v: string, r: EventItem) => (
        <a
          onClick={() => openDetail(r.id)}
          style={{ color: '#2563EB', cursor: 'pointer' }}
        >
          {v || r.event_type}
        </a>
      ),
    },
    {
      title: '方向', dataIndex: 'event_direction', key: 'direction', width: 80,
      render: (v: string) => <DirectionBadge direction={v} />,
      filters: [
        { text: '🟢 正面', value: 'positive' },
        { text: '🔴 负面', value: 'negative' },
        { text: '⚪ 中性', value: 'neutral' },
      ],
      filterMultiple: true,
      onFilter: (value: unknown, record: EventItem) => record.event_direction === value,
    },
    {
      title: '强度', dataIndex: 'event_strength', key: 'strength', width: 90,
      render: (v: number) => <StrengthBadge strength={v} />,
      sorter: (a: EventItem, b: EventItem) => a.event_strength - b.event_strength,
    },
    {
      title: '来源', dataIndex: 'event_source', key: 'source', width: 90,
      render: (v: string) => (
        <Tag style={{ fontSize: 11, margin: 0 }}>{v}</Tag>
      ),
    },
  ]

  // ═══════════════════════════════════════════════════════════════
  // 渲染: 加载态
  // ═══════════════════════════════════════════════════════════════
  if (loading && events.length === 0) {
    return <LoadingState tip="加载事件数据..." size="large" />
  }

  // ═══════════════════════════════════════════════════════════════
  // 渲染: 错误态
  // ═══════════════════════════════════════════════════════════════
  if (error && events.length === 0) {
    return (
      <div className="stagger-fade">
        <PageHeader title="事件研报与语义增强" />
        <Card style={CARD}>
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Typography.Text type="danger" style={{ fontSize: 14 }}>
              {error}
            </Typography.Text>
            <div style={{ marginTop: 16 }}>
              <Button type="primary" onClick={load} icon={<ReloadOutlined />}>
                重试
              </Button>
            </div>
          </div>
        </Card>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════
  // 渲染: 空态
  // ═══════════════════════════════════════════════════════════════
  if (!loading && !error && events.length === 0) {
    return (
      <div className="stagger-fade">
        <PageHeader title="事件研报与语义增强" />
        <EmptyState description="暂无事件数据" />
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════
  // 渲染: 主界面
  // ═══════════════════════════════════════════════════════════════
  return (
    <div className="stagger-fade">
      <PageHeader
        title="事件研报与语义增强"
        dataSource="半导体事件因子引擎"
        updatedAt={new Date().toLocaleDateString('zh-CN')}
      />

      {/* ── 统计卡片 ── */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col xs={12} sm={8} md={4}>
          <MetricCard title="事件总数" value={total} color="primary" />
        </Col>
        <Col xs={12} sm={8} md={4}>
          <MetricCard title="近30日" value={total30d} color="info" />
        </Col>
        <Col xs={12} sm={8} md={4}>
          <MetricCard title="近90日" value={total90d} color="info" />
        </Col>
        <Col xs={12} sm={8} md={4}>
          <MetricCard
            title="正面事件"
            value={positiveCount}
            color="success"
          />
        </Col>
        <Col xs={12} sm={8} md={4}>
          <MetricCard
            title="负面事件"
            value={negativeCount}
            color="error"
          />
        </Col>
        <Col xs={12} sm={8} md={4}>
          <MetricCard
            title="中性事件"
            value={neutralCount}
            color="warning"
          />
        </Col>
      </Row>

      {/* ── 事件频率统计 (近30日/90日各类型事件数) ── */}
      {stats && (Object.keys(stats.by_type_30d).length > 0 || Object.keys(stats.by_type_90d).length > 0) && (
        <Card
          title={
            <Space>
              <FileTextOutlined />
              <span>事件频率统计</span>
            </Space>
          }
          style={CARD}
        >
          <Row gutter={[16, 16]}>
            {/* 近30日 */}
            <Col xs={24} md={12}>
              <Typography.Text strong style={{ color: '#0F172A', fontSize: 13, marginBottom: 8, display: 'block' }}>
                近30日各类型事件数
              </Typography.Text>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(stats.by_type_30d)
                  .sort(([, a], [, b]) => b - a)
                  .map(([type, count]) => (
                    <Tag
                      key={type}
                      color={EVENT_TYPE_COLORS[type] || '#64748B'}
                      style={{ borderRadius: 8, fontSize: 12, padding: '2px 10px' }}
                    >
                      {type}: {count}
                    </Tag>
                  ))}
              </div>
            </Col>

            {/* 近90日 */}
            <Col xs={24} md={12}>
              <Typography.Text strong style={{ color: '#0F172A', fontSize: 13, marginBottom: 8, display: 'block' }}>
                近90日各类型事件数
              </Typography.Text>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(stats.by_type_90d)
                  .sort(([, a], [, b]) => b - a)
                  .map(([type, count]) => (
                    <Tag
                      key={type}
                      color={EVENT_TYPE_COLORS[type] || '#64748B'}
                      style={{ borderRadius: 8, fontSize: 12, padding: '2px 10px' }}
                    >
                      {type}: {count}
                    </Tag>
                  ))}
              </div>
            </Col>
          </Row>
        </Card>
      )}

      {/* ── 事件因子表现 ── */}
      {factorPerformance.length > 0 && (
        <Card
          title={
            <Space>
              <FileTextOutlined />
              <span>事件因子表现 (vs 同池等权)</span>
            </Space>
          }
          style={CARD}
        >
          <Table
            dataSource={factorPerformance}
            columns={[
              { title: '事件类型', dataIndex: 'event_type', key: 't', width: 100, render: (v: string) => <EventTypeTag type={v} /> },
              {
                title: '1日收益', dataIndex: 'return_1d', key: 'r1', width: 100, align: 'right',
                render: (v: number) => (
                  <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace', fontWeight: 600 }}>
                    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                  </span>
                ),
              },
              {
                title: '5日收益', dataIndex: 'return_5d', key: 'r5', width: 100, align: 'right',
                render: (v: number) => (
                  <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace', fontWeight: 600 }}>
                    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                  </span>
                ),
              },
              {
                title: '20日收益', dataIndex: 'return_20d', key: 'r20', width: 100, align: 'right',
                render: (v: number) => (
                  <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace', fontWeight: 600 }}>
                    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                  </span>
                ),
              },
              {
                title: '基准1日', dataIndex: 'benchmark_return_1d', key: 'b1', width: 100, align: 'right',
                render: (v: number) => (
                  <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace' }}>
                    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                  </span>
                ),
              },
              {
                title: '基准5日', dataIndex: 'benchmark_return_5d', key: 'b5', width: 100, align: 'right',
                render: (v: number) => (
                  <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace' }}>
                    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                  </span>
                ),
              },
              {
                title: '基准20日', dataIndex: 'benchmark_return_20d', key: 'b20', width: 100, align: 'right',
                render: (v: number) => (
                  <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace' }}>
                    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                  </span>
                ),
              },
              {
                title: '超额1日', key: 'ex1', width: 90, align: 'right',
                render: (_: unknown, r: EventFactorPerformance) => {
                  const ex = r.return_1d - r.benchmark_return_1d
                  return (
                    <span style={{ color: ex >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace', fontWeight: 700 }}>
                      {ex >= 0 ? '+' : ''}{ex.toFixed(2)}%
                    </span>
                  )
                },
              },
              {
                title: '超额5日', key: 'ex5', width: 90, align: 'right',
                render: (_: unknown, r: EventFactorPerformance) => {
                  const ex = r.return_5d - r.benchmark_return_5d
                  return (
                    <span style={{ color: ex >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace', fontWeight: 700 }}>
                      {ex >= 0 ? '+' : ''}{ex.toFixed(2)}%
                    </span>
                  )
                },
              },
              {
                title: '超额20日', key: 'ex20', width: 90, align: 'right',
                render: (_: unknown, r: EventFactorPerformance) => {
                  const ex = r.return_20d - r.benchmark_return_20d
                  return (
                    <span style={{ color: ex >= 0 ? '#059669' : '#DC2626', fontFamily: 'monospace', fontWeight: 700 }}>
                      {ex >= 0 ? '+' : ''}{ex.toFixed(2)}%
                    </span>
                  )
                },
              },
            ]}
            rowKey="event_type"
            size="small"
            pagination={false}
            style={{ fontSize: 13 }}
          />
        </Card>
      )}

      {/* ── 事件列表表格 ── */}
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>公告事件流 ({total})</span>
          </Space>
        }
        extra={
          <Button size="small" onClick={load} icon={<ReloadOutlined />}>
            刷新
          </Button>
        }
        style={CARD}
      >
        <Table
          dataSource={events}
          columns={columns}
          rowKey={(r) => r.id}
          size="small"
          pagination={{
            pageSize: 50,
            showTotal: (t) => `共 ${t} 条事件`,
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100'],
          }}
          style={{ fontSize: 13 }}
          scroll={{ x: 900 }}
          locale={{
            triggerDesc: '点击降序',
            triggerAsc: '点击升序',
            cancelSort: '取消排序',
          }}
        />
      </Card>

      {/* ── 事件详情弹窗 ── */}
      <Modal
        open={!!detailId}
        onCancel={closeDetail}
        footer={null}
        width={800}
        destroyOnClose
        title={
          <span style={{ color: '#0F172A', fontWeight: 600 }}>
            {detailData ? (
              <span>
                <EventTypeTag type={detailData.event_type} />
                {' '}{detailData.title || detailData.event_type}
              </span>
            ) : '事件详情'}
          </span>
        }
      >
        {/* 加载中 */}
        {detailLoading && (
          <div style={{ padding: '40px 0', textAlign: 'center' }}>
            <Skeleton active paragraph={{ rows: 4 }} />
          </div>
        )}

        {/* 错误 */}
        {detailError && !detailLoading && (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <Typography.Text type="danger">{detailError}</Typography.Text>
            <div style={{ marginTop: 12 }}>
              <Button
                size="small"
                onClick={() => detailId && openDetail(detailId)}
              >
                重试
              </Button>
            </div>
          </div>
        )}

        {/* 详情内容 */}
        {detailData && !detailLoading && (
          <div>
            <Descriptions
              column={2}
              size="small"
              bordered
              styles={{
                label: { background: '#F8FAFC', color: '#64748B', fontSize: 12 },
                content: { color: '#0F172A', fontSize: 13 },
              }}
            >
              <Descriptions.Item label="事件日期">
                <span style={{ fontFamily: 'monospace' }}>{detailData.event_date}</span>
              </Descriptions.Item>
              <Descriptions.Item label="股票">
                <code style={{ color: '#2563EB' }}>{detailData.ts_code}</code>
                {' '}{detailData.name}
              </Descriptions.Item>
              <Descriptions.Item label="事件类型">
                <EventTypeTag type={detailData.event_type} />
              </Descriptions.Item>
              <Descriptions.Item label="方向">
                <DirectionBadge direction={detailData.event_direction} />
              </Descriptions.Item>
              <Descriptions.Item label="强度">
                <StrengthBadge strength={detailData.event_strength} />
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                <Tag style={{ fontSize: 11 }}>{detailData.event_source}</Tag>
              </Descriptions.Item>
            </Descriptions>

            {/* 事件描述 */}
            {detailData.detail && (
              <div style={{ marginTop: 16 }}>
                <Typography.Text strong style={{ color: '#0F172A', fontSize: 13 }}>
                  事件描述
                </Typography.Text>
                <div
                  style={{
                    marginTop: 8,
                    background: '#F8FAFC',
                    border: '1px solid #E2E8F0',
                    borderRadius: 8,
                    padding: 12,
                    fontSize: 13,
                    color: '#334155',
                    maxHeight: 200,
                    overflow: 'auto',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'monospace',
                  }}
                >
                  {detailData.detail}
                </div>
              </div>
            )}

            {/* 产品 / 客户 / 产能 */}
            {(detailData.products?.length || detailData.customers?.length || detailData.capacity) && (
              <Descriptions
                column={2}
                size="small"
                bordered
                style={{ marginTop: 16 }}
                styles={{
                  label: { background: '#F8FAFC', color: '#64748B', fontSize: 12 },
                  content: { color: '#0F172A', fontSize: 13 },
                }}
              >
                {detailData.products?.length ? (
                  <Descriptions.Item label="相关产品">
                    {detailData.products.join('、')}
                  </Descriptions.Item>
                ) : null}
                {detailData.customers?.length ? (
                  <Descriptions.Item label="相关客户">
                    {detailData.customers.join('、')}
                  </Descriptions.Item>
                ) : null}
                {detailData.capacity ? (
                  <Descriptions.Item label="产能信息">
                    {detailData.capacity}
                  </Descriptions.Item>
                ) : null}
              </Descriptions>
            )}

            {/* 风险标记 */}
            {detailData.risk_flags?.length ? (
              <div style={{ marginTop: 16 }}>
                <Space style={{ marginBottom: 8 }}>
                  <WarningOutlined style={{ color: '#D97706' }} />
                  <Typography.Text strong style={{ color: '#0F172A', fontSize: 13 }}>
                    风险标记
                  </Typography.Text>
                </Space>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {detailData.risk_flags.map((flag, i) => (
                    <Tag key={i} color="error" style={{ borderRadius: 8, fontSize: 11 }}>
                      {flag}
                    </Tag>
                  ))}
                </div>
              </div>
            ) : null}

            {/* LLM 摘要 */}
            {detailData.llm_summary && (
              <div style={{ marginTop: 16 }}>
                <Space style={{ marginBottom: 8 }}>
                  <FileTextOutlined style={{ color: '#7C3AED' }} />
                  <Typography.Text strong style={{ color: '#0F172A', fontSize: 13 }}>
                    LLM 智能摘要
                  </Typography.Text>
                </Space>
                <div
                  style={{
                    background: '#F5F3FF',
                    border: '1px solid #EDE9FE',
                    borderRadius: 8,
                    padding: 12,
                    fontSize: 13,
                    color: '#334155',
                    lineHeight: 1.6,
                  }}
                >
                  {detailData.llm_summary}
                </div>
              </div>
            )}

            {/* 原始来源 */}
            <div style={{ marginTop: 16, fontSize: 12, color: '#94A3B8' }}>
              <Typography.Text style={{ color: '#94A3B8' }}>
                来源: {detailData.source_ref || detailData.event_source}
              </Typography.Text>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
