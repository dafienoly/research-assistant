import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Col, Descriptions, Input, InputNumber, Row, Select, Space, Statistic, Table, Tag, Typography, Upload, message } from 'antd'
import { BellOutlined, CheckOutlined, SafetyCertificateOutlined, UploadOutlined } from '@ant-design/icons'
import PageHeader from '../components/common/PageHeader'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import {
  acknowledgeDecisionEvent,
  activateDailyAuthorization,
  confirmDecisionPositions,
  confirmMiniQmtPositions,
  createDailyAuthorization,
  getDecisionLoopStatus,
  getPositionHistory,
  getPositionImportTemplate,
  previewDecisionPositions,
  previewMiniQmtPositions,
  previewOcrPositions,
  revokeDailyAuthorization,
  rollbackPositionSnapshot,
  type DecisionEvent,
  type DecisionPosition,
  type PositionPreview,
  type PositionSnapshot,
} from '../api/decisionLoop'

const BOOK_ROWS = [
  { key: 'catalyst', book: '催化交易仓', horizon: '1–5 个交易日', budget: '25%' },
  { key: 'swing', book: '趋势波段仓', horizon: '2–8 周', budget: '50%' },
  { key: 'core', book: '核心逻辑仓', horizon: '3–12 个月', budget: '20%' },
]

const RISK_ROWS = [
  { key: 'intraday', trigger: '权益日内高点回撤 3%', action: '禁止开仓；催化仓减半', severity: 'L3' },
  { key: 'daily', trigger: '当日收益 ≤ -4%', action: '降低高 Beta 暴露', severity: 'L3' },
  { key: 'rolling', trigger: '20 日滚动回撤 10%', action: '只减仓模式', severity: 'L4' },
]

function severityColor(value: string) {
  return value === 'L4' ? 'red' : value === 'L3' ? 'orange' : 'blue'
}

export default function DecisionCenter() {
  const queryClient = useQueryClient()
  const [source, setSource] = useState<'csv' | 'clipboard'>('clipboard')
  const [content, setContent] = useState('')
  const [preview, setPreview] = useState<PositionPreview | null>(null)
  const [previewKind, setPreviewKind] = useState<'manual' | 'miniqmt'>('manual')
  const [history, setHistory] = useState<PositionSnapshot[]>([])
  const [strategySummary, setStrategySummary] = useState('盘中利润保护与计划内交易')
  const [parameterVersion, setParameterVersion] = useState('decision-loop-v1')
  const [maxOrderAmount, setMaxOrderAmount] = useState(50_000)
  const [maxTotalAmount, setMaxTotalAmount] = useState(100_000)
  const [ordersJson, setOrdersJson] = useState('[]')
  const [activationNonce, setActivationNonce] = useState('')
  const [activationHash, setActivationHash] = useState('')
  const [hashConfirmed, setHashConfirmed] = useState(false)
  const statusQuery = useQuery({
    queryKey: ['decision-loop-status'],
    queryFn: async () => (await getDecisionLoopStatus()).data,
    refetchInterval: 60_000,
  })
  const status = statusQuery.data
  const positions = status?.current_position_snapshot?.positions ?? []
  const authorization = status?.daily_authorization
  const previewMutation = useMutation({
    mutationFn: () => previewDecisionPositions(source, content),
    onSuccess: result => {
      if (result.data) {
        setPreviewKind('manual')
        setPreview(result.data)
      }
      else message.error('导入预览未返回数据')
    },
    onError: error => message.error(`导入预览失败：${error instanceof Error ? error.message : '未知错误'}`),
  })
  const qmtPreviewMutation = useMutation({
    mutationFn: previewMiniQmtPositions,
    onSuccess: result => {
      if (result.data) {
        setPreviewKind('miniqmt')
        setPreview(result.data)
      }
    },
    onError: error => message.error(`MiniQMT 对账失败：${error instanceof Error ? error.message : '未知错误'}`),
  })
  const ocrPreviewMutation = useMutation({
    mutationFn: previewOcrPositions,
    onSuccess: result => {
      if (result.data) {
        setPreviewKind('manual')
        setPreview(result.data)
      }
    },
    onError: error => message.error(`OCR 识别失败：${error instanceof Error ? error.message : '未知错误'}`),
  })
  const templateMutation = useMutation({
    mutationFn: getPositionImportTemplate,
    onSuccess: result => {
      setSource('csv')
      setContent(result.data?.csv ?? '')
      message.success('导入模板已载入，可替换示例行后预览')
    },
  })
  const historyMutation = useMutation({
    mutationFn: () => getPositionHistory(20),
    onSuccess: result => setHistory(result.data ?? []),
  })
  const rollbackMutation = useMutation({
    mutationFn: rollbackPositionSnapshot,
    onSuccess: async () => {
      message.success('历史持仓快照已回滚')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
      historyMutation.mutate()
    },
  })
  const confirmMutation = useMutation({
    mutationFn: () => previewKind === 'miniqmt'
      ? confirmMiniQmtPositions(preview!.preview_id, preview!.proposed_snapshot.content_hash)
      : confirmDecisionPositions(preview!.preview_id, preview!.proposed_snapshot.content_hash),
    onSuccess: async () => {
      message.success('持仓快照已确认')
      setPreview(null)
      setContent('')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
    },
  })
  const ackMutation = useMutation({
    mutationFn: acknowledgeDecisionEvent,
    onSuccess: async () => {
      message.success('事件已确认，Telegram 与企业微信提醒同时关闭')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
    },
  })
  const createAuthorizationMutation = useMutation({
    mutationFn: () => {
      const orders = JSON.parse(ordersJson)
      if (!Array.isArray(orders)) throw new Error('计划订单必须是 JSON 数组')
      return createDailyAuthorization({
        trading_date: new Date().toLocaleDateString('sv-SE'),
        strategy_summary: strategySummary,
        risk_budget: { catalyst: 0.25, swing: 0.5, core: 0.2, cash_min: 0.05 },
        max_order_amount: maxOrderAmount,
        max_total_amount: maxTotalAmount,
        orders,
        parameter_version: parameterVersion,
      })
    },
    onSuccess: async result => {
      const auth = result.data?.authorization
      setActivationNonce(result.data?.confirmation_nonce ?? '')
      setActivationHash(auth?.plan.plan_hash ?? '')
      setHashConfirmed(false)
      message.success('授权计划已创建，请核对计划哈希并二次确认')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
    },
    onError: error => message.error(`创建授权失败：${error instanceof Error ? error.message : '未知错误'}`),
  })
  const activateAuthorizationMutation = useMutation({
    mutationFn: () => activateDailyAuthorization(authorization!.plan.trading_date, activationNonce, activationHash),
    onSuccess: async () => {
      message.success('当日授权已激活，收盘自动失效')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
    },
    onError: error => message.error(`激活失败：${error instanceof Error ? error.message : '未知错误'}`),
  })
  const revokeAuthorizationMutation = useMutation({
    mutationFn: () => revokeDailyAuthorization(authorization!.plan.trading_date, 'user_revoked_from_console'),
    onSuccess: async () => {
      message.success('当日授权已撤销')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
    },
  })

  const eventRows = useMemo(() => (status?.recent_events ?? []).slice().reverse(), [status?.recent_events])

  if (statusQuery.isLoading) return <LoadingState tip="正在读取量化决策闭环状态" />
  if (statusQuery.isError) return <ErrorState description={statusQuery.error instanceof Error ? statusQuery.error.message : '状态加载失败'} onRetry={() => statusQuery.refetch()} />

  return (
    <div>
      <PageHeader title="量化决策中心" dataSource="机会发现 → 三周期组合 → 盘中利润保护 → 受控执行 → 复盘学习" />

      <Alert
        type={authorization?.status === 'active' ? 'warning' : 'info'}
        showIcon
        title={authorization?.status === 'active' ? '当日执行授权已生效' : 'MiniQMT 自动执行当前为 Fail-Closed'}
        description={authorization?.status === 'active'
          ? `${authorization.plan.strategy_summary}；单笔上限 ¥${authorization.plan.max_order_amount.toLocaleString()}；${authorization.expires_at} 自动失效。`
          : '未配置 MiniQMT 或没有有效日级授权时，系统只生成操作卡片，不会下单。'}
        style={{ marginBottom: 16 }}
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}><Card><Statistic title="已确认持仓" value={positions.length} suffix="项" prefix={<SafetyCertificateOutlined />} /></Card></Col>
        <Col xs={24} md={8}><Card><Statistic title="未确认风险事件" value={status?.unacknowledged_event_count ?? eventRows.filter(row => !row.acknowledged).length} suffix="项" prefix={<BellOutlined />} /></Card></Col>
        <Col xs={24} md={8}><Card><Statistic title="执行授权" value={authorization?.status ?? 'inactive'} styles={{ content: { color: authorization?.status === 'active' ? '#d97706' : '#64748b' } }} /></Card></Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card title="三周期账簿与进取型预算">
            <Table
              size="small"
              pagination={false}
              rowKey="key"
              dataSource={BOOK_ROWS}
              columns={[
                { title: '账簿', dataIndex: 'book' },
                { title: '持有周期', dataIndex: 'horizon' },
                { title: '预算上限', dataIndex: 'budget' },
              ]}
            />
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              现金不低于 5%；单股 15%、单 ETF 30%、单主题穿透 70%。同一标的跨账簿时，理由、仓位与退出条件独立。
            </Typography.Paragraph>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card title="组合硬风控">
            <Table
              size="small"
              pagination={false}
              rowKey="key"
              dataSource={RISK_ROWS}
              columns={[
                { title: '触发', dataIndex: 'trigger' },
                { title: '强制动作', dataIndex: 'action' },
                { title: '级别', dataIndex: 'severity', render: value => <Tag color={severityColor(value)}>{value}</Tag> },
              ]}
            />
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              单标的最高浮盈回撤 2 点 L2；3 点 L3 减半；跌破上午低点或 VWAP 且 10 分钟未收回则 L4 清交易仓。
            </Typography.Paragraph>
          </Card>
        </Col>

        <Col xs={24} xl={12}>
          <Card title="持仓导入与差异确认" extra={<Tag color={status?.current_position_snapshot?.confirmed ? 'green' : 'default'}>{status?.current_position_snapshot?.confirmed ? '已确认' : '未导入'}</Tag>}>
            <Space orientation="vertical" style={{ width: '100%' }} size="middle">
              <Select value={source} onChange={setSource} options={[{ value: 'clipboard', label: '剪贴板表格' }, { value: 'csv', label: 'CSV 文本' }]} style={{ width: 180 }} />
              <Input.TextArea
                aria-label="持仓CSV或剪贴板内容"
                rows={5}
                value={content}
                onChange={event => setContent(event.target.value)}
                placeholder={'证券代码\t证券名称\t持仓数量\t可用数量\t成本价\n588200.SH\t设备ETF\t1000\t1000\t1.20'}
              />
              <Button icon={<UploadOutlined />} type="primary" disabled={!content.trim()} loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
                生成差异预览
              </Button>
              <Button loading={qmtPreviewMutation.isPending} onClick={() => qmtPreviewMutation.mutate()}>
                从 MiniQMT 读取并预览差异
              </Button>
              <Space wrap>
                <Upload
                  accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
                  maxCount={1}
                  showUploadList={false}
                  customRequest={({ file, onSuccess, onError }) => {
                    ocrPreviewMutation.mutate(file as File, {
                      onSuccess: () => onSuccess?.({}),
                      onError: error => onError?.(error),
                    })
                  }}
                >
                  <Button loading={ocrPreviewMutation.isPending}>上传券商截图 OCR</Button>
                </Upload>
                <Button loading={templateMutation.isPending} onClick={() => templateMutation.mutate()}>载入导入模板</Button>
                <Button loading={historyMutation.isPending} onClick={() => historyMutation.mutate()}>查看历史快照</Button>
              </Space>
              {preview && (
                <Alert
                  type={preview.requires_correction ? 'error' : 'warning'}
                  showIcon
                  title={`${previewKind === 'miniqmt' ? '券商对账' : '导入'}待确认：新增 ${preview.additions.length}，删除 ${preview.removals.length}，变更 ${preview.changes.length}，不变 ${preview.unchanged}`}
                  description={<Space orientation="vertical">
                    {preview.requires_correction && <Typography.Text type="danger">低置信度字段必须人工修正后重新生成预览：{preview.quality_issues?.map(issue => <Tag color="red" key={`${issue.text}:${issue.confidence}`}>{issue.text} ({issue.confidence.toFixed(0)})</Tag>)}</Typography.Text>}
                    <Button icon={<CheckOutlined />} disabled={preview.requires_correction} loading={confirmMutation.isPending} onClick={() => confirmMutation.mutate()}>确认覆盖当前组合</Button>
                  </Space>}
                />
              )}
              <Table<DecisionPosition>
                size="small"
                pagination={{ pageSize: 5, hideOnSinglePage: true }}
                rowKey={row => `${row.symbol}:${row.book}`}
                dataSource={positions}
                locale={{ emptyText: '尚无已确认持仓。粘贴券商持仓表并完成差异确认后启用分钟监控。' }}
                columns={[
                  { title: '标的', dataIndex: 'symbol' },
                  { title: '账簿', dataIndex: 'book' },
                  { title: '数量', dataIndex: 'quantity' },
                  { title: '可用/冻结', key: 'available', render: (_, row) => `${row.available_quantity}/${row.frozen_quantity ?? 0}` },
                  { title: '成本', dataIndex: 'cost_price' },
                ]}
              />
              {history.length > 0 && <Table<PositionSnapshot>
                size="small"
                pagination={{ pageSize: 5, hideOnSinglePage: true }}
                rowKey="snapshot_id"
                dataSource={history}
                columns={[
                  { title: '快照时间', dataIndex: 'as_of' },
                  { title: '来源', dataIndex: 'source' },
                  { title: '持仓数', render: (_, row) => row.positions.length },
                  { title: '操作', render: (_, row) => <Button size="small" danger loading={rollbackMutation.isPending} onClick={() => rollbackMutation.mutate(row.snapshot_id)}>一键回滚</Button> },
                ]}
              />}
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={12}>
          <Card title="风险事件与双通道确认" extra={<Space><Tag>Telegram</Tag><Tag>企业微信</Tag></Space>}>
            <Table<DecisionEvent>
              size="small"
              pagination={{ pageSize: 6, hideOnSinglePage: true }}
              rowKey="event_id"
              dataSource={eventRows}
              locale={{ emptyText: '当前无风险事件。L2 进入摘要，L3/L4 将同时推送两个通道。' }}
              columns={[
                { title: '级别', dataIndex: 'severity', render: value => <Tag color={severityColor(value)}>{value}</Tag> },
                { title: '标的', dataIndex: 'symbol', render: value => value || '组合' },
                { title: '操作卡片', dataIndex: 'reason' },
                { title: '动作', dataIndex: 'action' },
                { title: '状态', key: 'ack', render: (_, row) => row.acknowledged
                  ? <Tag color="green">acknowledged</Tag>
                  : <Button size="small" onClick={() => ackMutation.mutate(row.event_id)}>双通道确认</Button> },
              ]}
            />
          </Card>
        </Col>

        <Col xs={24}>
          <Card title="当日日级执行授权" extra={<Tag color={authorization?.status === 'active' ? 'orange' : 'default'}>{authorization?.status ?? '未创建'}</Tag>}>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Space orientation="vertical" style={{ width: '100%' }}>
                  <Space.Compact style={{ width: '100%' }}><Button disabled>策略</Button><Input aria-label="策略摘要" value={strategySummary} onChange={event => setStrategySummary(event.target.value)} /></Space.Compact>
                  <Space.Compact style={{ width: '100%' }}><Button disabled>参数版本</Button><Input aria-label="参数版本" value={parameterVersion} onChange={event => setParameterVersion(event.target.value)} /></Space.Compact>
                  <Space wrap>
                    <Typography.Text>单笔上限</Typography.Text>
                    <InputNumber min={1} value={maxOrderAmount} onChange={value => setMaxOrderAmount(Number(value ?? 0))} />
                    <Typography.Text>总额上限</Typography.Text>
                    <InputNumber min={1} value={maxTotalAmount} onChange={value => setMaxTotalAmount(Number(value ?? 0))} />
                  </Space>
                  <Input.TextArea aria-label="计划订单JSON" rows={6} value={ordersJson} onChange={event => setOrdersJson(event.target.value)} placeholder='[{"order_id":"ord_1","symbol":"588200.SH","side":"SELL","quantity":500,"limit_price":1.2,"book":"catalyst","strategy":"profit_guard","reason":"计划减仓"}]' />
                  <Typography.Text type="secondary">风险预算固定展示：催化 25%、波段 50%、核心 20%、现金至少 5%。计划外 BUY 始终阻断。</Typography.Text>
                  <Button type="primary" loading={createAuthorizationMutation.isPending} onClick={() => createAuthorizationMutation.mutate()}>创建待确认授权</Button>
                </Space>
              </Col>
              <Col xs={24} md={12}>
                {authorization ? <Descriptions bordered size="small" column={1} items={[
                  { key: 'strategy', label: '策略', children: authorization.plan.strategy_summary },
                  { key: 'parameter', label: '参数版本', children: authorization.plan.parameter_version },
                  { key: 'budget', label: '风险预算', children: JSON.stringify(authorization.plan.risk_budget) },
                  { key: 'orders', label: '计划订单', children: `${authorization.plan.orders.length} 笔` },
                  { key: 'limits', label: '单笔 / 总额', children: `¥${authorization.plan.max_order_amount.toLocaleString()} / ¥${authorization.plan.max_total_amount.toLocaleString()}` },
                  { key: 'hash', label: '计划哈希', children: <Typography.Text copyable code>{authorization.plan.plan_hash}</Typography.Text> },
                  { key: 'expiry', label: '失效时间', children: authorization.expires_at },
                ]} /> : <Alert type="info" showIcon title="尚未创建当日授权" />}
                {authorization?.status === 'pending' && (
                  <Space orientation="vertical" style={{ width: '100%', marginTop: 16 }}>
                    <Checkbox checked={hashConfirmed} onChange={event => setHashConfirmed(event.target.checked)}>我已逐项核对策略、预算、订单和计划哈希</Checkbox>
                    <Button danger disabled={!hashConfirmed || !activationNonce || activationHash !== authorization.plan.plan_hash} loading={activateAuthorizationMutation.isPending} onClick={() => activateAuthorizationMutation.mutate()}>二次确认并激活</Button>
                    {!activationNonce && <Alert type="warning" showIcon title="当前页面没有本次创建的确认随机码，请重新创建计划后激活" />}
                  </Space>
                )}
                {authorization?.status === 'active' && <Button danger style={{ marginTop: 16 }} loading={revokeAuthorizationMutation.isPending} onClick={() => revokeAuthorizationMutation.mutate()}>立即撤销当日授权</Button>}
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      <Card title="数据与执行门禁" style={{ marginTop: 16 }}>
        <Descriptions bordered size="small" column={{ xs: 1, md: 2 }} items={[
          { key: 'core', label: '核心数据', children: '行情 / 持仓 / 交易日历异常 → 禁止可执行建议' },
          { key: 'aux', label: '辅助数据', children: '新闻 / 资金流 / 基本面缺失 → 降置信度、仅观察、禁止自动 BUY' },
          { key: 'notify', label: '通知一致性', children: '统一 event_id、独立回执；任一通道失败不阻塞风险处置' },
          { key: 'learning', label: '参数学习', children: '只生成候选；样本外验证 + 周度人工确认后晋级生产' },
          { key: 'gate-mode', label: '当前数据门禁', children: `${status?.data_gate?.mode ?? 'blocked'} ${(status?.data_gate?.reasons ?? []).join('；')}` },
          { key: 'risk-mode', label: '当前账户风险模式', children: status?.account_risk_mode?.mode ?? 'unknown' },
          { key: 'execution', label: '执行就绪度', children: status?.execution_readiness?.ready ? 'ready' : (status?.execution_readiness?.reasons ?? []).join('；') },
        ]} />
      </Card>
    </div>
  )
}
