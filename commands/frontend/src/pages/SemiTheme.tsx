/** V5.6 半导体主题看板 — SemiTheme */
import { useMemo, type CSSProperties } from 'react'
import { Card, Row, Col, Table, Tag, Typography, Space, Tooltip, Progress } from 'antd'
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ThunderboltOutlined,
  TeamOutlined,
  BarChartOutlined,
  FundOutlined,
  RiseOutlined,
  FallOutlined,
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

import PageHeader from '../components/common/PageHeader'
import MetricCard from '../components/common/MetricCard'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import EmptyState from '../components/common/EmptyState'
import { useSemiThemeStatus } from '../hooks/useSemiThemeStatus'
import { useSemiSubsectors } from '../hooks/useSemiSubsectors'
import { useSemiHistory } from '../hooks/useSemiHistory'
import type { SubsectorItem } from '../hooks/useSemiSubsectors'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Text } = Typography

// ─── 样式常量 ────────────────────────────────────────────────
const CARD_STYLE: CSSProperties = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
  marginBottom: 16,
}

const SECTION_TITLE: CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  color: '#0F172A',
  marginBottom: 16,
  paddingBottom: 12,
  borderBottom: '1px solid #E2E8F0',
}

// ─── 主题状态配置 ──────────────────────────────────────────────
interface ThemeStateConfig {
  label: string
  color: string
  bg: string
}

const THEME_STATE_MAP: Record<string, ThemeStateConfig> = {
  '极弱': { label: '极弱', color: '#DC2626', bg: '#FEE2E2' },
  '偏弱': { label: '偏弱', color: '#D97706', bg: '#FEF3C7' },
  '中性': { label: '中性', color: '#64748B', bg: '#F1F5F9' },
  '偏强': { label: '偏强', color: '#059669', bg: '#D1FAE5' },
  '极强': { label: '极强', color: '#2563EB', bg: '#DBEAFE' },
}

const WEIGHT_CONFIG: Record<string, { label: string; color: string }> = {
  '0':   { label: '空仓', color: '#DC2626' },
  '30':  { label: '轻仓', color: '#D97706' },
  '50':  { label: '半仓', color: '#64748B' },
  '70':  { label: '重仓', color: '#059669' },
  '100': { label: '满仓', color: '#2563EB' },
}

// ─── 细分方向热力图颜色 ────────────────────────────────────────
function subsectorHeatColor(ratio: number): string {
  if (ratio >= 70) return '#166534'
  if (ratio >= 60) return '#16A34A'
  if (ratio >= 50) return '#FACC15'
  if (ratio >= 40) return '#FB923C'
  return '#DC2626'
}

function subsectorHeatBg(ratio: number): string {
  if (ratio >= 70) return '#DCFCE7'
  if (ratio >= 60) return '#BBF7D0'
  if (ratio >= 50) return '#FEF9C3'
  if (ratio >= 40) return '#FFEDD5'
  return '#FEE2E2'
}

// ─── 子组件: 细分方向热力卡片 ────────────────────────────────
const SubsectorCard: React.FC<{ item: SubsectorItem }> = ({ item }) => {
  const ratio = item.advance_ratio
  const color = subsectorHeatColor(ratio)
  const bg = subsectorHeatBg(ratio)
  return (
    <Col xs={12} sm={8} md={6} lg={4}>
      <div
        className="subsector-card"
        style={{
          background: bg,
          borderRadius: 10,
          padding: '16px 12px',
          border: `1px solid ${color}22`,
          cursor: 'default',
          transition: 'all 0.2s ease',
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, color }}>{item.subsector}</div>
        <div style={{ fontSize: 24, fontWeight: 700, color, margin: '4px 0' }}>
          {ratio.toFixed(1)}%
        </div>
        <Space size={4} style={{ fontSize: 12, color: '#64748B' }}>
          <RiseOutlined style={{ color: '#059669', fontSize: 11 }} />
          <span>{item.advance_count}/{item.total_stocks}</span>
        </Space>
        <br />
        <Space size={4} style={{ fontSize: 12, color: '#64748B' }}>
          <span>涨幅</span>
          <span style={{
            fontWeight: 500,
            color: item.avg_change_pct >= 0 ? '#059669' : '#DC2626',
          }}>
            {item.avg_change_pct >= 0 ? '+' : ''}{item.avg_change_pct.toFixed(2)}%
          </span>
        </Space>
        <br />
        <Space size={4} style={{ fontSize: 11, color: '#94A3B8' }}>
          <span>成交额 {item.turnover.toFixed(0)}亿</span>
        </Space>
      </div>
    </Col>
  )
}

// ─── 子组件: 主题状态标签 ────────────────────────────────────
const ThemeStateBadge: React.FC<{ state: string; score: number }> = ({ state, score }) => {
  const cfg = THEME_STATE_MAP[state] || THEME_STATE_MAP['中性']
  return (
    <Card style={{ ...CARD_STYLE, borderLeft: '4px solid #7C3AED', borderRadius: 10 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>主题状态</Text>
      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '6px 16px', borderRadius: 999,
            fontSize: 20, fontWeight: 700,
            color: cfg.color, backgroundColor: cfg.bg,
          }}
        >
          <ThunderboltOutlined />
          {cfg.label}
        </span>
      </div>
      <div style={{ marginTop: 12 }}>
        <Space size={4}>
          <Text style={{ fontSize: 12, color: '#64748B' }}>情绪分</Text>
          <Tooltip title={`${(score * 100).toFixed(0)}/100`}>
            <Progress
              percent={Number((score * 100).toFixed(0))}
              size="small"
              strokeColor={score >= 0.7 ? '#059669' : score >= 0.4 ? '#D97706' : '#DC2626'}
              style={{ width: 100, margin: 0 }}
            />
          </Tooltip>
        </Space>
      </div>
    </Card>
  )
}

// ─── 子组件: 建议仓位卡片 ────────────────────────────────────
const WeightCard: React.FC<{ weight: number; strength: number }> = ({ weight, strength }) => {
  const w = String(weight)
  const cfg = WEIGHT_CONFIG[w] || { label: '半仓', color: '#64748B' }
  return (
    <Card style={{ ...CARD_STYLE, borderLeft: '4px solid #2563EB', borderRadius: 10 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>建议仓位</Text>
      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 32, fontWeight: 700, color: cfg.color }}>
          {weight}%
        </span>
        <Tag color={cfg.color} style={{ fontSize: 13, padding: '2px 10px' }}>
          {cfg.label}
        </Tag>
      </div>
      <div style={{ marginTop: 8 }}>
        <Space>
          <Text style={{ fontSize: 12, color: '#64748B' }}>相对强度</Text>
          <Text style={{
            fontSize: 14, fontWeight: 600,
            color: strength >= 1 ? '#059669' : '#DC2626',
          }}>
            {strength.toFixed(2)}
          </Text>
          <Text style={{ fontSize: 12, color: '#64748B' }}>
            {strength >= 1 ? '跑赢全A' : '跑输全A'}
          </Text>
        </Space>
      </div>
    </Card>
  )
}

// ─── 子组件: 上涨家数占比 ────────────────────────────────────
const AdvanceRatioCard: React.FC<{ ratio: number }> = ({ ratio }) => {
  const strokeColor = ratio >= 60 ? '#059669' : ratio >= 40 ? '#D97706' : '#DC2626'
  const tagColor = ratio >= 60 ? 'success' : ratio >= 40 ? 'warning' : 'error'
  const tagLabel = ratio >= 60 ? '偏强' : ratio >= 40 ? '中性' : '偏弱'
  return (
    <Card style={{ ...CARD_STYLE, borderLeft: '4px solid #059669', borderRadius: 10 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>上涨家数占比</Text>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
        <span style={{ fontSize: 28, fontWeight: 600, color: '#0F172A' }}>
          {ratio.toFixed(1)}
        </span>
        <span style={{ fontSize: 14, color: '#64748B' }}>%</span>
      </div>
      <Progress
        percent={Number(ratio.toFixed(0))}
        size="small"
        strokeColor={strokeColor}
        style={{ marginTop: 8 }}
      />
      <div style={{ marginTop: 4 }}>
        <Tag color={tagColor}>{tagLabel}</Tag>
      </div>
    </Card>
  )
}

// ─── ETF 表格列 ──────────────────────────────────────────────
const ETF_COLUMNS = [
  { title: '代码', dataIndex: 'ticker', key: 'ticker', width: 100 },
  { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
  {
    title: '价格', dataIndex: 'price', key: 'price', width: 100,
    render: (v: number) => v.toFixed(3),
  },
  {
    title: '涨跌幅', dataIndex: 'change_pct', key: 'change_pct', width: 100,
    render: (v: number) => (
      <span style={{ color: v >= 0 ? '#059669' : '#DC2626', fontWeight: 500 }}>
        {v >= 0 ? '+' : ''}{v.toFixed(2)}%
      </span>
    ),
    sorter: (a: any, b: any) => a.change_pct - b.change_pct,
  },
  {
    title: '成交量', dataIndex: 'volume', key: 'volume', width: 110,
    render: (v: number) => (v >= 1e8 ? (v / 1e8).toFixed(2) + '亿' : (v / 1e4).toFixed(0) + '万'),
  },
  {
    title: '成交额', dataIndex: 'amount', key: 'amount', width: 120,
    render: (v: number) => {
      if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
      if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
      return v.toFixed(0)
    },
    sorter: (a: any, b: any) => a.amount - b.amount,
  },
]

// ═══════════════════════════════════════════════════════════════
// SemiTheme Component
// ═══════════════════════════════════════════════════════════════
export default function SemiTheme() {
  const { data: statusResult, isLoading: loadingStatus, error: statusError, refetch: refetchStatus } = useSemiThemeStatus()
  const { data: subsectorsResult, isLoading: loadingSubsectors, error: subsectorsError, refetch: refetchSubsectors } = useSemiSubsectors()
  const { data: historyResult, isLoading: loadingHistory, error: historyError } = useSemiHistory(60)

  // ─── 解包 ApiResult ─────────────────────────────────────────
  const status = statusResult?.data ?? null
  const subsectors = subsectorsResult?.data ?? null
  const history = historyResult?.data ?? null

  const isLoading = loadingStatus || loadingSubsectors || loadingHistory
  const hasError = !!statusError || !!subsectorsError || !!historyError

  // ─── ECharts Option 1: 半导体等权 vs 全A等权 ────────────────
  // NOTE: useMemo MUST stay before any early return to keep hooks order consistent.
  const chartOption1 = useMemo(() => {
    if (!history?.series?.length) return {}
    const dates = history.series.map(p => p.date.slice(5)) // MM-DD
    return {
      tooltip: { trigger: 'axis' as const },
      legend: { data: ['半导体等权', '全A等权'], bottom: 0 },
      grid: { left: 50, right: 16, top: 16, bottom: 40 },
      xAxis: { type: 'category' as const, data: dates, axisLabel: { fontSize: 10, rotate: 30 } },
      yAxis: { type: 'value' as const, scale: true },
      series: [
        {
          name: '半导体等权',
          type: 'line',
          data: history.series.map(p => p.semi_ew),
          smooth: true,
          lineStyle: { width: 2, color: '#2563EB' },
          itemStyle: { color: '#2563EB' },
          areaStyle: { color: 'rgba(37, 99, 235, 0.08)' },
          symbol: 'none',
        },
        {
          name: '全A等权',
          type: 'line',
          data: history.series.map(p => p.all_a_ew),
          smooth: true,
          lineStyle: { width: 2, color: '#64748B' },
          itemStyle: { color: '#64748B' },
          areaStyle: { color: 'rgba(100, 116, 139, 0.08)' },
          symbol: 'none',
        },
      ],
    }
  }, [history])

  // ─── ECharts Option 2: 核心池 vs 广义池 ─────────────────────
  const chartOption2 = useMemo(() => {
    if (!history?.series?.length) return {}
    const dates = history.series.map(p => p.date.slice(5))
    return {
      tooltip: { trigger: 'axis' as const },
      legend: { data: ['核心池等权', '半导体等权(广义)'], bottom: 0 },
      grid: { left: 50, right: 16, top: 16, bottom: 40 },
      xAxis: { type: 'category' as const, data: dates, axisLabel: { fontSize: 10, rotate: 30 } },
      yAxis: { type: 'value' as const, scale: true },
      series: [
        {
          name: '核心池等权',
          type: 'line',
          data: history.series.map(p => p.core_pool_ew),
          smooth: true,
          lineStyle: { width: 2, color: '#059669' },
          itemStyle: { color: '#059669' },
          areaStyle: { color: 'rgba(5, 150, 105, 0.08)' },
          symbol: 'none',
        },
        {
          name: '半导体等权(广义)',
          type: 'line',
          data: history.series.map(p => p.semi_ew),
          smooth: true,
          lineStyle: { width: 2, color: '#D97706', type: 'dashed' },
          itemStyle: { color: '#D97706' },
          symbol: 'none',
        },
      ],
    }
  }, [history])

  // ─── 细分方向热力图数据 ─────────────────────────────────────
  const subsectorItems: SubsectorItem[] = subsectors?.items ?? []

  // ─── 全局加载 ───────────────────────────────────────────────
  if (isLoading && !status && !subsectors && !history) {
    return <LoadingState tip="加载半导体主题数据..." size="large" />
  }

  // ─── 全局错误 ───────────────────────────────────────────────
  if (hasError && !status && !subsectors && !history) {
    const errMsg = statusError?.message || subsectorsError?.message || historyError?.message || '数据加载失败'
    return (
      <ErrorState
        message="半导体主题数据加载失败"
        description={errMsg}
        onRetry={() => { refetchStatus(); refetchSubsectors() }}
      />
    )
  }

  // ─── 空状态 ─────────────────────────────────────────────────
  if (!status) {
    return <EmptyState description="暂无半导体主题数据" />
  }

  return (
    <div style={{ maxWidth: 1600, margin: '0 auto' }}>
      {/* ─── Header ─────────────────────────────────────────── */}
      <PageHeader
        title="📡 半导体主题看板"
        updatedAt={status.updated_at}
        dataSource="Hermes 主题引擎 v5.6"
      />

      {/* ══════════════════════════════════════════════════════ */}
      {/* 第1行: 核心指标 (4 MetricCards)                        */}
      {/* ══════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 8 }}>
        {/* 1. 成交额占比 */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="成交额占比"
            value={status.metrics.turnover_share.toFixed(1)}
            suffix="%"
            color="primary"
          />
        </Col>

        {/* 2. 上涨家数占比 */}
        <Col xs={24} sm={12} lg={6}>
          <AdvanceRatioCard ratio={status.metrics.advance_ratio} />
        </Col>

        {/* 3. 主题状态标签 */}
        <Col xs={24} sm={12} lg={6}>
          <ThemeStateBadge state={status.theme_state} score={status.sentiment_score} />
        </Col>

        {/* 4. 建议仓位 */}
        <Col xs={24} sm={12} lg={6}>
          <WeightCard weight={status.theme_weight} strength={status.metrics.relative_strength} />
        </Col>
      </Row>

      {/* ══════════════════════════════════════════════════════ */}
      {/* 第2行: 曲线对比 (2 ECharts)                           */}
      {/* ══════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 8 }}>
        <Col xs={24} lg={12}>
          <Card style={CARD_STYLE} title={
            <Space>
              <BarChartOutlined />
              <span>半导体等权 vs 全A等权</span>
              {status && (
                <Tag color={status.metrics.relative_strength >= 1 ? 'success' : 'error'}>
                  相对强度 {status.metrics.relative_strength.toFixed(2)}
                </Tag>
              )}
            </Space>
          }>
            {loadingHistory && !history
              ? <LoadingState tip="加载历史数据..." size="default" />
              : (!history?.series?.length
                ? <EmptyState description="暂无历史数据" />
                : <ReactEChartsCore option={chartOption1} style={{ height: 320 }} />
              )
            }
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card style={CARD_STYLE} title={
            <Space>
              <FundOutlined />
              <span>核心池 vs 广义池</span>
              {status && (
                <Tag color={status.metrics.core_pool_return > status.metrics.broad_pool_return ? 'success' : 'default'}>
                  核心{status.metrics.core_pool_return > status.metrics.broad_pool_return ? '↑' : '↓'} {Math.abs(status.metrics.core_pool_return - status.metrics.broad_pool_return).toFixed(2)}%
                </Tag>
              )}
            </Space>
          }>
            {loadingHistory && !history
              ? <LoadingState tip="加载历史数据..." size="default" />
              : (!history?.series?.length
                ? <EmptyState description="暂无历史数据" />
                : <ReactEChartsCore option={chartOption2} style={{ height: 320 }} />
              )
            }
          </Card>
        </Col>
      </Row>

      {/* ══════════════════════════════════════════════════════ */}
      {/* 第3行: 细分方向热力图                                  */}
      {/* ══════════════════════════════════════════════════════ */}
      <Card style={CARD_STYLE} styles={{ body: { paddingBottom: 8 } }}>
        <div style={SECTION_TITLE}>
          <Space>
            <TeamOutlined />
            <span>细分方向热力图</span>
            {subsectors && (
              <Text style={{ fontSize: 12, color: '#64748B', fontWeight: 400 }}>
                更新于 {subsectors.updated_at?.slice(5, 16) || '—'}
              </Text>
            )}
          </Space>
        </div>

        {loadingSubsectors && !subsectors ? (
          <LoadingState tip="加载细分方向..." size="default" />
        ) : subsectorItems.length === 0 ? (
          <EmptyState description="暂无细分方向数据" />
        ) : (
          <Row gutter={[12, 12]}>
            {subsectorItems.map((item) => (
              <SubsectorCard key={item.subsector} item={item} />
            ))}
          </Row>
        )}
      </Card>

      {/* ══════════════════════════════════════════════════════ */}
      {/* 第4行: ETF 篮子表现                                   */}
      {/* ══════════════════════════════════════════════════════ */}
      <Card style={CARD_STYLE}>
        <div style={SECTION_TITLE}>
          <Space>
            <FundOutlined />
            <span>ETF 篮子表现</span>
          </Space>
        </div>

        {status.etf_basket?.length > 0 ? (
          <Table
            dataSource={status.etf_basket}
            columns={ETF_COLUMNS}
            rowKey="ticker"
            pagination={false}
            size="small"
          />
        ) : (
          <EmptyState description="暂无ETF数据" />
        )}
      </Card>

      {/* ══════════════════════════════════════════════════════ */}
      {/* 第5行: 关键事件 + 重仓股                              */}
      {/* ══════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {/* 关键事件 */}
        <Col xs={24} lg={12}>
          <Card style={CARD_STYLE}>
            <div style={SECTION_TITLE}>
              <Space>
                <ThunderboltOutlined />
                <span>关键事件</span>
              </Space>
            </div>
            {status.key_events?.length > 0 ? (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {status.key_events.map((evt: any, i: number) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex', alignItems: 'flex-start', gap: 12,
                      padding: '8px 12px',
                      background: evt.impact === 'positive' ? '#F0FDF4' : evt.impact === 'negative' ? '#FEF2F2' : '#F8FAFC',
                      borderRadius: 8,
                    }}
                  >
                    <div style={{
                      width: 6, height: 6, borderRadius: '50%', marginTop: 6, flexShrink: 0,
                      background: evt.impact === 'positive' ? '#059669' : evt.impact === 'negative' ? '#DC2626' : '#64748B',
                    }} />
                    <div style={{ flex: 1 }}>
                      <Text style={{ fontSize: 13 }}>{evt.title}</Text>
                      <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 2 }}>
                        {evt.date}
                        <Tag
                          color={evt.impact === 'positive' ? 'success' : evt.impact === 'negative' ? 'error' : 'default'}
                          style={{ marginLeft: 8, fontSize: 10 }}
                        >
                          {evt.impact === 'positive' ? '利好' : evt.impact === 'negative' ? '利空' : '中性'}
                        </Tag>
                      </div>
                    </div>
                  </div>
                ))}
              </Space>
            ) : (
              <EmptyState description="暂无关键事件" />
            )}
          </Card>
        </Col>

        {/* 重仓股 */}
        <Col xs={24} lg={12}>
          <Card style={CARD_STYLE}>
            <div style={SECTION_TITLE}>
              <Space>
                <BarChartOutlined />
                <span>核心重仓股</span>
              </Space>
            </div>
            {status.top_holdings?.length > 0 ? (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {status.top_holdings.map((h: any, i: number) => (
                  <div
                    key={h.ticker}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '8px 12px', background: '#F8FAFC', borderRadius: 8,
                    }}
                  >
                    <Space>
                      <Text style={{ fontSize: 12, color: '#94A3B8', width: 20 }}>{i + 1}</Text>
                      <div>
                        <Text style={{ fontSize: 13, fontWeight: 500 }}>{h.name}</Text>
                        <Text style={{ fontSize: 11, color: '#94A3B8', marginLeft: 8 }}>{h.ticker}</Text>
                      </div>
                    </Space>
                    <Space size={12}>
                      <Text style={{ fontSize: 13, color: '#0F172A' }}>{h.weight.toFixed(1)}%</Text>
                      <Text style={{
                        fontSize: 13, fontWeight: 500,
                        color: h.change_pct >= 0 ? '#059669' : '#DC2626',
                      }}>
                        {h.change_pct >= 0 ? '+' : ''}{h.change_pct.toFixed(1)}%
                      </Text>
                    </Space>
                  </div>
                ))}
              </Space>
            ) : (
              <EmptyState description="暂无重仓股数据" />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
