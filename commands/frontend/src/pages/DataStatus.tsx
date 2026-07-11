/** V5.4 数据中心 — DataStatus 重构
 *
 * 数据源能力展示 / 数据覆盖 / 数据新鲜度 / 数据 Manifest
 * 验收标准: 1. Tushare 接口能力 2. 本地数据覆盖 3. 缺失醒目展示 4. 无 mock
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Table, Tag, Button, Progress,
  Alert, Modal, Descriptions, Space,
} from 'antd'
import {
  ReloadOutlined, DatabaseOutlined, CheckCircleOutlined,
  MinusCircleOutlined, ExclamationCircleOutlined,
  FileTextOutlined, HistoryOutlined, EyeOutlined,
} from '@ant-design/icons'
import { API } from '../App'
import PageHeader from '../components/common/PageHeader'
import LoadingState from '../components/common/LoadingState'
import EmptyState from '../components/common/EmptyState'
import MetricCard from '../components/common/MetricCard'
import type {
  DataSourceItem,
  CoverageItem,
  FreshnessFile,
  ManifestItem,
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
// 数据源/类型 映射
// ═════════════════════════════════════════════════════════════════
const PROVIDER_LABEL: Record<string, string> = {
  baostock: 'Baostock',
  eastmoney: '东方财富',
  manual: '人工',
  tushare: 'Tushare Pro',
}

const TYPE_LABEL: Record<string, string> = {
  kline: 'K线',
  fund_flow: '资金流向',
  factor: '因子',
  northbound: '北向资金',
  margin: '两融',
  event: '事件驱动',
  sentiment: '新闻情绪',
  test: '测试',
  market_data: '行情+基本面',
}

const TYPE_COLORS: Record<string, string> = {
  kline: 'blue',
  fund_flow: 'cyan',
  factor: 'purple',
  northbound: 'green',
  margin: 'orange',
  event: 'volcano',
  sentiment: 'magenta',
  test: 'default',
  market_data: 'geekblue',
}

// ═════════════════════════════════════════════════════════════════
// 新鲜度状态配置 (绿/黄/红)
// ═════════════════════════════════════════════════════════════════
const FRESH_STATUS: Record<string, { color: string; bg: string; label: string; dot: string }> = {
  ok:      { color: '#059669', bg: '#D1FAE5', label: '正常', dot: '#059669' },
  warning: { color: '#D97706', bg: '#FEF3C7', label: '警告', dot: '#D97706' },
  stale:   { color: '#D97706', bg: '#FEF3C7', label: '过期', dot: '#D97706' },
  missing: { color: '#DC2626', bg: '#FEE2E2', label: '缺失', dot: '#DC2626' },
}

// ═════════════════════════════════════════════════════════════════
// 通用 fetch helper
// ═════════════════════════════════════════════════════════════════
async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(`${API}${url}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  // 统一响应格式 {ok, data, error, meta}
  if (json && typeof json === 'object' && 'ok' in json) {
    if (!json.ok) throw new Error(json.error?.message || `API 错误 (${url})`)
    return json.data as T
  }
  return json as T
}

// ═════════════════════════════════════════════════════════════════
// 子组件: 缺失率进度条
// ═════════════════════════════════════════════════════════════════
const MissingRateBar: React.FC<{ rate: number }> = ({ rate }) => {
  const color = rate === 0 ? '#059669' : rate < 10 ? '#D97706' : '#DC2626'
  return (
    <Space size={4}>
      <Progress
        percent={100 - rate}
        format={() => `${rate.toFixed(1)}%`}
        size="small"
        strokeColor={color}
        style={{ width: 100, marginBottom: 0 }}
      />
      <Tag color={rate === 0 ? 'success' : rate < 10 ? 'warning' : 'error'} style={{ margin: 0 }}>
        {rate === 0 ? '完整' : rate < 10 ? '轻微缺失' : '严重缺失'}
      </Tag>
    </Space>
  )
}

// ═════════════════════════════════════════════════════════════════
// 子组件: 新鲜度标签
// ═════════════════════════════════════════════════════════════════
const FreshnessTag: React.FC<{ status: string }> = ({ status }) => {
  const cfg = FRESH_STATUS[status] || { color: '#94A3B8', bg: '#F1F5F9', label: status, dot: '#94A3B8' }
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 12,
        color: cfg.color,
        backgroundColor: cfg.bg,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: cfg.dot }} />
      {cfg.label}
    </span>
  )
}

// ═════════════════════════════════════════════════════════════════
// Main Component
// ═════════════════════════════════════════════════════════════════
export default function DataStatus() {
  // ─── 独立状态管理 ──────────────────────────────────────────────
  const [sources, setSources] = useState<DataSourceItem[]>([])
  const [coverage, setCoverage] = useState<CoverageItem[]>([])
  const [coverageMeta, setCoverageMeta] = useState<{ total_stocks: number; total_rows: number } | null>(null)
  const [freshness, setFreshness] = useState<FreshnessFile[]>([])
  const [freshnessOverall, setFreshnessOverall] = useState<string>('')
  const [manifests, setManifests] = useState<ManifestItem[]>([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [manifestDetail, setManifestDetail] = useState<ManifestItem | null>(null)

  // ─── 数据加载 ──────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [srcRes, covRes, frhRes, mfsRes] = await Promise.allSettled([
        fetchJson<{ sources: DataSourceItem[] }>('/api/data/sources'),
        fetchJson<{ coverage: CoverageItem[]; total_stocks: number; total_rows: number }>('/api/data/coverage'),
        fetchJson<{ files: FreshnessFile[]; overall_status: string; check_time?: string }>('/api/data/freshness'),
        fetchJson<{ manifests: ManifestItem[] }>('/api/data/manifests'),
      ])

      if (srcRes.status === 'fulfilled') {
        // API 返回数组直接（非 {sources: [...]} 格式）
        const data = srcRes.value
        setSources(Array.isArray(data) ? data : (data as any)?.sources || [])
      } else {
        console.warn('GET /api/data/sources failed:', srcRes.reason)
        setSources([])
      }

      if (covRes.status === 'fulfilled') {
        setCoverage(covRes.value.coverage || [])
        setCoverageMeta({
          total_stocks: covRes.value.total_stocks ?? 0,
          total_rows: covRes.value.total_rows ?? 0,
        })
      } else {
        console.warn('GET /api/data/coverage failed:', covRes.reason)
        setCoverage([])
        setCoverageMeta(null)
      }

      if (frhRes.status === 'fulfilled') {
        setFreshness(frhRes.value.files || [])
        setFreshnessOverall(frhRes.value.overall_status || 'unknown')
      } else {
        console.warn('GET /api/data/freshness failed:', frhRes.reason)
        setFreshness([])
        setFreshnessOverall('error')
      }

      if (mfsRes.status === 'fulfilled') {
        setManifests(mfsRes.value.manifests || [])
      } else {
        console.warn('GET /api/data/manifests failed:', mfsRes.reason)
        setManifests([])
      }

      // 如果所有请求都失败，显示错误
      if (
        srcRes.status === 'rejected' &&
        covRes.status === 'rejected' &&
        frhRes.status === 'rejected' &&
        mfsRes.status === 'rejected'
      ) {
        throw new Error('所有数据接口均无法访问，请检查后端服务')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // ─── 加载状态 ──────────────────────────────────────────────────
  if (loading && sources.length === 0 && freshness.length === 0) {
    return <LoadingState tip="加载数据中心数据..." size="large" />
  }

  // ═══════════════════════════════════════════════════════════════
  // Column 定义
  // ═══════════════════════════════════════════════════════════════

  // ── 数据源能力列 ─────────────────────────────────────────────
  const sourceCols = [
    {
      title: '接口名', dataIndex: 'source_id', key: 'source_id', width: 140,
      render: (v: string) => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code>,
    },
    {
      title: '数据源', key: 'provider', width: 100,
      render: (_: unknown, record: DataSourceItem) => (
        <span style={{ color: '#0F172A', fontSize: 13 }}>
          {PROVIDER_LABEL[record.provider] || record.provider || '-'}
        </span>
      ),
    },
    {
      title: '数据类型', key: 'data_type', width: 90,
      render: (_: unknown, record: DataSourceItem) => (
        <Tag color={TYPE_COLORS[record.type] || 'default'}>
          {TYPE_LABEL[record.type] || record.type || '-'}
        </Tag>
      ),
    },
    {
      title: '可用', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => {
        if (v === 'active' || v === 'ok') {
          return <Tag icon={<CheckCircleOutlined />} color="success">可用</Tag>
        }
        if (v === 'degraded') {
          return <Tag icon={<ExclamationCircleOutlined />} color="warning">降级</Tag>
        }
        // pending / inactive / unchecked
        return <Tag icon={<MinusCircleOutlined />} color="default">待初始化</Tag>
      },
    },
    {
      title: '最早日期', dataIndex: 'last_refresh', key: 'earliest', width: 120,
      render: (_: unknown, record: DataSourceItem) => {
        const cap = record.capabilities?.[Object.keys(record.capabilities || {})[0]]
        return <span style={{ color: '#64748B', fontSize: 12 }}>{cap?.earliest_date || '-'}</span>
      },
    },
    {
      title: '最新日期', dataIndex: 'last_refresh', key: 'latest', width: 120,
      render: (v: string) => (
        <span style={{ color: '#64748B', fontSize: 12 }}>
          {v ? v.slice(0, 10) : '-'}
        </span>
      ),
    },
    {
      title: '覆盖股票数', dataIndex: 'record_count', key: 'stock_count', width: 100,
      render: (v: number) => (
        <span style={{ color: '#0F172A', fontFamily: 'monospace', fontSize: 13 }}>
          {v?.toLocaleString() ?? '-'}
        </span>
      ),
    },
  ]

  // ── 数据覆盖列 ───────────────────────────────────────────────
  const coverageCols = [
    {
      title: '数据集', dataIndex: 'dataset', key: 'dataset', width: 120,
      render: (v?: string) => v || '—',
    },
    {
      title: '股票数', dataIndex: 'stock_count', key: 'stock_count', width: 90,
      render: (v: number) => <span style={{ fontFamily: 'monospace' }}>{v?.toLocaleString() ?? '-'}</span>,
    },
    {
      title: '交易日范围', key: 'trade_days', width: 200,
      render: (_: unknown, r: CoverageItem) => (
        <span style={{ color: '#64748B', fontSize: 12 }}>
          {Array.isArray(r.trade_days) ? `${r.trade_days[0]} ~ ${r.trade_days[1]}` : '-'}
        </span>
      ),
    },
    {
      title: '行数', dataIndex: 'row_count', key: 'row_count', width: 90,
      render: (v: number) => <span style={{ fontFamily: 'monospace' }}>{v?.toLocaleString() ?? '-'}</span>,
    },
    {
      title: '最新日期', dataIndex: 'latest_date', key: 'latest_date', width: 110,
      render: (v: string) => <span style={{ color: '#64748B', fontSize: 12 }}>{v?.slice(0, 10) || '-'}</span>,
    },
    {
      title: '缺失率', dataIndex: 'missing_rate', key: 'missing_rate', width: 200,
      render: (v: number) => <MissingRateBar rate={v ?? 0} />,
    },
  ]

  // ── 新鲜度列 ─────────────────────────────────────────────────
  const freshCols = [
    {
      title: '股票代码', key: 'code', width: 110,
      render: (_: unknown, r: FreshnessFile) => (
        <code style={{ color: '#0F172A', fontSize: 12 }}>
          {r.stock_code || r.code || r.path?.split('/')?.pop() || '-'}
        </code>
      ),
    },
    {
      title: '最新日期', dataIndex: 'latest_date', key: 'latest_date', width: 110,
      render: (v?: string) => (
        <span style={{ color: '#64748B', fontSize: 12 }}>{v?.slice(0, 10) || '-'}</span>
      ),
    },
    {
      title: '滞后天数', dataIndex: 'lag_days', key: 'lag_days', width: 90,
      render: (v?: number) => {
        if (v === undefined || v === null) return <span style={{ color: '#94A3B8' }}>-</span>
        const color = v <= 1 ? '#059669' : v <= 3 ? '#D97706' : '#DC2626'
        return <span style={{ color, fontWeight: 600, fontFamily: 'monospace' }}>{v}d</span>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => <FreshnessTag status={v} />,
    },
  ]

  // ── Manifest 列 ──────────────────────────────────────────────
  const manifestCols = [
    {
      title: 'Manifest ID', dataIndex: 'manifest_id', key: 'manifest_id', width: 180,
      render: (v: string) => <code style={{ color: '#2563EB', fontSize: 11 }}>{v}</code>,
    },
    {
      title: '数据源', dataIndex: 'source_id', key: 'source_id', width: 110,
      render: (v: string) => <Tag color="geekblue">{v}</Tag>,
    },
    {
      title: '行数', dataIndex: 'record_count', key: 'record_count', width: 80,
      render: (v: number) => <span style={{ fontFamily: 'monospace' }}>{v?.toLocaleString() ?? '-'}</span>,
    },
    {
      title: '文件大小', dataIndex: 'file_size', key: 'file_size', width: 90,
      render: (v?: number) => {
        if (!v) return <span style={{ color: '#94A3B8' }}>-</span>
        const kb = (v / 1024).toFixed(1)
        return <span style={{ color: '#64748B', fontSize: 12 }}>{kb} KB</span>
      },
    },
    {
      title: '获取时间', dataIndex: 'created_at', key: 'created_at', width: 160,
      render: (v: string) => <span style={{ color: '#64748B', fontSize: 12 }}>{v?.slice(0, 19) || '-'}</span>,
    },
    {
      title: '操作', key: 'action', width: 60,
      render: (_: unknown, record: ManifestItem) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={(e) => { e.stopPropagation(); setManifestDetail(record) }}
        />
      ),
    },
  ]

  // ═══════════════════════════════════════════════════════════════
  // Render
  // ═══════════════════════════════════════════════════════════════
  return (
    <div style={{ maxWidth: 1600, margin: '0 auto' }}>
      {/* ─── Header ───────────────────────────────────────────── */}
      <PageHeader
        title="📡 数据中心"
        updatedAt={freshnessOverall ? `新鲜度: ${freshnessOverall}` : undefined}
        dataSource="Hermes Data API v5.4"
      />

      {/* ─── 全局错误 + 刷新 ──────────────────────────────────── */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <Col>
          {error && (
            <Alert
              message={error}
              type="error"
              showIcon
              closable
              style={{ borderRadius: 8, marginBottom: 12 }}
              action={<Button size="small" onClick={load}>重试</Button>}
            />
          )}
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            刷新
          </Button>
        </Col>
      </Row>

      {/* ═══════════════════════════════════════════════════════ */}
      {/* 第一部分: 数据源能力展示                                    */}
      {/* ═══════════════════════════════════════════════════════ */}
      <Card
        title={
          <span style={{ color: '#0F172A', fontWeight: 600 }}>
            <DatabaseOutlined style={{ marginRight: 8 }} />数据源能力
          </span>
        }
        extra={
          <Space size={12}>
            <span style={{ color: '#059669', fontSize: 12 }}>
              <CheckCircleOutlined /> {sources.filter(s => s.status === 'active' || s.status === 'ok').length} 可用
            </span>
            <span style={{ color: '#D97706', fontSize: 12 }}>
              <ExclamationCircleOutlined /> {sources.filter(s => s.status === 'degraded').length} 降级
            </span>
            <span style={{ color: '#94A3B8', fontSize: 12 }}>
              <MinusCircleOutlined /> {sources.filter(s => !['active', 'ok', 'degraded'].includes(s.status)).length} 待初始化
            </span>
            <span style={{ color: '#94A3B8', fontSize: 12, borderLeft: '1px solid #E2E8F0', paddingLeft: 12 }}>
              已注册 {sources.length} 个数据源
            </span>
          </Space>
        }
        style={CARD}
      >
        {sources.length === 0 ? (
          <EmptyState description="暂无数据源信息" />
        ) : (
          <Table
            dataSource={sources}
            columns={sourceCols}
            rowKey="source_id"
            size="small"
            pagination={{ pageSize: 10 }}
          />
        )}
      </Card>

      {/* ═══════════════════════════════════════════════════════ */}
      {/* 第二部分: 数据覆盖                                        */}
      {/* ═══════════════════════════════════════════════════════ */}
      <Card
        title={
          <span style={{ color: '#0F172A', fontWeight: 600 }}>
            <FileTextOutlined style={{ marginRight: 8 }} />数据覆盖
          </span>
        }
        style={CARD}
      >
        {coverageMeta && (
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <MetricCard
                title="覆盖股票数"
                value={coverageMeta.total_stocks?.toLocaleString() ?? '—'}
                color="primary"
              />
            </Col>
            <Col xs={12} sm={6}>
              <MetricCard
                title="总行数"
                value={coverageMeta.total_rows?.toLocaleString() ?? '—'}
                color="info"
              />
            </Col>
            <Col xs={12} sm={6}>
              <MetricCard
                title="数据集数"
                value={coverage.length}
                color="success"
              />
            </Col>
            <Col xs={12} sm={6}>
              <MetricCard
                title="缺失状态"
                value={coverage.some(c => c.missing_rate > 0) ? '存在缺失' : '完整'}
                color={coverage.some(c => c.missing_rate > 0) ? 'warning' : 'success'}
              />
            </Col>
          </Row>
        )}

        {coverage.length === 0 ? (
          <EmptyState description="暂无覆盖数据" />
        ) : (
          <Table
            dataSource={coverage}
            columns={coverageCols}
            rowKey={(r, i) => r.dataset || `${i}`}
            size="small"
            pagination={false}
          />
        )}
      </Card>

      {/* ═══════════════════════════════════════════════════════ */}
      {/* 第三部分: 数据新鲜度                                      */}
      {/* ═══════════════════════════════════════════════════════ */}
      <Card
        title={
          <span style={{ color: '#0F172A', fontWeight: 600 }}>
            <HistoryOutlined style={{ marginRight: 8 }} />数据新鲜度
          </span>
        }
        extra={
          <Space size={8}>
            <Tag color={freshnessOverall === 'ok' ? 'success' : freshnessOverall === 'warning' ? 'warning' : 'error'}>
              总体: {freshnessOverall === 'ok' ? '正常' : freshnessOverall === 'stale' || freshnessOverall === 'warning' ? '预警' : '异常'}
            </Tag>
            <span style={{ color: '#94A3B8', fontSize: 12 }}>
              滞后天数 ≤1d 🟢 ≤3d 🟡 {'>'}3d 🔴
            </span>
          </Space>
        }
        style={CARD}
      >
        {freshness.length === 0 ? (
          <EmptyState description="暂无新鲜度数据" />
        ) : (
          <Table
            dataSource={freshness}
            columns={freshCols}
            rowKey={(r, i) => r.stock_code || r.code || r.path || `${i}`}
            size="small"
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>

      {/* ═══════════════════════════════════════════════════════ */}
      {/* 第四部分: 数据 Manifest                                    */}
      {/* ═══════════════════════════════════════════════════════ */}
      <Card
        title={
          <span style={{ color: '#0F172A', fontWeight: 600 }}>
            <FileTextOutlined style={{ marginRight: 8 }} />数据 Manifest
          </span>
        }
        extra={
          <span style={{ color: '#94A3B8', fontSize: 12 }}>
            共 {manifests.length} 条记录 · 点击 👁 查看详情
          </span>
        }
        style={CARD}
      >
        {manifests.length === 0 ? (
          <EmptyState description="暂无 Manifest 数据" />
        ) : (
          <Table
            dataSource={manifests}
            columns={manifestCols}
            rowKey="manifest_id"
            size="small"
            pagination={{ pageSize: 15 }}
            onRow={(record) => ({
              onClick: () => setManifestDetail(record),
              style: { cursor: 'pointer' },
            })}
          />
        )}
      </Card>

      {/* ─── Manifest 详情 Modal ──────────────────────────────── */}
      <Modal
        title={`📄 ${manifestDetail?.manifest_id || ''}`}
        open={!!manifestDetail}
        onCancel={() => setManifestDetail(null)}
        footer={null}
        width={640}
      >
        {manifestDetail && (
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="Manifest ID" span={2}>
              <code>{manifestDetail.manifest_id}</code>
            </Descriptions.Item>
            <Descriptions.Item label="数据源">
              <Tag color="geekblue">{manifestDetail.source_id}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="数据集">
              {manifestDetail.dataset || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="行数" span={2}>
              {manifestDetail.record_count?.toLocaleString() ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="文件大小">
              {manifestDetail.file_size
                ? `${(manifestDetail.file_size / 1024).toFixed(1)} KB`
                : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="文件 Hash">
              <code style={{ fontSize: 11 }}>{manifestDetail.file_hash || '—'}</code>
            </Descriptions.Item>
            <Descriptions.Item label="文件路径" span={2}>
              <code style={{ fontSize: 11, wordBreak: 'break-all' }}>
                {manifestDetail.file || '—'}
              </code>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间" span={2}>
              {manifestDetail.created_at?.slice(0, 19) || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="血缘关系" span={2}>
              {manifestDetail.lineage && manifestDetail.lineage.length > 0
                ? manifestDetail.lineage.map(id => (
                    <Tag key={id} color="blue" style={{ marginBottom: 4 }}>
                      {id}
                    </Tag>
                  ))
                : <span style={{ color: '#94A3B8' }}>无</span>}
            </Descriptions.Item>
            <Descriptions.Item label="子节点" span={2}>
              {manifestDetail.children && manifestDetail.children.length > 0
                ? manifestDetail.children.map(id => (
                    <Tag key={id} color="purple" style={{ marginBottom: 4 }}>
                      {id}
                    </Tag>
                  ))
                : <span style={{ color: '#94A3B8' }}>无</span>}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}
