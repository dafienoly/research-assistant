import { useState, type FC, type CSSProperties } from 'react'
import { Card, Row, Col, Table, Tag, Button, Typography, Tabs, Space, Empty } from 'antd'
import {
  ThunderboltOutlined,
  ReloadOutlined,
  WalletOutlined,
  RiseOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import PageHeader from '../components/common/PageHeader'
import MetricCard from '../components/common/MetricCard'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import { useQmtHealth } from '../hooks/useQmtHealth'
import { useQmtAccount } from '../hooks/useQmtAccount'
import { useQmtPositions } from '../hooks/useQmtPositions'
import { useQmtOrders, useQmtTrades } from '../hooks/useQmtOrders'
import { useQmtPlanPositions } from '../hooks/useQmtPlanPositions'
import type { MetricColor } from '../types'
import type { QmtAccount } from '../api/schemas'

const { Text } = Typography

// ─── Helpers ───────────────────────────────────────────────────────

/** Format a number with 2 decimal places and locale separators */
const fmtMoney = (v: number | null | undefined) => {
  if (v == null || isNaN(v)) return '—'
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** QMT online/offline badge */
const QmtStatusBadge: FC<{ connected: boolean }> = ({ connected }) => {
  const color = connected ? '#059669' : '#DC2626'
  const bg = connected ? '#D1FAE5' : '#FEE2E2'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 14px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 600,
        color,
        backgroundColor: bg,
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: color }} />
      {connected ? '在线' : '离线'}
    </span>
  )
}

/** PnL cell with automatic colouring */
const PnLColored: FC<{ value: number | null | undefined; suffix?: string }> = ({ value, suffix = '' }) => {
  if (value == null || isNaN(value)) return <span style={{ color: '#94A3B8' }}>—</span>
  let bg = 'transparent'
  let color = '#0F172A'
  if (value < -8) {
    bg = '#FECACA'
    color = '#DC2626'
  } else if (value < -5) {
    bg = '#FEE2E2'
    color = '#DC2626'
  } else if (value > 0) {
    color = '#059669'
  }
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 6,
        backgroundColor: bg,
        color,
        fontWeight: 600,
        fontSize: 13,
      }}
    >
      {value > 0 ? '+' : ''}
      {value.toFixed(2)}
      {suffix}
    </span>
  )
}

/** Tag for order/trade direction */
const DirectionTag: FC<{ direction: string }> = ({ direction }) => {
  const isBuy = direction === 'buy'
  return (
    <Tag
      color={isBuy ? 'red' : 'green'}
      style={{ borderRadius: 12, fontSize: 11, border: 'none' }}
    >
      {isBuy ? '买入' : '卖出'}
    </Tag>
  )
}

/** Status tag for orders */
const OrderStatusTag: FC<{ status: string }> = ({ status }) => {
  const colorMap: Record<string, string> = {
    '全部成交': 'success',
    '部分成交': 'processing',
    '已撤单': 'error',
    '待报': 'default',
    '已报': 'processing',
    '已撤': 'error',
  }
  return (
    <Tag color={colorMap[status] || 'default'} style={{ borderRadius: 12, fontSize: 11, border: 'none' }}>
      {status}
    </Tag>
  )
}

// ─── Card style ────────────────────────────────────────────────────

const CARD_STYLE: CSSProperties = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
}

// ─── Column definitions (module-level) ─────────────────────────────

/** Safe number formatting helpers to prevent 'toFixed/toLocaleString of undefined' crashes */
const safeFixed = (v: number | null | undefined, digits = 2): string => {
  if (v == null || isNaN(v)) return '—'
  return v.toFixed(digits)
}
const safeLocale = (v: number | null | undefined): string => {
  if (v == null || isNaN(v)) return '—'
  return v.toLocaleString()
}
const safePercent = (v: number | null | undefined): string => {
  if (v == null || isNaN(v)) return '—%'
  return `${v.toFixed(1)}%`
}

const POSITION_COLUMNS = [
  {
    title: '代码', dataIndex: 'code', key: 'code', width: 100,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 120, ellipsis: true },
  {
    title: '持仓数量', dataIndex: 'volume', key: 'volume', width: 90, align: 'right' as const,
    render: (v: number | null | undefined) => safeLocale(v),
  },
  {
    title: '成本价', dataIndex: 'cost_price', key: 'cost_price', width: 90, align: 'right' as const,
    render: (v: number | null | undefined) => safeFixed(v, 3),
  },
  {
    title: '现价', dataIndex: 'current_price', key: 'current_price', width: 90, align: 'right' as const,
    render: (v: number | null | undefined) => safeFixed(v, 3),
  },
  {
    title: '盈亏', dataIndex: 'pnl', key: 'pnl', width: 110, align: 'right' as const,
    render: (v: number | null | undefined) => <PnLColored value={v} />,
  },
  {
    title: '盈亏%', dataIndex: 'pnl_pct', key: 'pnl_pct', width: 90, align: 'right' as const,
    render: (v: number | null | undefined) => <PnLColored value={v} suffix="%" />,
  },
]

const ORDER_COLUMNS = [
  {
    title: '委托编号', dataIndex: 'id', key: 'id', width: 160,
    render: (v: string) => <code style={{ fontSize: 11, color: '#64748B' }}>{v}</code>,
  },
  {
    title: '代码', dataIndex: 'code', key: 'code', width: 90,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 80, ellipsis: true },
  {
    title: '方向', dataIndex: 'direction', key: 'direction', width: 60,
    render: (v: string) => <DirectionTag direction={v} />,
  },
  {
    title: '委托价', dataIndex: 'price', key: 'price', width: 80, align: 'right' as const,
    render: (v: number | null | undefined) => safeFixed(v, 3),
  },
  {
    title: '委托量', dataIndex: 'volume', key: 'volume', width: 70, align: 'right' as const,
    render: (v: number | null | undefined) => safeLocale(v),
  },
  {
    title: '已成交', dataIndex: 'traded_volume', key: 'traded_volume', width: 70, align: 'right' as const,
    render: (v: number | null | undefined) => safeLocale(v),
  },
  {
    title: '状态', dataIndex: 'status', key: 'status', width: 70,
    render: (v: string) => <OrderStatusTag status={v} />,
  },
  {
    title: '委托时间', dataIndex: 'created_at', key: 'created_at', width: 160,
    render: (v: string) => (v ? <Text style={{ fontSize: 12, color: '#64748B' }}>{v}</Text> : '-'),
  },
]

const TRADE_COLUMNS = [
  {
    title: '成交编号', dataIndex: 'id', key: 'id', width: 160,
    render: (v: string) => <code style={{ fontSize: 11, color: '#64748B' }}>{v}</code>,
  },
  {
    title: '代码', dataIndex: 'code', key: 'code', width: 90,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 80, ellipsis: true },
  {
    title: '方向', dataIndex: 'direction', key: 'direction', width: 60,
    render: (v: string) => <DirectionTag direction={v} />,
  },
  {
    title: '成交价', dataIndex: 'price', key: 'price', width: 80, align: 'right' as const,
    render: (v: number | null | undefined) => safeFixed(v, 3),
  },
  {
    title: '成交量', dataIndex: 'volume', key: 'volume', width: 70, align: 'right' as const,
    render: (v: number | null | undefined) => safeLocale(v),
  },
  {
    title: '成交额', dataIndex: 'amount', key: 'amount', width: 100, align: 'right' as const,
    render: (v: number | null | undefined) => fmtMoney(v),
  },
  {
    title: '成交时间', dataIndex: 'traded_at', key: 'traded_at', width: 160,
    render: (v: string) => (v ? <Text style={{ fontSize: 12, color: '#64748B' }}>{v}</Text> : '-'),
  },
]

const PLAN_COLUMNS = [
  {
    title: '代码', dataIndex: 'code', key: 'code', width: 100,
    render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
  },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100, ellipsis: true },
  {
    title: '计划权重', dataIndex: 'target_weight', key: 'target_weight', width: 100, align: 'right' as const,
    render: (v: number | null | undefined) => safePercent(v),
  },
  {
    title: '实际权重', dataIndex: 'actual_weight', key: 'actual_weight', width: 100, align: 'right' as const,
    render: (v: number | null | undefined) => safePercent(v),
  },
  {
    title: '偏差', dataIndex: 'diff', key: 'diff', width: 90, align: 'right' as const,
    render: (v: number | null | undefined) => {
      if (v == null || isNaN(v)) return <span style={{ color: '#94A3B8' }}>—</span>
      const color = Math.abs(v) > 2 ? '#DC2626' : Math.abs(v) > 1 ? '#D97706' : '#059669'
      return <span style={{ color, fontWeight: 600 }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>
    },
  },
]

// ─── Page Component ────────────────────────────────────────────────

const QMTSpot: FC = () => {
  // ─── Hooks ────────────────────────────────────────────────────
  const { data: healthResp, isLoading: healthLoading, isError: healthError, error: healthErr, refetch: refetchHealth } = useQmtHealth()
  const { data: acctResp, isLoading: acctLoading, refetch: refetchAcct } = useQmtAccount()
  const { data: posResp, isLoading: posLoading, refetch: refetchPos } = useQmtPositions()
  const { data: ordResp, isLoading: ordLoading, refetch: refetchOrd } = useQmtOrders()
  const { data: tradeResp, isLoading: tradeLoading, refetch: refetchTrade } = useQmtTrades()
  const { data: planResp, isLoading: planLoading, refetch: refetchPlan } = useQmtPlanPositions()

  // ─── Unwrap ApiResult ─────────────────────────────────────────
  const qmtData = healthResp?.data

  // Backend returns { accounts: [{ balance, available, ... }], total_asset, available_cash }
  // Frontend expects flat QmtAccount { total_assets, available, market_value, pnl, pnl_pct, ... }
  const rawAcct = acctResp?.data as Record<string, unknown> | undefined
  const acctArr = rawAcct?.accounts as Array<Record<string, unknown>> | undefined
  const acctRecord = acctArr?.[0]
  const a = (k: string, fallback = 0): number => {
    const v = acctRecord?.[k]
    return typeof v === 'number' ? v : fallback
  }
  const acctFlat: QmtAccount | null = acctRecord ? {
    total_assets: a('m_dTotalAsset') || a('total_asset'),
    available: a('m_dAvailable') || a('available'),
    market_value: a('m_dMarketValue') || a('market_value'),
    pnl: a('m_dProfitLossTotal') || a('m_dProfitLoss') || a('profit_loss_total'),
    pnl_pct: 0,
    frozen: a('m_dFrozen') || a('frozen'),
    currency: '元',
  } : null

  // Backend positions: { positions: [{ ticker, name, volume, cost_price, current_price, profit_loss_pct, market_value }] }
  // Frontend columns expect: { code, name, volume, cost_price, current_price, pnl, pnl_pct }
  const rawPos = posResp?.data as Record<string, unknown> | undefined
  const posArr = rawPos?.positions as Array<Record<string, unknown>> | undefined
  const positions = Array.isArray(posArr) ? posArr.map((p: Record<string, unknown>) => ({
    code: p.m_strStockCode ?? p.stock_code ?? p.ticker ?? p.code ?? '',
    name: p.m_strStockName ?? p.stock_name ?? p.name ?? '',
    volume: Number(p.m_nVolume ?? p.volume ?? 0),
    cost_price: Number(p.m_dCostPrice ?? p.cost_price ?? 0),
    current_price: Number(p.m_dLastPrice ?? p.m_dPrice ?? p.last_price ?? p.current_price ?? 0),
    pnl: Number(p.m_dProfitLoss ?? p.profit_loss ?? Number(p.m_dMarketValue ?? p.market_value ?? 0) - Number(p.m_dCostPrice ?? p.cost_price ?? 0) * Number(p.m_nVolume ?? p.volume ?? 0)),
    pnl_pct: Number(p.m_dProfitLossPct ?? p.profit_loss_pct ?? 0),
    market: p.market ?? '',
  })) : []

  // Backend orders: NOT_FOUND → show empty
  const ordRaw = ordResp?.data
  const orders = Array.isArray(ordRaw) ? ordRaw : []

  // Trades
  const tradeRaw = tradeResp?.data
  const trades = Array.isArray(tradeRaw) ? tradeRaw : []

  // Plan positions
  const planRaw = planResp?.data
  const planPositions = Array.isArray(planRaw) ? planRaw : []

  const anyLoading = healthLoading || acctLoading || posLoading
  const anyRefetching = ordLoading || tradeLoading || planLoading

  // ─── Tab state ────────────────────────────────────────────────
  const [orderTab, setOrderTab] = useState('orders')

  // ─── Full refresh ─────────────────────────────────────────────
  const handleRefresh = () => {
    refetchHealth()
    refetchAcct()
    refetchPos()
    refetchOrd()
    refetchTrade()
    refetchPlan()
  }

  // ─── Initial load spinner ─────────────────────────────────────
  if (anyLoading && !qmtData) {
    return <LoadingState tip="加载 QMT 实盘数据..." size="large" />
  }

  // ─── Initial error (no cached data) ───────────────────────────
  if (healthError && !qmtData) {
    return (
      <ErrorState
        message="QMT 连接失败"
        description={healthErr?.message || '无法连接到 QMT 网关，请检查网关状态。'}
        onRetry={() => refetchHealth()}
      />
    )
  }

  // ─── Render ───────────────────────────────────────────────────
  return (
    <div>
      {/* ══════════════════════════════════════════════════════════ */}
      {/* 1. Header + QMT Health Status                            */}
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
        <PageHeader title="💹 QMT 实盘中心" dataSource="QMT 交易网关" />
        <Space size={12} wrap>
          <QmtStatusBadge connected={qmtData?.connected ?? false} />
          {qmtData && (
            <Text style={{ fontSize: 11, color: '#94A3B8' }}>
              模式: {qmtData.mode} | 延迟: {qmtData.latency_ms}ms | v
              {qmtData.version}
            </Text>
          )}
          <Button
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            loading={anyLoading || anyRefetching}
          >
            刷新
          </Button>
        </Space>
      </div>

      {/* Offline banner */}
      {qmtData && !qmtData.connected && (
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
          <ThunderboltOutlined style={{ color: '#DC2626', fontSize: 18 }} />
          <Text style={{ color: '#DC2626', fontWeight: 600, fontSize: 14 }}>
            QMT 网关离线 — 数据可能不是最新的，请检查 QMT 网关连接状态。
          </Text>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 2. Account Assets — MetricCard ×4                        */}
      {/* ══════════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="总资产"
            value={acctFlat ? fmtMoney(acctFlat.total_assets) : '—'}
            color="primary"
            loading={acctLoading && !acctFlat}
            suffix={acctFlat?.currency || '元'}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="可用资金"
            value={acctFlat ? fmtMoney(acctFlat.available) : '—'}
            color="success"
            loading={acctLoading && !acctFlat}
            suffix={acctFlat?.currency || '元'}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="持仓市值"
            value={acctFlat ? fmtMoney(acctFlat.market_value) : '—'}
            color="info"
            loading={acctLoading && !acctFlat}
            suffix={acctFlat?.currency || '元'}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title="总盈亏"
            value={acctFlat ? fmtMoney(acctFlat.pnl) : '—'}
            color={(acctFlat && acctFlat.pnl >= 0 ? 'success' : 'error') as MetricColor}
            loading={acctLoading && !acctFlat}
            suffix={acctFlat?.currency || '元'}
            trend={acctFlat?.pnl_pct}
          />
        </Col>
      </Row>

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 3. Real Positions Table                                  */}
      {/* ══════════════════════════════════════════════════════════ */}
      <Card
        style={{ ...CARD_STYLE, marginBottom: 24 }}
        title={
          <Space>
            <WalletOutlined style={{ color: '#2563EB' }} />
            <span>真实持仓</span>
            {positions.length > 0 && (
              <Tag style={{ borderRadius: 12, fontSize: 11, border: 'none', marginLeft: 4 }}>
                {positions.length} 只
              </Tag>
            )}
          </Space>
        }
      >
        {positions.length === 0 ? (
          <Empty description="暂无持仓数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            dataSource={positions}
            columns={POSITION_COLUMNS}
            rowKey="code"
            size="small"
            pagination={positions.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
          />
        )}
      </Card>

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 4. Orders + Trades (tab switch)                          */}
      {/* ══════════════════════════════════════════════════════════ */}
      <Card style={{ ...CARD_STYLE, marginBottom: 24 }} styles={{ body: { padding: 0 } }}>
        <Tabs
          activeKey={orderTab}
          onChange={setOrderTab}
          tabBarStyle={{ padding: '0 16px', margin: 0 }}
          items={[
            {
              key: 'orders',
              label: (
                <span>
                  <SwapOutlined style={{ marginRight: 4 }} />
                  当日委托
                  {orders.length > 0 && (
                    <Tag
                      style={{ marginLeft: 6, borderRadius: 12, fontSize: 10, border: 'none' }}
                    >
                      {orders.length}
                    </Tag>
                  )}
                </span>
              ),
              children:
                orders.length === 0 ? (
                  <div style={{ padding: 24 }}>
                    <Empty description="暂无当日委托" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  </div>
                ) : (
                  <Table
                    dataSource={orders}
                    columns={ORDER_COLUMNS}
                    rowKey="id"
                    size="small"
                    pagination={
                      orders.length > 20 ? { pageSize: 20, showSizeChanger: false } : false
                    }
                    style={{ borderTop: '1px solid #E2E8F0' }}
                  />
                ),
            },
            {
              key: 'trades',
              label: (
                <span>
                  <RiseOutlined style={{ marginRight: 4 }} />
                  当日成交
                  {trades.length > 0 && (
                    <Tag
                      style={{ marginLeft: 6, borderRadius: 12, fontSize: 10, border: 'none' }}
                    >
                      {trades.length}
                    </Tag>
                  )}
                </span>
              ),
              children:
                trades.length === 0 ? (
                  <div style={{ padding: 24 }}>
                    <Empty description="暂无当日成交" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  </div>
                ) : (
                  <Table
                    dataSource={trades}
                    columns={TRADE_COLUMNS}
                    rowKey="id"
                    size="small"
                    pagination={
                      trades.length > 20 ? { pageSize: 20, showSizeChanger: false } : false
                    }
                    style={{ borderTop: '1px solid #E2E8F0' }}
                  />
                ),
            },
          ]}
        />
      </Card>

      {/* ══════════════════════════════════════════════════════════ */}
      {/* 5. Plan vs Actual Comparison                             */}
      {/* ══════════════════════════════════════════════════════════ */}
      <Card
        style={CARD_STYLE}
        title={
          <Space>
            <span style={{ fontSize: 16 }}>📋</span>
            <span>计划组合 vs 真实持仓</span>
            {planPositions.length > 0 && (
              <Tag style={{ borderRadius: 12, fontSize: 11, border: 'none', marginLeft: 4 }}>
                {planPositions.length} 只
              </Tag>
            )}
          </Space>
        }
      >
        {planPositions.length === 0 ? (
          <Empty description="暂无计划组合数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            dataSource={planPositions}
            columns={PLAN_COLUMNS}
            rowKey="code"
            size="small"
            pagination={
              planPositions.length > 20 ? { pageSize: 20, showSizeChanger: false } : false
            }
          />
        )}
      </Card>
    </div>
  )
}

export default QMTSpot
