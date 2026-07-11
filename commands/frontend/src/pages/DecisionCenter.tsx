import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Descriptions, Input, Row, Select, Space, Statistic, Table, Tag, Typography, message } from 'antd'
import { BellOutlined, CheckOutlined, SafetyCertificateOutlined, UploadOutlined } from '@ant-design/icons'
import PageHeader from '../components/common/PageHeader'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import {
  acknowledgeDecisionEvent,
  confirmDecisionPositions,
  getDecisionLoopStatus,
  previewDecisionPositions,
  type DecisionEvent,
  type DecisionPosition,
  type PositionPreview,
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
  const statusQuery = useQuery({
    queryKey: ['decision-loop-status'],
    queryFn: async () => (await getDecisionLoopStatus()).data,
    refetchInterval: 60_000,
  })
  const previewMutation = useMutation({
    mutationFn: () => previewDecisionPositions(source, content),
    onSuccess: result => {
      if (result.data) setPreview(result.data)
      else message.error('导入预览未返回数据')
    },
    onError: error => message.error(`导入预览失败：${error instanceof Error ? error.message : '未知错误'}`),
  })
  const confirmMutation = useMutation({
    mutationFn: () => confirmDecisionPositions(preview!.preview_id, preview!.proposed_snapshot.content_hash),
    onSuccess: async () => {
      message.success('持仓快照已确认')
      setPreview(null)
      setContent('')
      await queryClient.invalidateQueries({ queryKey: ['decision-loop-status'] })
    },
  })
  const ackMutation = useMutation({
    mutationFn: acknowledgeDecisionEvent,
    onSuccess: () => message.success('事件已确认，Telegram 与企业微信提醒同时关闭'),
  })

  const status = statusQuery.data
  const positions = status?.current_position_snapshot?.positions ?? []
  const authorization = status?.daily_authorization
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
        <Col xs={24} md={8}><Card><Statistic title="未确认风险事件" value={eventRows.length} suffix="项" prefix={<BellOutlined />} /></Card></Col>
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
              {preview && (
                <Alert
                  type="warning"
                  showIcon
                  title={`待确认：新增 ${preview.additions.length}，删除 ${preview.removals.length}，变更 ${preview.changes.length}，不变 ${preview.unchanged}`}
                  description={<Button icon={<CheckOutlined />} loading={confirmMutation.isPending} onClick={() => confirmMutation.mutate()}>确认覆盖当前组合</Button>}
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
                  { title: '成本', dataIndex: 'cost_price' },
                ]}
              />
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
                { title: '确认', key: 'ack', render: (_, row) => <Button size="small" onClick={() => ackMutation.mutate(row.event_id)}>双通道确认</Button> },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card title="数据与执行门禁" style={{ marginTop: 16 }}>
        <Descriptions bordered size="small" column={{ xs: 1, md: 2 }} items={[
          { key: 'core', label: '核心数据', children: '行情 / 持仓 / 交易日历异常 → 禁止可执行建议' },
          { key: 'aux', label: '辅助数据', children: '新闻 / 资金流 / 基本面缺失 → 降置信度、仅观察、禁止自动 BUY' },
          { key: 'notify', label: '通知一致性', children: '统一 event_id、独立回执；任一通道失败不阻塞风险处置' },
          { key: 'learning', label: '参数学习', children: '只生成候选；样本外验证 + 周度人工确认后晋级生产' },
        ]} />
      </Card>
    </div>
  )
}
