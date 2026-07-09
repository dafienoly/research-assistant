import { useState, type FC, type CSSProperties } from 'react'
import { Card, Row, Col, Table, Tag, Button, Typography, Tabs, Space, Empty, Tooltip } from 'antd'
import {
  ThunderboltOutlined,
  ReloadOutlined,
  WalletOutlined,
  RiseOutlined,
  SwapOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  HistoryOutlined,
  InfoCircleOutlined,
  FileTextOutlined,
  BlockOutlined,
} from '@ant-design/icons'
import PageHeader from '../components/common/PageHeader'
import MetricCard from '../components/common/MetricCard'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import { usePaperStatus, usePaperDashboard } from '../hooks/usePaperDashboard'
import { useShadowStatus, useShadowDashboard } from '../hooks/useShadowDashboard'
import type { ShadowPlanTrade, ShadowFilledTrade, ShadowDailyReview, ShadowRiskInterception } from '../api/schemas'
import type { MetricColor } from '../types'

const { Text } = Typography

// ─── Helpers ───────────────────────────────────────────────────────

/** Format a number with 2 decimal places and locale separators */
const fmtMoney = (v: number) =>
  v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Format percentage with sign */
const fmtPct = (v: number | null | undefined, digits = 2): string => {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`
}

/** PnL colored span */
const PnLText: FC<{ value: number; suffix?: string; digits?: number }> = ({
  value,
  suffix = '',
  digits = 2,
}) => {
  const color = value >= 0 ? '#059669' : '#DC2626'
  return (
    <span style={{ color, fontWeight: 600, fontSize: 13 }}>
      {value >= 0 ? '+' : ''}
      {value.toFixed(digits)}
      {suffix}
    </span>
  )
}

/** Direction tag */
const DirectionTag: FC<{ direction: string }> = ({ direction }) => {
  const isBuy = direction === 'buy'
  return (
    <Tag color={isBuy ? 'red' : 'green'} style={{ borderRadius: 12, fontSize: 11, border: 'none' }}>
      {isBuy ? '买入' : '卖出'}
    </Tag>
  )
}

/** Trade status tag */
const TradeStatusTag: FC<{ status: string }> = ({ status }) => {
  const colorMap: Record<string, string> = {
    planned: 'default',
    filled: 'success',
    partial: 'processing',
    blocked: 'error',
    cancelled: 'default',
  }
  const labelMap: Record<string, string> = {
    planned: '计划中',
    filled: '已成交',
    partial: '部分成交',
    blocked: '已拦截',
    cancelled: '已撤销',
  }
  return (
    <Tag color={colorMap[status] || 'default'} style={{ borderRadius: 12, fontSize: 11, border: 'none' }}>
      {labelMap[status] || status}
    </Tag>
  )
}

/** NOT_READY badge */
const NotReadyBadge: FC<{ notReady: boolean }> = ({ notReady }) => {
  if (!notReady) return null
  return (
    <Tag color="error" style={{ borderRadius: 12, fontSize: 11, border: 'none', fontWeight: 600 }}>
      ⚠ NOT READY
    </Tag>
  )
}

/** Warning banner for stale/error data */
const WarningBanner: FC<{ message: string }> = ({ message }) => (
  <div
    style={{
      background: '#FEF2F2',
      border: '1px solid #FEE2E2',
      borderRadius: 10,
      padding: '12px 20px',
      marginBottom: 20,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}
  >
    <WarningOutlined style={{ color: '#DC2626', fontSize: 18 }} />
    <Text style={{ color: '#DC2626', fontWeight: 600, fontSize: 14 }}>{message}</Text>
  </div>
)

// ─── Card style ──────────────────────────────────────────────────

const CARD_STYLE: CSSProperties = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
}

// ─── Column definitions (module-level, no dependency on component state) ──

const PLAN_TRADE_COLUMNS = [
  {
    title: '代码', dataIndex: 'symbol', key: 'symbol', width: 100,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100, ellipsis: true },
  {
    title: '方向', dataIndex: 'direction', key: 'direction', width: 60,
    render: (v: string) => <DirectionTag direction={v} />,
  },
  {
    title: '价格', dataIndex: 'price', key: 'price', width: 90, align: 'right' as const,
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '股数', dataIndex: 'shares', key: 'shares', width: 80, align: 'right' as const,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '权重%', dataIndex: 'weight_pct', key: 'weight_pct', width: 70, align: 'right' as const,
    render: (v: number | undefined) => (v != null ? v.toFixed(1) : '-'),
  },
  {
    title: '状态', dataIndex: 'status', key: 'status', width: 80,
    render: (v: string) => <TradeStatusTag status={v} />,
  },
  {
    title: '拦截原因', dataIndex: 'block_reason', key: 'block_reason', width: 140, ellipsis: true,
    render: (v: string | undefined) =>
      v ? <Tooltip title={v}><Text style={{ color: '#DC2626', fontSize: 12 }}>{v}</Text></Tooltip> : '-',
  },
]

const FILL_COLUMNS = [
  {
    title: '成交号', dataIndex: 'trade_id', key: 'trade_id', width: 110,
    render: (v: string) => <code style={{ fontSize: 11, color: '#64748B' }}>{v}</code>,
  },
  {
    title: '代码', dataIndex: 'symbol', key: 'symbol', width: 90,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 80, ellipsis: true },
  {
    title: '方向', dataIndex: 'direction', key: 'direction', width: 60,
    render: (v: string) => <DirectionTag direction={v} />,
  },
  {
    title: '成交价', dataIndex: 'fill_price', key: 'fill_price', width: 90, align: 'right' as const,
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '数量', dataIndex: 'fill_shares', key: 'fill_shares', width: 70, align: 'right' as const,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '金额', dataIndex: 'fill_amount', key: 'fill_amount', width: 100, align: 'right' as const,
    render: (v: number) => fmtMoney(v),
  },
  {
    title: '佣金', dataIndex: 'fee', key: 'fee', width: 80, align: 'right' as const,
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160,
    render: (v: string) =>
      v ? <Text style={{ fontSize: 12, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text> : '-',
  },
]

const DAILY_REVIEW_COLUMNS = [
  {
    title: '日期', dataIndex: 'date', key: 'date', width: 100,
    render: (v: string) => <code style={{ fontSize: 12, color: '#475569' }}>{v}</code>,
  },
  {
    title: '组合收益', dataIndex: 'strategy_return_pct', key: 'strategy_return_pct', width: 100, align: 'right' as const,
    render: (v: number) => <PnLText value={v} suffix="%" />,
  },
  {
    title: '基准收益', dataIndex: 'benchmark_return_pct', key: 'benchmark_return_pct', width: 100, align: 'right' as const,
    render: (v: number | null) => (v != null ? <PnLText value={v} suffix="%" /> : <Text type="secondary">—</Text>),
  },
  {
    title: '超额收益', dataIndex: 'excess_return_pct', key: 'excess_return_pct', width: 100, align: 'right' as const,
    render: (v: number | null) => (v != null ? <PnLText value={v} suffix="%" /> : <Text type="secondary">—</Text>),
  },
  {
    title: '对比', dataIndex: 'vs_benchmark', key: 'vs_benchmark', width: 70,
    render: (v: string) => {
      const isWin = v === '跑赢'
      return <Tag color={isWin ? 'success' : 'error'} style={{ borderRadius: 12, fontSize: 11, border: 'none' }}>{v}</Tag>
    },
  },
  {
    title: '状态', dataIndex: 'not_ready', key: 'not_ready', width: 100,
    render: (v: boolean) => <NotReadyBadge notReady={v} />,
  },
  {
    title: '拦截', dataIndex: 'n_blocked', key: 'n_blocked', width: 60, align: 'right' as const,
    render: (v: number) => (v > 0 ? <Text style={{ color: '#DC2626', fontWeight: 600 }}>{v}</Text> : v),
  },
  {
    title: '成交', dataIndex: 'n_filled', key: 'n_filled', width: 60, align: 'right' as const,
    render: (v: number) => v,
  },
  {
    title: '摘要', dataIndex: 'summary', key: 'summary', width: 200, ellipsis: true,
  },
]

const RISK_COLUMNS = [
  {
    title: '代码', dataIndex: 'symbol', key: 'symbol', width: 100,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100, ellipsis: true },
  {
    title: '拦截原因', dataIndex: 'reason', key: 'reason', width: 160,
    render: (v: string) => (
      <Space>
        <BlockOutlined style={{ color: '#DC2626', fontSize: 12 }} />
        <Text style={{ color: '#DC2626', fontWeight: 500, fontSize: 12 }}>{v}</Text>
      </Space>
    ),
  },
  {
    title: '拦截阶段', dataIndex: 'stage', key: 'stage', width: 100,
    render: (v: string) => <Tag style={{ borderRadius: 12, fontSize: 11, border: 'none' }}>{v}</Tag>,
  },
  {
    title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 160,
    render: (v: string) =>
      v ? <Text style={{ fontSize: 12, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text> : '-',
  },
]

// ─── Sub-table components ────────────────────────────────────────

const PlanTradesTable: FC<{ stocks: ShadowPlanTrade[] }> = ({ stocks }) => {
  if (!stocks.length) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="暂无计划交易" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    )
  }
  return (
    <Table
      dataSource={stocks}
      columns={PLAN_TRADE_COLUMNS}
      rowKey={(r) => r.symbol}
      size="small"
      pagination={stocks.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
      style={{ borderTop: '1px solid #E2E8F0' }}
    />
  )
}

const FillsTable: FC<{ trades: ShadowFilledTrade[] }> = ({ trades }) => {
  if (!trades.length) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="暂无模拟成交" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    )
  }
  return (
    <Table
      dataSource={trades}
      columns={FILL_COLUMNS}
      rowKey={(r) => r.trade_id}
      size="small"
      pagination={trades.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
      style={{ borderTop: '1px solid #E2E8F0' }}
    />
  )
}

interface DailyReviewTableProps {
  shadowDash: NonNullable<ReturnType<typeof useShadowDashboard>['data']>['data']
  date: string
}

const DailyReviewTable: FC<{ shadowDash: any; shadowDashDate: string }> = ({ shadowDash, shadowDashDate }) => {
  // Try multi-day data first, otherwise derive from single-day data
  const dailyData: ShadowDailyReview[] = (shadowDash as any)?.daily_summaries ?? []

  const summaries: ShadowDailyReview[] = dailyData.length > 0
    ? dailyData
    : shadowDash
      ? [{
          date: shadowDashDate,
          strategy_return_pct: shadowDash.performance.strategy_return_pct,
          benchmark_return_pct: shadowDash.performance.benchmark_return_pct,
          excess_return_pct: shadowDash.performance.excess_return_pct,
          vs_benchmark: shadowDash.performance.vs_benchmark,
          not_ready: shadowDash.not_ready,
          n_blocked: shadowDash.tradability.n_check_blocked,
          n_filled: shadowDash.execution.n_filled,
          summary: shadowDash.summary,
        }]
      : []

  if (!summaries.length) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="暂无日度复盘数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    )
  }

  return (
    <Table
      dataSource={summaries}
      columns={DAILY_REVIEW_COLUMNS}
      rowKey="date"
      size="small"
      pagination={summaries.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
      style={{ borderTop: '1px solid #E2E8F0' }}
    />
  )
}

const RiskLogTable: FC<{ interceptions: ShadowRiskInterception[] }> = ({ interceptions }) => {
  if (!interceptions.length) {
    return (
      <div style={{ padding: 24 }}>
        <Empty
          description={
            <Space direction="vertical" align="center">
              <CheckCircleOutlined style={{ color: '#059669', fontSize: 24 }} />
              <Text style={{ color: '#059669' }}>今日无风控拦截</Text>
            </Space>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </div>
    )
  }

  // Aggregate reasons
  const reasonCounts: Record<string, number> = {}
  for (const r of interceptions) {
    reasonCounts[r.reason] = (reasonCounts[r.reason] || 0) + 1
  }

  return (
    <div>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #E2E8F0', display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {Object.entries(reasonCounts).map(([reason, count]) => (
          <Tag key={reason} color="error" style={{ borderRadius: 12, fontSize: 11 }}>
            {reason}: {count}次
          </Tag>
        ))}
      </div>
      <Table
        dataSource={interceptions}
        columns={RISK_COLUMNS}
        rowKey={(r) => `${r.symbol}_${r.timestamp}_${r.reason}`}
        size="small"
        pagination={interceptions.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
      />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════
// Page Component
// ═══════════════════════════════════════════════════════════════════

const PaperDashboard: FC = () => {
  // ─── Hooks ────────────────────────────────────────────────────
  const {
    data: paperStatusResp,
    isLoading: paperStatusLoading,
    isError: paperStatusError,
    error: paperStatusErr,
    refetch: refetchPaperStatus,
  } = usePaperStatus()
  const {
    data: paperDashResp,
    isLoading: paperDashLoading,
    refetch: refetchPaperDash,
  } = usePaperDashboard({ last_n: 20 })

  const {
    data: shadowStatusResp,
    isLoading: shadowStatusLoading,
    isError: shadowStatusError,
    error: shadowStatusErr,
    refetch: refetchShadowStatus,
  } = useShadowStatus()
  const {
    data: shadowDashResp,
    isLoading: shadowDashLoading,
    refetch: refetchShadowDash,
  } = useShadowDashboard()

  // ─── Unwrap ApiResult ─────────────────────────────────────────
  const paperStatus = paperStatusResp?.data
  const paperDash = paperDashResp?.data
  const shadowStatus = shadowStatusResp?.data
  const shadowDash = shadowDashResp?.data

  const anyInitLoading = paperStatusLoading && !paperStatus
  const anyLoading = paperDashLoading || shadowDashLoading

  // ─── Tab state ────────────────────────────────────────────────
  const [shadowTab, setShadowTab] = useState('plan')

  // ─── Full refresh ─────────────────────────────────────────────
  const handleRefresh = () => {
    refetchPaperStatus()
    refetchPaperDash()
    refetchShadowStatus()
    refetchShadowDash()
  }

  // ─── Initial load spinner ─────────────────────────────────────
  if (anyInitLoading && !paperStatus) {
    return <LoadingState tip="加载 Paper/Shadow 看板数据..." size="large" />
  }

  // ─── Initial error (no cached data) ───────────────────────────
  if (paperStatusError && !paperStatus) {
    return (
      <ErrorState
        message="Paper 状态加载失败"
        description={paperStatusErr?.message || '无法获取 Paper 交易状态，请检查后台服务。'}
        onRetry={() => refetchPaperStatus()}
      />
    )
  }

  // ══════════════════════════════════════════════════════════════
  // Render
  // ══════════════════════════════════════════════════════════════

  return (
    <div>
      {/* ══════════════════════════════════════════════════════════ */}
      {/* 1. Header + Refresh                                      */}
      {/* ══════════════════════════════════════════════════════════ */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <PageHeader
          title="📋 Paper / Shadow 看板"
          dataSource="Paper Trading Engine + Shadow Trading Engine"
        />
        <Space size={12} wrap>
          {shadowStatus && (
            <NotReadyBadge notReady={shadowStatus.n_not_ready > 0} />
          )}
          <Button
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            loading={anyInitLoading || anyLoading}
          >
            刷新
          </Button>
        </Space>
      </div>

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 2. Error banners                                          */}
      {/* ══════════════════════════════════════════════════════════ */}
      {paperStatusError && paperStatus && (
        <WarningBanner message={`Paper 状态加载失败 — ${paperStatusErr?.message || '请检查后台服务'}`} />
      )}

      {shadowStatusError && shadowStatus && (
        <WarningBanner message={`Shadow 状态加载失败 — ${shadowStatusErr?.message || '请检查后台服务'}`} />
      )}

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 3. Metric Cards — Paper + Shadow Status                   */}
      {/* ══════════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {/* Paper: 运行天数 */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="Paper 运行天数"
            value={paperDash ? String(paperDash.n_trading_days) : '—'}
            color="primary"
            loading={paperDashLoading && !paperDash}
          />
        </Col>
        {/* Paper: 组合收益 vs 半导体同池等权 */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="组合收益 (vs 同池等权)"
            value={paperDash ? fmtPct(paperDash.paper_total_return_pct) : '—'}
            color={(paperDash?.paper_total_return_pct ?? 0) >= 0 ? 'success' : 'error' as MetricColor}
            loading={paperDashLoading && !paperDash}
            trend={
              paperDash?.vs_semiconductor_ew
                ? paperDash.vs_semiconductor_ew.excess_return_pct
                : undefined
            }
          />
        </Col>
        {/* Paper: 执行偏差 (fill rate) */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="执行成交率"
            value={paperDash ? `${paperDash.execution_quality.fill_rate}%` : '—'}
            color={((paperDash?.execution_quality.fill_rate ?? 0) >= 90) ? 'success' : 'warning' as MetricColor}
            loading={paperDashLoading && !paperDash}
          />
        </Col>
        {/* Paper: Sharpe */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="Sharpe 比率"
            value={paperDash ? String(paperDash.paper_sharpe) : '—'}
            color={((paperDash?.paper_sharpe ?? 0) >= 1) ? 'success' : 'warning' as MetricColor}
            loading={paperDashLoading && !paperDash}
            suffix=""
          />
        </Col>
      </Row>

      {/* ── Second row: Shadow status ────────────────────────────── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="Shadow 运行次数"
            value={shadowStatus ? String(shadowStatus.total_runs) : '—'}
            color="primary"
            loading={shadowStatusLoading && !shadowStatus}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="当日计划/实际"
            value={shadowDash ? `${shadowDash.plan.n_stocks ?? 0} / ${shadowDash.execution.n_filled ?? 0}` : '—'}
            color="info"
            loading={shadowDashLoading && !shadowDash}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="风控拦截次数"
            value={shadowDash ? String(shadowDash.risk_interceptions.total_interceptions) : '—'}
            color={(shadowDash?.risk_interceptions.total_interceptions ?? 0) > 0 ? 'error' : 'success' as MetricColor}
            loading={shadowDashLoading && !shadowDash}
            suffix="次"
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="NOT_READY 天数"
            value={shadowStatus ? String(shadowStatus.n_not_ready) : '—'}
            color={(shadowStatus?.n_not_ready ?? 0) > 0 ? 'error' : 'success' as MetricColor}
            loading={shadowStatusLoading && !shadowStatus}
            suffix="天"
          />
        </Col>
      </Row>

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 4. Paper Dashboard Detail Card                            */}
      {/* ══════════════════════════════════════════════════════════ */}
      {paperDash && (
        <Card style={{ ...CARD_STYLE, marginBottom: 16 }} styles={{ body: { padding: '16px 20px' } }}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Text style={{ fontSize: 14, fontWeight: 600, color: '#0F172A' }}>
              <ThunderboltOutlined style={{ marginRight: 6, color: '#2563EB' }} />
              Paper Dashboard 详情
            </Text>
            <Row gutter={16}>
              <Col span={8}>
                <Text style={{ color: '#64748B', fontSize: 12 }}>期间</Text>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{paperDash.period}</div>
              </Col>
              <Col span={4}>
                <Text style={{ color: '#64748B', fontSize: 12 }}>年化收益</Text>
                <div style={{ fontSize: 16, fontWeight: 600 }}>
                  <PnLText value={paperDash.paper_annualized_return_pct} suffix="%" />
                </div>
              </Col>
              <Col span={4}>
                <Text style={{ color: '#64748B', fontSize: 12 }}>波动率</Text>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{paperDash.paper_volatility_pct.toFixed(2)}%</div>
              </Col>
              <Col span={4}>
                <Text style={{ color: '#64748B', fontSize: 12 }}>最大回撤</Text>
                <div style={{ fontSize: 16, fontWeight: 600 }}>
                  <PnLText value={paperDash.paper_max_drawdown_pct} suffix="%" />
                </div>
              </Col>
              <Col span={4}>
                <Text style={{ color: '#64748B', fontSize: 12 }}>胜率</Text>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{paperDash.paper_win_rate_pct}%</div>
              </Col>
            </Row>
            {paperDash.vs_semiconductor_ew && (
              <Row gutter={16} style={{ marginTop: 8 }}>
                <Col span={24}>
                  <Text style={{ color: '#64748B', fontSize: 12 }}>
                    相对半导体同池等权: 基准
                    <PnLText value={paperDash.vs_semiconductor_ew.benchmark_return_pct} suffix="%" /> |
                    超额
                    <PnLText value={paperDash.vs_semiconductor_ew.excess_return_pct} suffix="%" /> |
                    {paperDash.vs_semiconductor_ew.vs_benchmark === '跑赢' ? (
                      <Tag color="success" style={{ borderRadius: 12, fontSize: 11, border: 'none', marginLeft: 4 }}>
                        ✅ 跑赢
                      </Tag>
                    ) : (
                      <Tag color="error" style={{ borderRadius: 12, fontSize: 11, border: 'none', marginLeft: 4 }}>
                        ❌ 跑输 (NOT READY)
                      </Tag>
                    )}
                  </Text>
                </Col>
              </Row>
            )}
            {/* Execution quality */}
            <Row gutter={16} style={{ marginTop: 4 }}>
              <Col span={24}>
                <Text style={{ color: '#64748B', fontSize: 12 }}>
                  执行质量: 已成交 {paperDash.execution_quality.filled} 笔 |
                  部分成交 {paperDash.execution_quality.partial_filled} 笔 |
                  受阻 {paperDash.execution_quality.blocked} 笔 |
                  成交率 {paperDash.execution_quality.fill_rate}%
                </Text>
              </Col>
            </Row>
          </Space>
        </Card>
      )}

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 5. Shadow Dashboard — Tabs                                 */}
      {/* ══════════════════════════════════════════════════════════ */}
      <Card style={CARD_STYLE} styles={{ body: { padding: 0 } }}>
        {!shadowDash ? (
          <div style={{ padding: 24 }}>
            {shadowDashLoading ? (
              <LoadingState tip="加载 Shadow Dashboard..." size="default" />
            ) : (
              <Empty
                description={
                  <Space direction="vertical" align="center">
                    <Text>暂无 Shadow 数据</Text>
                    {shadowStatusError && (
                      <Text type="danger" style={{ fontSize: 12 }}>
                        {shadowStatusErr?.message || '加载失败'}
                      </Text>
                    )}
                  </Space>
                }
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            )}
          </div>
        ) : (
          <Tabs
            activeKey={shadowTab}
            onChange={setShadowTab}
            tabBarStyle={{ padding: '0 16px', margin: 0 }}
            items={[
              {
                key: 'plan',
                label: (
                  <span>
                    <FileTextOutlined style={{ marginRight: 4 }} />
                    计划交易
                    {(shadowDash.plan.stocks?.length ?? 0) > 0 && (
                      <Tag style={{ marginLeft: 6, borderRadius: 12, fontSize: 10, border: 'none' }}>
                        {shadowDash.plan.stocks.length}
                      </Tag>
                    )}
                  </span>
                ),
                children: <PlanTradesTable stocks={shadowDash.plan.stocks ?? []} />,
              },
              {
                key: 'fills',
                label: (
                  <span>
                    <SwapOutlined style={{ marginRight: 4 }} />
                    模拟成交
                    {(shadowDash.execution.trades?.length ?? 0) > 0 && (
                      <Tag style={{ marginLeft: 6, borderRadius: 12, fontSize: 10, border: 'none' }}>
                        {shadowDash.execution.trades.length}
                      </Tag>
                    )}
                  </span>
                ),
                children: <FillsTable trades={shadowDash.execution.trades ?? []} />,
              },
              {
                key: 'review',
                label: (
                  <span>
                    <HistoryOutlined style={{ marginRight: 4 }} />
                    日度复盘
                    <Tag style={{ marginLeft: 6, borderRadius: 12, fontSize: 10, border: 'none' }}>
                      近20日
                    </Tag>
                  </span>
                ),
                children: <DailyReviewTable shadowDash={shadowDash} shadowDashDate={shadowDash.date} />,
              },
              {
                key: 'risk',
                label: (
                  <span>
                    <BlockOutlined style={{ marginRight: 4 }} />
                    风控拦截
                    {shadowDash.risk_interceptions.total_interceptions > 0 && (
                      <Tag color="error" style={{ marginLeft: 6, borderRadius: 12, fontSize: 10, border: 'none' }}>
                        {shadowDash.risk_interceptions.total_interceptions}
                      </Tag>
                    )}
                  </span>
                ),
                children: <RiskLogTable interceptions={shadowDash.risk_interceptions.details ?? []} />,
              },
            ]}
          />
        )}
      </Card>
    </div>
  )
}

export default PaperDashboard
