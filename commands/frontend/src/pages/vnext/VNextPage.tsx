import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Collapse,
  DatePicker,
  Descriptions,
  Empty,
  Flex,
  Progress,
  Row,
  Col,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import {
  ClockCircleOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { useQueries } from '@tanstack/react-query'
import type { VNextComponent, VNextRecord } from '../../api/vnext'
import { reportDownloadUrl, vnextApi } from '../../api/vnext'
import { useInvalidateVNext, type VNextResource } from '../../hooks/useVNext'

export type VNextPageKind =
  | 'home'
  | 'regime'
  | 'semi'
  | 'candidates'
  | 'portfolio'
  | 'ml'
  | 'backtests'
  | 'trading'
  | 'approvals'
  | 'execution'
  | 'review'
  | 'data-health'

const PAGE_CONFIG: Record<VNextPageKind, { title: string; subtitle: string; resources: VNextResource[] }> = {
  home: {
    title: 'Hermes 投研交易控制台',
    subtitle: '10 秒确认今天能不能动、动什么、为什么、有什么风险以及是否需要审批',
    resources: ['status', 'dataHealth', 'regime', 'policyPut', 'semiMainline', 'portfolioRisk', 'executionStatus', 'paper', 'shadow', 'approvals'],
  },
  regime: {
    title: 'Regime & Policy Put',
    subtitle: '指数箱体、政策托底代理、广度背离、风格轮动和上沿派发风险',
    resources: ['regime', 'policyPut'],
  },
  semi: {
    title: 'Semiconductor Mainline',
    subtitle: '半导体主线阶段、状态转移、锚点证据、缺失证据和 ETF 替代',
    resources: ['semiMainline', 'candidates'],
  },
  candidates: {
    title: 'Signal / Candidates',
    subtitle: '研究候选、账户可交易、受限板块、ETF substitution、watch-only 与 blocked 分层',
    resources: ['candidates', 'regime', 'semiMainline'],
  },
  portfolio: {
    title: 'Portfolio & Risk',
    subtitle: '组合 Sharpe、回撤、相关性、边际贡献、科技/半导体 beta 与假分散',
    resources: ['portfolioRisk', 'regime'],
  },
  ml: {
    title: 'ML Factor / Ranker Lab',
    subtitle: '因子筛选、模型版本、训练/OOS、特征解释与横截面 score/rank（不输出买卖）',
    resources: ['mlRanker'],
  },
  backtests: {
    title: 'Backtest / Validation',
    subtitle: '政策托底、箱体、广度、轮动、多基准、成本/滑点和多 Regime 稳健性',
    resources: ['backtests'],
  },
  trading: {
    title: 'Paper / Shadow Trading',
    subtitle: '模拟权益、订单、成交、偏差、滑点、未成交原因与 live dry-run readiness',
    resources: ['paper', 'shadow', 'executionStatus'],
  },
  approvals: {
    title: 'Telegram Approval Queue',
    subtitle: '审批只改变审批状态，不会从 UI 直接触发 miniQMT 委托',
    resources: ['approvals', 'executionStatus'],
  },
  execution: {
    title: 'Execution / miniQMT',
    subtitle: '交易模式、只读连接、账户/持仓/通道状态、no_live_trade 与 Kill Switch',
    resources: ['executionStatus'],
  },
  review: {
    title: 'Antifragile Review',
    subtitle: '逐笔归因：策略、Regime、主线、买点、仓位、执行、数据还是正常波动',
    resources: ['antifragileReview'],
  },
  'data-health': {
    title: 'Data Health',
    subtitle: '数据真实性、新鲜度、缺失/部分/回测专用/观察专用状态',
    resources: ['dataHealth'],
  },
}

const SEMI_STATES = [
  'SEMI_DORMANT', 'SEMI_POLICY_WARMUP', 'SEMI_MAINLINE_START', 'SEMI_MAINLINE_CONFIRM',
  'SEMI_ACCELERATION', 'SEMI_HIGH_DIVERGENCE', 'SEMI_ROTATION_INTERNAL', 'SEMI_PULLBACK_HEALTHY',
  'SEMI_POLICY_RESCUE', 'SEMI_DISTRIBUTION', 'SEMI_RETREAT', 'SEMI_FAILURE',
]

const BAD_STATUSES = new Set(['MISSING', 'STALE', 'PARTIAL', 'BLOCKED', 'WATCH_ONLY', 'BACKTEST_ONLY'])

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'MISSING'
  if (typeof value === 'boolean') return value ? 'YES' : 'NO'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : 'MISSING'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function objectOf(value: unknown): VNextRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as VNextRecord) : {}
}

function arrayOf(value: unknown): VNextRecord[] {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') as VNextRecord[] : []
}

function statusColor(status?: unknown) {
  const value = String(status ?? 'MISSING').toUpperCase()
  if (value === 'OK' || value === 'HEALTHY' || value === 'APPROVED') return 'success'
  if (value === 'PARTIAL' || value === 'STALE' || value === 'DELAYED' || value === 'MODIFIED') return 'warning'
  if (value === 'READ_ONLY' || value === 'PAPER' || value === 'SHADOW' || value === 'DRY_RUN') return 'processing'
  return 'error'
}

function StatusTag({ value }: { value: unknown }) {
  const text = valueText(value)
  return <Tag color={statusColor(text)}>{text}</Tag>
}

function Metric({ title, value, danger = false }: { title: string; value: unknown; danger?: boolean }) {
  const missing = value === null || value === undefined || value === ''
  return (
    <Card size="small" className="vnext-metric-card">
      <Typography.Text type="secondary">{title}</Typography.Text>
      <div className={danger || missing ? 'vnext-metric-value danger' : 'vnext-metric-value'}>{valueText(value)}</div>
    </Card>
  )
}

function EvidencePanel({ component }: { component: VNextComponent }) {
  const evidence = Array.isArray(component.evidence) ? component.evidence : []
  const missing = Array.isArray(component.missing_evidence) ? component.missing_evidence : []
  const sources = Array.isArray(component.data_sources) ? component.data_sources : []
  return (
    <Collapse
      size="small"
      items={[
        {
          key: 'evidence',
          label: `证据下钻 · ${evidence.length} evidence / ${missing.length} missing`,
          children: (
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={8}>
                <Typography.Title level={5}>Evidence</Typography.Title>
                {evidence.length ? evidence.map((item) => <div key={item}>• {item}</div>) : <StatusTag value="MISSING" />}
              </Col>
              <Col xs={24} lg={8}>
                <Typography.Title level={5}>Missing evidence</Typography.Title>
                {missing.length ? missing.map((item) => <div key={item} className="vnext-danger-text">• {item}</div>) : <Tag color="success">NONE</Tag>}
              </Col>
              <Col xs={24} lg={8}>
                <Typography.Title level={5}>Data source</Typography.Title>
                {sources.length ? sources.map((item) => <div key={item}>{item}</div>) : <StatusTag value="MISSING" />}
                <div className="vnext-updated">更新时间：{valueText(component.updated_at)}</div>
              </Col>
            </Row>
          ),
        },
      ]}
    />
  )
}

function ComponentFrame({ title, component, children }: { title: string; component?: VNextComponent; children: ReactNode }) {
  if (!component) return <Card title={title}><Alert type="error" showIcon message="MISSING" description="API 未返回组件数据" /></Card>
  const status = String(component.status ?? 'MISSING').toUpperCase()
  return (
    <Card
      title={<Space><span>{title}</span><StatusTag value={status} /></Space>}
      extra={typeof component.confidence === 'number' ? <span>置信度 {Math.round(component.confidence * 100)}%</span> : null}
      className={BAD_STATUSES.has(status) ? 'vnext-card degraded' : 'vnext-card'}
    >
      {BAD_STATUSES.has(status) && (
        <Alert
          type={status === 'STALE' || status === 'PARTIAL' ? 'warning' : 'error'}
          showIcon
          message={`${status}：结论已降级`}
          description={(component.missing_evidence ?? []).join('；') || '没有足够真实数据证明成功态'}
          style={{ marginBottom: 16 }}
        />
      )}
      {children}
      <div style={{ marginTop: 16 }}><EvidencePanel component={component} /></div>
    </Card>
  )
}

function usePageData(kind: VNextPageKind, date: string) {
  const resources = PAGE_CONFIG[kind].resources
  const results = useQueries({
    queries: resources.map((resource) => ({
      queryKey: ['vnext', resource, date],
      queryFn: async () => {
        if (resource === 'approvals') return (await vnextApi.approvals()).data
        if (resource === 'backtests') return (await vnextApi.backtests()).data
        const fn = vnextApi[resource] as (selectedDate?: string) => ReturnType<typeof vnextApi.status>
        return (await fn(date)).data
      },
      staleTime: 30_000,
      refetchInterval: resource === 'status' || resource === 'executionStatus' ? 60_000 : false,
    })),
  })
  const queries = resources.map((resource, index) => ({ resource, query: results[index] }))
  const data = Object.fromEntries(queries.map(({ resource, query }) => [resource, query.data])) as Record<VNextResource, unknown>
  return {
    data,
    isLoading: queries.some(({ query }) => query.isLoading),
    errors: queries.filter(({ query }) => query.error).map(({ resource, query }) => `${resource}: ${query.error instanceof Error ? query.error.message : 'request failed'}`),
    refetch: () => Promise.all(queries.map(({ query }) => query.refetch())),
  }
}

function componentAt(data: Record<VNextResource, unknown>, key: VNextResource): VNextComponent {
  return objectOf(data[key]) as VNextComponent
}

function HomeContent({ data }: { data: Record<VNextResource, unknown> }) {
  const status = componentAt(data, 'status')
  const regime = objectOf(componentAt(data, 'regime').payload)
  const semi = objectOf(componentAt(data, 'semiMainline').payload)
  const policy = objectOf(componentAt(data, 'policyPut').payload)
  const portfolio = objectOf(componentAt(data, 'portfolioRisk').payload)
  const execution = componentAt(data, 'executionStatus')
  const approvals = objectOf(data.approvals)
  const danger = Boolean(status.kill_switch_triggered) || status.data_freshness !== 'OK' || execution.live_enabled === true
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type={danger ? 'error' : 'info'}
        showIcon
        icon={danger ? <StopOutlined /> : <SafetyCertificateOutlined />}
        message={execution.message ? valueText(execution.message) : '当前不会真实下单'}
        description={`交易模式 ${valueText(status.trading_mode)} · Kill Switch ${valueText(status.kill_switch_triggered)} · no_live_trade ${valueText(status.no_live_trade)}`}
      />
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}><Metric title="今日交易模式" value={status.trading_mode} /></Col>
        <Col xs={12} md={6}><Metric title="Kill Switch" value={status.kill_switch_triggered ? 'TRIGGERED' : 'CLEAR'} danger={Boolean(status.kill_switch_triggered)} /></Col>
        <Col xs={12} md={6}><Metric title="数据新鲜度" value={status.data_freshness} danger={status.data_freshness !== 'OK'} /></Col>
        <Col xs={12} md={6}><Metric title="Telegram 待审批" value={approvals.total ?? execution.telegram_pending} /></Col>
        <Col xs={12} md={6}><Metric title="Regime" value={regime.regime_name ?? status.regime} /></Col>
        <Col xs={12} md={6}><Metric title="半导体主线" value={semi.state ?? status.semiconductor_state} /></Col>
        <Col xs={12} md={6}><Metric title="政策托底代理" value={policy.policy_support_proxy_score} /></Col>
        <Col xs={12} md={6}><Metric title="指数箱体位置" value={policy.index_box_position} /></Col>
        <Col xs={12} md={6}><Metric title="组合风险 / 假分散" value={portfolio.false_diversification_warning === true ? 'WARNING' : portfolio.false_diversification_warning === false ? 'CLEAR' : 'MISSING'} danger={portfolio.false_diversification_warning !== false} /></Col>
        <Col xs={12} md={6}><Metric title="允许新开仓" value={regime.allow_new_buy} danger={regime.allow_new_buy !== true} /></Col>
        <Col xs={12} md={6}><Metric title="允许隔夜" value={regime.allow_overnight} danger={regime.allow_overnight !== true} /></Col>
        <Col xs={12} md={6}><Metric title="miniQMT" value={objectOf(execution.miniqmt).connection_status} danger /></Col>
      </Row>
      <ComponentFrame title="当前 Regime" component={componentAt(data, 'regime')}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 4 }} items={Object.entries(regime).slice(0, 12).map(([key, value]) => ({ key, label: key, children: valueText(value) }))} />
      </ComponentFrame>
      <ComponentFrame title="半导体主线状态" component={componentAt(data, 'semiMainline')}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} items={Object.entries(semi).map(([key, value]) => ({ key, label: key, children: valueText(value) }))} />
      </ComponentFrame>
    </Space>
  )
}

function RegimeContent({ data }: { data: Record<VNextResource, unknown> }) {
  const regimeComponent = componentAt(data, 'regime')
  const policyComponent = componentAt(data, 'policyPut')
  const regime = objectOf(regimeComponent.payload)
  const policy = objectOf(policyComponent.payload)
  const box = objectOf(policyComponent.index_box)
  const boxPayload = objectOf(box.payload)
  const fixed = objectOf(boxPayload.fixed_box)
  const dynamic = objectOf(boxPayload.dynamic_box)
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <ComponentFrame title="Regime Router" component={regimeComponent}>
        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}><Metric title="Regime" value={regime.regime_name} /></Col>
          <Col xs={12} md={4}><Metric title="Risk budget" value={regime.recommended_risk_budget} /></Col>
          <Col xs={12} md={4}><Metric title="Semi budget" value={regime.semiconductor_budget} /></Col>
          <Col xs={12} md={4}><Metric title="Defensive" value={regime.defensive_budget} /></Col>
          <Col xs={12} md={4}><Metric title="Cash" value={regime.cash_budget} /></Col>
        </Row>
      </ComponentFrame>
      <ComponentFrame title="Policy Put / Index Box" component={policyComponent}>
        <Row gutter={[12, 12]}>
          <Col xs={12} md={6}><Metric title="policy_support_proxy_score" value={policy.policy_support_proxy_score} /></Col>
          <Col xs={12} md={6}><Metric title="breadth_divergence_score" value={policy.breadth_divergence_score} /></Col>
          <Col xs={12} md={6}><Metric title="style_rotation_score" value={objectOf(policyComponent.style_rotation).payload ? objectOf(objectOf(policyComponent.style_rotation).payload).style_rotation_score : undefined} /></Col>
          <Col xs={12} md={6}><Metric title="upper_box_distribution_risk" value={policy.upper_box_distribution_risk} /></Col>
        </Row>
        <Typography.Title level={5}>用户假设箱体（待回测，不是永久规则）</Typography.Title>
        <Flex wrap="wrap" gap={8}>{['lower_bound', 'policy_put_zone', 'neutral_line', 'upper_warning', 'upper_risk', 'upper_bound'].map((key) => <Tag key={key}>{key}: {valueText(fixed[key])}</Tag>)}</Flex>
        <Typography.Title level={5}>动态箱体</Typography.Title>
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} items={Object.entries(dynamic).map(([key, value]) => ({ key, label: key, children: valueText(value) }))} />
      </ComponentFrame>
    </Space>
  )
}

function SemiContent({ data }: { data: Record<VNextResource, unknown> }) {
  const component = componentAt(data, 'semiMainline')
  const payload = objectOf(component.payload)
  const current = String(payload.state ?? '')
  return (
    <ComponentFrame title="Semiconductor Mainline State Machine" component={component}>
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}><Metric title="当前状态" value={current} /></Col>
        <Col xs={12} md={8}><Metric title="推荐动作偏置" value={payload.recommended_action_bias} /></Col>
        <Col xs={12} md={8}><Metric title="优先工具" value={payload.preferred_instrument} /></Col>
      </Row>
      <Typography.Title level={5}>状态路径</Typography.Title>
      <Flex wrap="wrap" gap={6}>{SEMI_STATES.map((state) => <Tag key={state} color={state === current ? 'blue' : undefined}>{state}</Tag>)}</Flex>
      <Alert style={{ marginTop: 16 }} type="info" showIcon message="不是简单看多/看空" description={valueText(payload.state_transition_reason)} />
    </ComponentFrame>
  )
}

function CandidateContent({ data }: { data: Record<VNextResource, unknown> }) {
  const component = componentAt(data, 'candidates')
  const payload = objectOf(component.payload)
  const rows = arrayOf(payload.raw_candidates).map((item, index) => ({ key: String(item.symbol ?? index), ...item }))
  const columns: ColumnsType<VNextRecord> = [
    { title: '代码', dataIndex: 'symbol', fixed: 'left', width: 110 },
    { title: '名称', dataIndex: 'name', width: 110 },
    { title: '分类', dataIndex: 'category', width: 140, render: (value) => <StatusTag value={value} /> },
    { title: '可交易性', dataIndex: 'tradability', width: 130, render: (value) => <StatusTag value={value} /> },
    { title: '价格', dataIndex: 'latest_price', render: valueText },
    { title: '因子分数', dataIndex: 'factor_score', render: valueText },
    { title: 'ML rank', dataIndex: 'ml_rank_score', render: valueText },
    { title: 'Regime 适配', dataIndex: 'regime_applicability', render: valueText },
    { title: '主线适配', dataIndex: 'mainline_fit', render: valueText },
    { title: 'Marginal Sharpe', dataIndex: 'marginal_sharpe', render: valueText },
    { title: '流动性', dataIndex: 'liquidity_check', render: (value) => <StatusTag value={value} /> },
    { title: '涨跌停', dataIndex: 'price_limit_check', render: (value) => <StatusTag value={value} /> },
    { title: 'ST/停牌', dataIndex: 'st_suspension_check', render: (value) => <StatusTag value={value} /> },
    { title: '建议仓位', dataIndex: 'recommended_weight', render: valueText },
    { title: '风险', dataIndex: 'risk_level', render: (value) => <StatusTag value={value} /> },
    { title: 'Blocked reason', dataIndex: 'blocked_reason', width: 260, render: valueText },
  ]
  return (
    <ComponentFrame title="候选分层" component={component}>
      <Flex wrap="wrap" gap={8} style={{ marginBottom: 12 }}>
        {[
          ['raw', payload.raw_candidates], ['tradable', payload.account_tradable_candidates],
          ['restricted', payload.restricted_board_candidates], ['ETF substitution', payload.etf_substitution_candidates],
          ['watch-only', payload.watch_only_candidates], ['blocked', payload.blocked_candidates],
          ['paper', payload.paper_candidates], ['shadow', payload.shadow_candidates], ['live dry-run', payload.live_dry_run_candidates],
        ].map(([label, items]) => <Tag key={String(label)}>{String(label)}: {Array.isArray(items) ? items.length : 0}</Tag>)}
      </Flex>
      {rows.length ? <Table size="small" scroll={{ x: 1800 }} dataSource={rows} columns={columns} pagination={{ pageSize: 20 }} /> : <Empty description="MISSING：没有真实候选产物" />}
    </ComponentFrame>
  )
}

function PortfolioContent({ data }: { data: Record<VNextResource, unknown> }) {
  const component = componentAt(data, 'portfolioRisk')
  const payload = objectOf(component.payload)
  const weights = objectOf(payload.weights)
  const marginal = objectOf(payload.marginal_sharpe_contribution)
  return (
    <ComponentFrame title="组合风险与假分散" component={component}>
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}><Metric title="Portfolio Sharpe" value={payload.portfolio_sharpe} /></Col>
        <Col xs={12} md={6}><Metric title="最大回撤" value={payload.max_drawdown} /></Col>
        <Col xs={12} md={6}><Metric title="风险集中度" value={payload.risk_concentration_score} /></Col>
        <Col xs={12} md={6}><Metric title="分散化分数" value={payload.diversification_score} /></Col>
        <Col xs={12} md={6}><Metric title="科技 beta" value={payload.technology_beta_exposure} /></Col>
        <Col xs={12} md={6}><Metric title="半导体 beta" value={payload.semiconductor_beta_exposure} /></Col>
        <Col xs={12} md={6}><Metric title="有效资产数" value={payload.effective_asset_count} /></Col>
        <Col xs={12} md={6}><Metric title="假分散" value={payload.false_diversification_warning} danger={payload.false_diversification_warning !== false} /></Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 12 }}>
        <Col xs={24} lg={12}>
          <Typography.Title level={5}>当前权重</Typography.Title>
          {Object.keys(weights).length ? Object.entries(weights).map(([name, value]) => <div key={name}><Flex justify="space-between"><span>{name}</span><span>{valueText(value)}</span></Flex><Progress percent={Math.max(0, Math.min(100, Number(value) * 100))} showInfo={false} /></div>) : <StatusTag value="MISSING" />}
        </Col>
        <Col xs={24} lg={12}>
          <Typography.Title level={5}>Marginal Sharpe</Typography.Title>
          {Object.keys(marginal).length ? <Descriptions column={1} items={Object.entries(marginal).map(([key, value]) => ({ key, label: key, children: valueText(value) }))} /> : <StatusTag value="MISSING" />}
        </Col>
      </Row>
    </ComponentFrame>
  )
}

function StructuredValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    const visible = value.slice(0, 100)
    return (
      <div>
        <pre className="vnext-json">{JSON.stringify(visible, null, 2)}</pre>
        {value.length > visible.length && (
          <Typography.Text type="secondary">仅渲染前 {visible.length} / {value.length} 条；完整数据请下载 JSON。</Typography.Text>
        )}
      </div>
    )
  }
  if (typeof value === 'object' && value !== null) {
    return <pre className="vnext-json">{JSON.stringify(value, null, 2)}</pre>
  }
  return valueText(value)
}

function GenericContent({ resource, title, data }: { resource: VNextResource; title: string; data: Record<VNextResource, unknown> }) {
  const component = componentAt(data, resource)
  const payload = objectOf(component.payload)
  const display = Object.keys(payload).length ? payload : component
  const entries = Object.entries(display).filter(([key]) => !['evidence', 'missing_evidence', 'data_sources', 'payload'].includes(key))
  return (
    <ComponentFrame title={title} component={component}>
      {entries.length ? (
        <Descriptions bordered size="small" column={{ xs: 1, sm: 2, lg: 3 }} items={entries.slice(0, 30).map(([key, value]) => ({ key, label: key, children: <StructuredValue value={value} /> }))} />
      ) : <Empty description="MISSING：没有真实运行产物" />}
    </ComponentFrame>
  )
}

function ApprovalContent({ data }: { data: Record<VNextResource, unknown> }) {
  const approvals = objectOf(data.approvals)
  const rows = arrayOf(approvals.items).map((item, index) => ({ key: String(item.approval_id ?? index), ...item }))
  const invalidate = useInvalidateVNext()
  const [working, setWorking] = useState<string | null>(null)
  const act = async (record: VNextRecord, action: 'approve' | 'reject' | 'delay' | 'modify') => {
    const id = String(record.approval_id ?? '')
    if (!id) return
    setWorking(`${id}:${action}`)
    try {
      await vnextApi.decideApproval(id, action, { approver: 'ui-user', reason: `UI ${action}; approval state only` })
      invalidate()
    } finally {
      setWorking(null)
    }
  }
  const columns: ColumnsType<VNextRecord> = [
    { title: 'Approval ID', dataIndex: 'approval_id', width: 190 },
    { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> },
    { title: '订单草案', dataIndex: 'order_draft', width: 260, render: (value) => <pre className="vnext-json compact">{JSON.stringify(value ?? {}, null, 2)}</pre> },
    { title: 'Regime', dataIndex: 'regime', render: valueText },
    { title: '半导体状态', dataIndex: 'semiconductor_mainline_state', render: valueText },
    { title: '模型分数', dataIndex: 'model_score', render: valueText },
    { title: '数据新鲜度', dataIndex: 'data_freshness', render: (value) => <StatusTag value={value} /> },
    { title: 'Kill Switch', dataIndex: 'kill_switch_triggered', render: (value) => <StatusTag value={value} /> },
    { title: '审批人', dataIndex: 'approver', render: valueText },
    { title: '审批时间', dataIndex: 'approval_time', render: valueText },
    {
      title: '审批动作（不下单）', fixed: 'right', width: 310,
      render: (_, record) => <Space wrap>{(['approve', 'reject', 'delay', 'modify'] as const).map((action) => <Button key={action} size="small" danger={action === 'reject'} loading={working === `${record.approval_id}:${action}`} onClick={() => act(record, action)}>{action}</Button>)}</Space>,
    },
  ]
  return (
    <Card title={<Space>Telegram 审批队列 <Badge count={Number(approvals.total ?? rows.length)} /></Space>}>
      <Alert type="warning" showIcon message="审批动作不会触发真实下单" description="后端仅更新审批记录；miniQMT 仍由 no_live_trade 和 Kill Switch 阻断。" style={{ marginBottom: 16 }} />
      {rows.length ? <Table size="small" scroll={{ x: 1900 }} columns={columns} dataSource={rows} /> : <Empty description="没有审批单；不会用 demo 订单填充" />}
    </Card>
  )
}

function DataHealthContent({ data }: { data: Record<VNextResource, unknown> }) {
  const component = componentAt(data, 'dataHealth')
  const sources = arrayOf(component.sources)
  const columns: ColumnsType<VNextRecord> = [
    { title: '数据源', dataIndex: 'source', width: 220 },
    { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} />, width: 110 },
    { title: '更新时间', dataIndex: 'updated_at', render: valueText, width: 220 },
    { title: '记录/文件', dataIndex: 'records_or_files', render: (value, row) => valueText(value ?? row.records) },
    { title: '缺失字段', dataIndex: 'missing_fields', render: valueText },
    { title: '说明', dataIndex: 'message', render: valueText },
    { title: '路径', dataIndex: 'path', width: 360, render: valueText },
  ]
  return (
    <ComponentFrame title="数据真实性与新鲜度" component={component}>
      <Alert type={component.status === 'OK' ? 'success' : 'error'} showIcon message={`总体状态 ${valueText(component.status)}`} description={valueText(component.truthfulness)} style={{ marginBottom: 16 }} />
      {sources.length ? <Table size="small" scroll={{ x: 1300 }} rowKey={(row) => String(row.source)} columns={columns} dataSource={sources} pagination={{ pageSize: 20 }} /> : <Empty description="MISSING：没有数据源健康记录" />}
    </ComponentFrame>
  )
}

function PageContent({ kind, data }: { kind: VNextPageKind; data: Record<VNextResource, unknown> }) {
  if (kind === 'home') return <HomeContent data={data} />
  if (kind === 'regime') return <RegimeContent data={data} />
  if (kind === 'semi') return <SemiContent data={data} />
  if (kind === 'candidates') return <CandidateContent data={data} />
  if (kind === 'portfolio') return <PortfolioContent data={data} />
  if (kind === 'approvals') return <ApprovalContent data={data} />
  if (kind === 'data-health') return <DataHealthContent data={data} />
  if (kind === 'ml') return <GenericContent resource="mlRanker" title="ML Factor / Ranker" data={data} />
  if (kind === 'backtests') return <GenericContent resource="backtests" title="回测与多 Regime 验证" data={data} />
  if (kind === 'trading') return <Space direction="vertical" size={16} style={{ width: '100%' }}><GenericContent resource="paper" title="Paper Trading" data={data} /><GenericContent resource="shadow" title="Shadow Trading" data={data} /><GenericContent resource="executionStatus" title="进入 Live Dry-run 的门禁" data={data} /></Space>
  if (kind === 'execution') return <GenericContent resource="executionStatus" title="miniQMT / Trading Mode" data={data} />
  return <GenericContent resource="antifragileReview" title="反脆弱复盘" data={data} />
}

export default function VNextPage({ kind }: { kind: VNextPageKind }) {
  const config = PAGE_CONFIG[kind]
  const [date, setDate] = useState(dayjs().format('YYYY-MM-DD'))
  const { data, isLoading, errors, refetch } = usePageData(kind, date)
  const latestUpdate = useMemo(() => {
    const values = Object.values(data).map((item) => objectOf(item).updated_at).filter(Boolean)
    const sorted = values.sort()
    return sorted.length ? String(sorted[sorted.length - 1]) : 'MISSING'
  }, [data])
  return (
    <div className="vnext-page" data-page-kind={kind}>
      <Flex justify="space-between" align="flex-start" wrap="wrap" gap={12} className="vnext-page-header">
        <div>
          <Typography.Title level={2} style={{ marginBottom: 4 }}>{config.title}</Typography.Title>
          <Typography.Text type="secondary">{config.subtitle}</Typography.Text>
          <div className="vnext-updated"><ClockCircleOutlined /> 最近更新：{latestUpdate}</div>
        </div>
        <Space wrap>
          <DatePicker allowClear={false} value={dayjs(date)} onChange={(value) => value && setDate(value.format('YYYY-MM-DD'))} />
          <Button icon={<ReloadOutlined />} loading={isLoading} onClick={() => refetch()}>刷新</Button>
          <Button icon={<DownloadOutlined />} href={reportDownloadUrl(date, 'md')}>Markdown</Button>
          <Button icon={<DownloadOutlined />} href={reportDownloadUrl(date, 'json')}>JSON</Button>
          <Button icon={<DownloadOutlined />} href={reportDownloadUrl(date, 'csv')}>CSV</Button>
        </Space>
      </Flex>
      {errors.length > 0 && <Alert type="error" showIcon message="API 请求失败" description={errors.join('；')} style={{ marginBottom: 16 }} />}
      {isLoading && !Object.values(data).some(Boolean) ? <Card loading style={{ minHeight: 320 }} /> : <PageContent kind={kind} data={data} />}
    </div>
  )
}
