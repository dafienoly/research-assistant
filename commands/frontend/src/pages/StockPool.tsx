import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  Card, Tabs, Table, Tag, Button, Modal, Spin, Alert,
  Select, Space, Typography, Tooltip, Row, Col, Descriptions,
} from 'antd'
import {
  AuditOutlined, CheckCircleOutlined,
  CloseCircleOutlined, MinusCircleOutlined,
} from '@ant-design/icons'
import PageHeader from '../components/common/PageHeader'
import MetricCard from '../components/common/MetricCard'
import type { UniverseDetail, UniverseAuditResponse } from '../api/schemas'

// ─── Tab definitions ──────────────────────────────────────────────
const UNIVERSE_TABS = [
  { key: 'U0', label: 'U0 全A' },
  { key: 'U1', label: 'U1 可交易' },
  { key: 'U2', label: 'U2 AI/半导体' },
  { key: 'U3', label: 'U3 核心' },
  { key: 'U4', label: 'U4 对照' },
  { key: 'ETF', label: 'ETF替代' },
]

// ─── Helpers ──────────────────────────────────────────────────────
const BASE_URL = import.meta.env.VITE_API_BASE ?? ''

function apiGet<T>(path: string): Promise<T> {
  return fetch(`${BASE_URL}${path}`)
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
    .then((body) => {
      if (!body.ok) throw new Error(body.error?.message || body.error || '请求失败')
      return body.data as T
    })
}

function formatMV(v: number | null | undefined): string {
  if (v == null) return '-'
  const b = v / 1e8
  return b >= 1 ? `${b.toFixed(1)}亿` : `${(v / 1e4).toFixed(0)}万`
}

// ─── Main Component ────────────────────────────────────────────────
export default function StockPool() {
  const [activeTab, setActiveTab] = useState('U0')
  const [universeCache, setUniverseCache] = useState<Record<string, UniverseDetail>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Current tab's data (instant on revisit)
  const universe = universeCache[activeTab] ?? null

  // Audit
  const [auditData, setAuditData] = useState<UniverseAuditResponse | null>(null)
  const [auditModalOpen, setAuditModalOpen] = useState(false)
  const [auditLoading, setAuditLoading] = useState(false)

  // Stock detail modal
  const [detailStock, setDetailStock] = useState<any | null>(null)
  const [detailModalOpen, setDetailModalOpen] = useState(false)

  // U3 subsector filter
  const [subsectorFilter, setSubsectorFilter] = useState<string[]>([])

  // ── Fetch universe data ──────────────────────────────────────────
  const fetchUniverse = useCallback((silent = false) => {
    if (!silent) setLoading(true)
    if (!silent) setError(null)
    apiGet<{ universe: UniverseDetail }>(`/api/universe/${activeTab}`)
      .then(d => {
        setUniverseCache(prev => ({ ...prev, [activeTab]: d.universe }))
        setSubsectorFilter([])
      })
      .catch(e => {
        if (!silent) setError(e.message)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [activeTab])

  useEffect(() => { fetchUniverse() }, [fetchUniverse])

  // ── Prefetch adjacent tabs ─────────────────────────────────────────
  useEffect(() => {
    if (!universe || !activeTab) return
    const tabs = ['U0', 'U1', 'U2', 'U3', 'U4', 'ETF']
    const idx = tabs.indexOf(activeTab)
    const preload = [tabs[idx - 1], tabs[idx + 1]].filter(Boolean)
    preload.forEach((tab) => {
      if (universeCache[tab]) return  // already cached
      apiGet<{ universe: UniverseDetail }>(`/api/universe/${tab}`)
        .then(d => setUniverseCache(prev => ({ ...prev, [tab]: d.universe })))
        .catch(() => {})
    })
  }, [activeTab, universe, universeCache])

  // ── Audit ────────────────────────────────────────────────────────
  const openAudit = useCallback(async () => {
    setAuditLoading(true)
    setAuditModalOpen(true)
    try {
      const data = await apiGet<UniverseAuditResponse>(`/api/universe/${activeTab}/audit`)
      setAuditData(data)
    } catch {
      setAuditData(null)
    } finally {
      setAuditLoading(false)
    }
  }, [activeTab])

  // ── Derived ──────────────────────────────────────────────────────
  const stocks: any[] = useMemo(() => universe?.stocks ?? [], [universe])
  const filteredStocks = useMemo(() => {
    if (activeTab !== 'U3' || subsectorFilter.length === 0) return stocks
    return stocks.filter((s: any) => {
      const subs = s.semiconductor_subsector ?? []
      return subsectorFilter.some(f => subs.includes(f))
    })
  }, [stocks, activeTab, subsectorFilter])

  // Unique subsectors for U3 filter
  const allSubsectors = useMemo(() => {
    if (activeTab !== 'U3') return []
    const set = new Set<string>()
    for (const s of stocks) {
      const subs: string[] = s.semiconductor_subsector ?? []
      subs.forEach((sub: string) => set.add(sub))
    }
    return Array.from(set).sort()
  }, [stocks, activeTab])

  // ── Table columns per universe ──────────────────────────────────
  const getColumns = () => {
    switch (activeTab) {
      case 'U0':
        return [
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120, render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code> },
          { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
          { title: '板块', dataIndex: 'board', key: 'board', width: 80, render: (v: string) => <Tag color="geekblue">{v || '-'}</Tag> },
          { title: '行业', dataIndex: 'industry', key: 'industry', width: 140, ellipsis: true, render: (v: string) => v || '-' },
          { title: '上市日期', dataIndex: 'list_date', key: 'list_date', width: 100, render: (v: string) => v || '-' },
        ]
      case 'U1':
        return [
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120, render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code> },
          { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
          {
            title: '可交易', dataIndex: 'tradable_by_user', key: 'tradable', width: 80,
            render: (v: boolean | undefined | null) => {
              if (v === true) return <Tag icon={<CheckCircleOutlined />} color="success">可交易</Tag>
              if (v === false) return <Tag icon={<CloseCircleOutlined />} color="error">受限</Tag>
              return <Tag color="default">未知</Tag>
            },
          },
          {
            title: 'ST', dataIndex: 'is_st', key: 'st', width: 60,
            render: (v: boolean) => v ? <Tag color="error">ST</Tag> : '-',
          },
          {
            title: '停牌', dataIndex: 'is_suspended', key: 'sus', width: 60,
            render: (v: boolean) => v ? <Tag color="warning">停牌</Tag> : '-',
          },
          {
            title: '涨停', dataIndex: 'is_limit_up', key: 'limit', width: 60,
            render: (v: boolean) => v ? <Tag color="warning">涨停</Tag> : '-',
          },
          {
            title: '日均成交额(20d)', dataIndex: 'avg_amount_20d', key: 'amount', width: 140,
            render: (v: number) => v ? formatMV(v) : '-',
          },
          { title: '限制原因', dataIndex: 'trade_block_reason', key: 'reason', width: 200, ellipsis: true, render: (v: string | null) => v || '-' },
        ]
      case 'U2':
        return [
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120, render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code> },
          { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
          {
            title: '置信度', dataIndex: 'source_confidence', key: 'conf', width: 80,
            render: (v: string) => {
              const colorMap: Record<string, string> = { high: 'success', medium: 'warning', low: 'default' }
              return <Tag color={colorMap[v] || 'default'}>{v}</Tag>
            },
          },
          {
            title: '产业链层', dataIndex: 'ai_chain_layer', key: 'layer', width: 80,
            render: (v: string) => v ? <Tag color="purple">{v}</Tag> : '-',
          },
          {
            title: '主题标签', dataIndex: 'theme_tags', key: 'tags', width: 200,
            render: (tags: string[]) => (tags?.length
              ? tags.map(t => <Tag key={t} style={{ marginBottom: 2 }}>{t}</Tag>)
              : '-'),
          },
          {
            title: '广义AI/半导体', dataIndex: 'is_broad_ai_semiconductor', key: 'broad', width: 120,
            render: (v: boolean) => v
              ? <Tag icon={<CheckCircleOutlined />} color="blue">是</Tag>
              : <Tag>否</Tag>,
          },
          {
            title: 'Atlas来源', dataIndex: 'source_atlas', key: 'atlas', width: 90,
            render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#059669' }} /> : <MinusCircleOutlined style={{ color: '#94A3B8' }} />,
          },
        ]
      case 'U3':
        return [
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120, render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code> },
          { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
          { title: '行业', dataIndex: 'industry', key: 'industry', width: 120, ellipsis: true, render: (v: string) => v || '-' },
          {
            title: '细分方向', dataIndex: 'semiconductor_subsector', key: 'subsector', width: 220,
            render: (subs: string[]) => subs?.length
              ? subs.map(s => <Tag key={s} color="cyan" style={{ marginBottom: 2 }}>{s}</Tag>)
              : '-',
          },
          {
            title: '核心度', dataIndex: 'core_score', key: 'core', width: 80, sorter: (a: any, b: any) => (a.core_score ?? 0) - (b.core_score ?? 0),
            render: (v: number) => {
              const color = v >= 0.7 ? '#059669' : v >= 0.4 ? '#D97706' : '#DC2626'
              return <span style={{ color, fontWeight: 600 }}>{v?.toFixed(2) ?? '-'}</span>
            },
          },
          {
            title: '国产替代', dataIndex: 'domestic_substitution_score', key: 'domestic', width: 80,
            render: (v: number) => {
              const color = v >= 0.6 ? '#059669' : v >= 0.3 ? '#D97706' : '#94A3B8'
              return <span style={{ color, fontWeight: 600 }}>{v?.toFixed(2) ?? '-'}</span>
            },
          },
          {
            title: '供应链位置', dataIndex: 'supply_chain_position', key: 'position', width: 120,
            render: (v: string[]) => v?.length ? v.map(p => <Tag key={p}>{p}</Tag>) : '-',
          },
        ]
      case 'U4':
        return [
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120, render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code> },
          { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
          {
            title: '匹配', key: 'matched', width: 72,
            render: (_: any, record: any) => {
              if (record.matched === true) return <Tag icon={<CheckCircleOutlined />} color="success">是</Tag>
              return <Tag icon={<CloseCircleOutlined />} color="default">否</Tag>
            },
          },
          {
            title: '质量', dataIndex: 'match_quality', key: 'quality', width: 80,
            render: (v: string) => {
              if (v === 'normal') return <Tag color="success">正常</Tag>
              if (v === 'degraded') return <Tag color="warning">降级</Tag>
              return <Tag color="default">{v}</Tag>
            },
          },
          {
            title: '匹配数', dataIndex: 'match_count', key: 'count', width: 72,
            render: (v: number) => <Tag color={v > 0 ? 'success' : 'default'}>{v}</Tag>,
          },
          {
            title: '缺失特征', dataIndex: 'missing_features', key: 'missing', width: 160,
            render: (v: string[]) => v?.length ? v.join(', ') : '-',
          },
          {
            title: '跳过原因', dataIndex: 'skip_reason', key: 'reason', width: 200,
            ellipsis: true,
            render: (v: string) => v ? <Typography.Text type="warning" style={{ fontSize: 12 }}>{v}</Typography.Text> : '-',
          },
          {
            title: '对照标的', key: 'matches', width: 300,
            render: (_: any, record: any) => record.matched_stocks?.length
              ? record.matched_stocks.map((m: any) => (
                <Tooltip key={m.ts_code} title={`${m.industry || '-'} | ${formatMV(m.float_mv)} | ${(m as any).volatility_60d ? `波动${(m as any).volatility_60d}` : ''}`}>
                  <Tag style={{ marginBottom: 2, cursor: 'pointer' }}>{m.name} ({m.ts_code})</Tag>
                </Tooltip>
              ))
              : '-',
          },
        ]
      case 'ETF':
        return [
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120, render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code> },
          { title: '名称', dataIndex: 'name', key: 'name', width: 200, ellipsis: true },
          {
            title: '管理费率', dataIndex: 'management_fee_pct', key: 'fee', width: 90,
            render: (v: number) => v ? `${v}%` : '-',
          },
          { title: '跟踪指数', dataIndex: 'track_index', key: 'index', width: 240, ellipsis: true },
        ]
      default:
        return []
    }
  }

  // ── Render audit detail ─────────────────────────────────────────
  const renderAuditDetail = () => {
    if (!auditData) return null
    const d = auditData.detail
    const items: { label: string; value: React.ReactNode }[] = [
      { label: '股票池', value: auditData.name },
      { label: '成分股数量', value: auditData.total_stocks },
      { label: '审计时间', value: auditData.audited_at?.slice(0, 19) ?? '-' },
    ]

    // Universe-specific audit data
    switch (activeTab) {
      case 'U0': {
        const boards: Record<string, number> = (d as any).board_distribution ?? {}
        const industries: Record<string, number> = (d as any).top_industries ?? {}
        items.push(
          { label: '板块分布', value: <Space wrap>{Object.entries(boards).map(([k, v]) => <Tag key={k}>{k}: {v}</Tag>)}</Space> },
          { label: '前10行业', value: <Space wrap>{Object.entries(industries).slice(0, 5).map(([k, v]) => <Tag key={k}>{k}: {v}</Tag>)}</Space> },
        )
        break
      }
      case 'U1': {
        items.push(
          { label: '可交易数', value: `${(d as any).tradable_count ?? 0} (${(d as any).tradable_pct ?? 0}%)` },
          { label: 'ST 数量', value: (d as any).st_count ?? 0 },
          { label: '停牌数量', value: (d as any).suspended_count ?? 0 },
          { label: '涨停数量', value: (d as any).limit_up_count ?? 0 },
        )
        break
      }
      case 'U2': {
        items.push(
          { label: 'Atlas 来源', value: (d as any).atlas_sourced ?? 0 },
          { label: '高置信度', value: (d as any).high_confidence ?? 0 },
          { label: '广义AI/半导体', value: (d as any).broad_ai_semiconductor_count ?? 0 },
        )
        break
      }
      case 'U3': {
        const subs: Record<string, number> = (d as any).subsector_distribution ?? {}
        items.push(
          { label: '平均核心度', value: (d as any).avg_core_score ?? '-' },
          { label: '细分方向分布', value: <Space wrap>{Object.entries(subs).map(([k, v]) => <Tag key={k} color="cyan">{k}: {v}</Tag>)}</Space> },
        )
        break
      }
      case 'U4': {
        items.push(
          { label: '匹配总数', value: (d as any).matched_total ?? 0 },
          { label: '平均匹配数', value: (d as any).avg_matches_per_stock ?? 0 },
          { label: '匹配失败数', value: (d as any).match_fail_count ?? 0 },
        )
        break
      }
      case 'ETF': {
        items.push({ label: 'ETF 数量', value: (d as any).etf_count ?? 0 })
        break
      }
    }

    return (
      <Descriptions column={2} size="small" bordered style={{ marginTop: 16 }}>
        {items.map((item, i) => (
          <Descriptions.Item key={i} label={item.label} span={item.label === '板块分布' || item.label === '前10行业' || item.label === '细分方向分布' ? 2 : 1}>
            {item.value}
          </Descriptions.Item>
        ))}
      </Descriptions>
    )
  }

  // ── Loading ─────────────────────────────────────────────────────
  if (loading && !universe) {
    return (
      <div>
        <PageHeader title="股票池中心" />
        <Spin size="large" style={{ display: 'block', marginTop: 80, textAlign: 'center' }} />
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────────────────
  if (error && !universe) {
    return (
      <div>
        <PageHeader title="股票池中心" />
        <Alert
          type="error"
          message="加载失败"
          description={error}
          showIcon
          closable
          action={<Button size="small" onClick={() => fetchUniverse()}>重试</Button>}
        />
      </div>
    )
  }

  // ── Normal render ────────────────────────────────────────────────
  return (
    <div>
      {/* Subtle loading bar when switching tabs */}
      {loading && universe && (
        <div style={{ height: 3, background: '#E2E8F0', borderRadius: 2, marginBottom: 8, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: '30%', background: '#2563EB', borderRadius: 2, animation: 'pulse 1.5s ease-in-out infinite' }} />
        </div>
      )}

      <PageHeader
        title="股票池中心"
        dataSource={universe?.built_at ? `更新: ${universe.built_at.slice(0, 19)}` : undefined}
      />

      {/* Summary cards */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <MetricCard title="成分股" value={universe?.total_stocks ?? 0} color="primary" />
        </Col>
        <Col span={6}>
          <MetricCard title="数据来源" value={universe?.data_sources?.length ?? 0} color="info" suffix="个" />
        </Col>
        <Col span={6}>
          <MetricCard title="当前池" value={activeTab} color="success" />
        </Col>
        <Col span={6}>
          <Button
            icon={<AuditOutlined />}
            onClick={openAudit}
            style={{ width: '100%', height: 80, fontSize: 16, borderRadius: 10 }}
          >
            审计
          </Button>
        </Col>
      </Row>

      {/* Universe tabs */}
      <Card style={{ borderRadius: 10, border: '1px solid #E2E8F0' }}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key)}
          items={UNIVERSE_TABS.map(tab => ({
            key: tab.key,
            label: tab.label,
          }))}
          style={{ marginBottom: 0 }}
        />

        {/* U3 subsector filter */}
        {activeTab === 'U3' && allSubsectors.length > 0 && (
          <div style={{ padding: '8px 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>细分方向筛选:</Typography.Text>
            <Select
              mode="multiple"
              placeholder="选择细分方向"
              value={subsectorFilter}
              onChange={setSubsectorFilter}
              style={{ minWidth: 320 }}
              options={allSubsectors.map(s => ({ label: s, value: s }))}
              allowClear
              size="small"
            />
            {subsectorFilter.length > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                已选 {subsectorFilter.length} 个方向 · 显示 {filteredStocks.length} / {stocks.length} 只
              </Typography.Text>
            )}
          </div>
        )}

        {/* Table */}
        <Table
          dataSource={filteredStocks}
          columns={getColumns()}
          rowKey={(record: any) => record.ts_code || record.u3_ts_code || record.name}
          scroll={{ x: 'max-content' }}
          size="small"
          pagination={{
            pageSize: 50,
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100', '200'],
            showTotal: (total, range) => `${range[0]}-${range[1]} / 共 ${total} 只`,
          }}
          onRow={(record) => ({
            onClick: () => { setDetailStock(record); setDetailModalOpen(true) },
            style: { cursor: 'pointer' },
          })}
        />
      </Card>

      {/* Audit Modal */}
      <Modal
        title={`审计 · ${auditData?.name || activeTab}`}
        open={auditModalOpen}
        onCancel={() => { setAuditModalOpen(false); setAuditData(null) }}
        footer={null}
        width={700}
        destroyOnClose
      >
        {auditLoading ? (
          <Spin style={{ display: 'block', margin: '40px auto', textAlign: 'center' }} />
        ) : auditData ? (
          renderAuditDetail()
        ) : (
          <Alert type="warning" message="审计数据加载失败" />
        )}
      </Modal>

      {/* ─── Stock Detail Modal ─── */}
      <Modal
        title={`${detailStock?.name || detailStock?.ts_code || '个股详情'} (${activeTab})`}
        open={detailModalOpen}
        onCancel={() => setDetailModalOpen(false)}
        footer={null}
        width={640}
        destroyOnClose
      >
        {detailStock && (
          <Descriptions column={2} size="small" bordered
            styles={{
              label: { background: '#F8FAFC', color: '#64748B' },
              content: { color: '#0F172A' },
            }}
          >
            {/* Common fields */}
            <Descriptions.Item label="代码" span={1}>
              <code style={{ color: '#2563EB' }}>{detailStock.ts_code || '-'}</code>
            </Descriptions.Item>
            <Descriptions.Item label="名称" span={1}>{detailStock.name || '-'}</Descriptions.Item>

            {/* Tab-specific fields */}
            {activeTab === 'U0' && (
              <>
                <Descriptions.Item label="板块">{detailStock.board || '-'}</Descriptions.Item>
                <Descriptions.Item label="行业">{detailStock.industry || '-'}</Descriptions.Item>
                <Descriptions.Item label="上市日期">{detailStock.list_date || '-'}</Descriptions.Item>
                <Descriptions.Item label="总市值">{detailStock.total_mv ? formatMV(detailStock.total_mv) : '-'}</Descriptions.Item>
                <Descriptions.Item label="流通市值">{detailStock.float_mv ? formatMV(detailStock.float_mv) : '-'}</Descriptions.Item>
              </>
            )}
            {activeTab === 'U1' && (
              <>
                <Descriptions.Item label="可交易">
                  {detailStock.tradable_by_user === true ? <Tag color="success">可交易</Tag>
                    : detailStock.tradable_by_user === false ? <Tag color="error">受限</Tag> : <Tag>未知</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="限制原因">{detailStock.restriction_reason || '-'}</Descriptions.Item>
                <Descriptions.Item label="板块">{detailStock.board || '-'}</Descriptions.Item>
                <Descriptions.Item label="行业">{detailStock.industry || '-'}</Descriptions.Item>
                <Descriptions.Item label="ST">{detailStock.is_st ? <Tag color="error">ST</Tag> : '-'}</Descriptions.Item>
                <Descriptions.Item label="停牌">{detailStock.is_suspended ? <Tag color="warning">停牌</Tag> : '-'}</Descriptions.Item>
                <Descriptions.Item label="流通市值">{detailStock.float_mv ? formatMV(detailStock.float_mv) : '-'}</Descriptions.Item>
                <Descriptions.Item label="日均成交额(20d)">{detailStock.avg_amount_20d ? formatMV(detailStock.avg_amount_20d) : '-'}</Descriptions.Item>
                <Descriptions.Item label="PE">{detailStock.pe?.toFixed(2) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="PB">{detailStock.pb?.toFixed(2) ?? '-'}</Descriptions.Item>
              </>
            )}
            {activeTab === 'U2' && (
              <>
                <Descriptions.Item label="置信度">
                  <Tag color={detailStock.source_confidence === 'high' ? 'success' : detailStock.source_confidence === 'medium' ? 'warning' : 'default'}>
                    {detailStock.source_confidence || '-'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="产业链层">{detailStock.ai_chain_layer ? <Tag color="purple">{detailStock.ai_chain_layer}</Tag> : '-'}</Descriptions.Item>
                <Descriptions.Item label="主题标签" span={2}>
                  {detailStock.theme_tags?.length
                    ? detailStock.theme_tags.map((t: string) => <Tag key={t} style={{ marginBottom: 2 }}>{t}</Tag>)
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="广义AI/半导体">
                  {detailStock.is_broad_ai_semiconductor ? <Tag color="blue">是</Tag> : '否'}
                </Descriptions.Item>
                <Descriptions.Item label="Atlas来源">
                  {detailStock.source_atlas ? <CheckCircleOutlined style={{ color: '#059669' }} /> : <MinusCircleOutlined style={{ color: '#94A3B8' }} />}
                </Descriptions.Item>
              </>
            )}
            {activeTab === 'U3' && (
              <>
                <Descriptions.Item label="行业">{detailStock.industry || '-'}</Descriptions.Item>
                <Descriptions.Item label="核心度">{detailStock.core_score?.toFixed(2) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="国产替代">{detailStock.domestic_substitution_score?.toFixed(2) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="细分方向" span={2}>
                  {detailStock.semiconductor_subsector?.length
                    ? detailStock.semiconductor_subsector.map((s: string) => <Tag key={s} color="cyan">{s}</Tag>)
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="供应链位置" span={2}>
                  {detailStock.supply_chain_position?.length
                    ? detailStock.supply_chain_position.map((p: string) => <Tag key={p}>{p}</Tag>)
                    : '-'}
                </Descriptions.Item>
              </>
            )}
            {activeTab === 'U4' && (
              <>
                <Descriptions.Item label="匹配">{detailStock.matched ? <Tag color="success">是</Tag> : <Tag>否</Tag>}</Descriptions.Item>
                <Descriptions.Item label="质量">
                  {detailStock.match_quality === 'normal' ? <Tag color="success">正常</Tag>
                    : detailStock.match_quality === 'degraded' ? <Tag color="warning">降级</Tag>
                    : <Tag>{detailStock.match_quality || '-'}</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="匹配数">{detailStock.match_count ?? 0}</Descriptions.Item>
                <Descriptions.Item label="市值来源">{detailStock.mv_source || '-'}</Descriptions.Item>
                <Descriptions.Item label="缺失特征">{detailStock.missing_features?.length ? detailStock.missing_features.join(', ') : '-'}</Descriptions.Item>
                <Descriptions.Item label="跳过原因">{detailStock.skip_reason || '-'}</Descriptions.Item>
                <Descriptions.Item label="对照标的" span={2}>
                  {detailStock.matched_stocks?.length
                    ? detailStock.matched_stocks.map((m: any) => (
                        <Tag key={m.ts_code} style={{ marginBottom: 2 }}>
                          {m.name} ({m.ts_code})
                        </Tag>
                      ))
                    : '-'}
                </Descriptions.Item>
              </>
            )}
            {activeTab === 'ETF' && (
              <>
                <Descriptions.Item label="管理费率">{detailStock.management_fee_pct ? `${detailStock.management_fee_pct}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="跟踪指数" span={2}>{detailStock.track_index || '-'}</Descriptions.Item>
              </>
            )}
          </Descriptions>
        )}
        <div style={{ marginTop: 16, padding: '8px 12px', background: '#F1F5F9', borderRadius: 8, fontSize: 11, color: '#64748B' }}>
          💡 当前为基础信息弹窗。完整的个股看板（历史行情/财务/资金流）已列入后续迭代计划。
        </div>
      </Modal>
    </div>
  )
}
