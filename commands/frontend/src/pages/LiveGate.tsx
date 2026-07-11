/** V5.12 Live Gate — 实盘信号网关 */

import React from 'react'
import {
  Card,
  Table,
  Tag,
  Typography,
  Space,
  Spin,
  Alert,
  Button,
  Tooltip,
  Descriptions,
  Row,
  Col,
  Empty,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  ReloadOutlined,
  HistoryOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import ErrorState from '../components/common/ErrorState'
import {
  useLiveGateLatest,
  useLiveGateHistory,
  useRunLiveGate,
} from '../hooks/useLiveReadinessReport'
import type { GateCheckResult, GateReport, GateHistoryItem } from '../api/schemas'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Text, Title } = Typography

// ─── Styles ────────────────────────────────────────────────────────────────

const CARD: React.CSSProperties = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
  marginBottom: 16,
}

const SECTION_TITLE: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  color: '#0F172A',
  marginBottom: 16,
  paddingBottom: 12,
  borderBottom: '1px solid #E2E8F0',
}

const GATE_NAME_MAP: Record<string, string> = {
  DataHealthGate: '数据健康',
  UniversePurityGate: '股票池纯度',
  BenchmarkGate: '基准体系',
  SemiconductorPeerGate: '半导体同池',
  RiskExposureGate: '风险暴露',
  CostAdjustedReturnGate: '成本调整收益',
  PaperTradingGate: 'Paper Trading',
  ShadowTradingGate: 'Shadow Trading',
  TradeConstraintGate: '交易约束',
  ManualApprovalGate: '人工审批',
  KillSwitchGate: 'Kill Switch',
  AuditTrailGate: '审计日志',
  WeChatNotifyGate: '企业微信通知',
  QMTAccountGate: 'QMT 账户',
}

function getGateLabel(name: string): string {
  return GATE_NAME_MAP[name] || name
}

// ─── Gate Status helpers ──────────────────────────────────────────────────

type GateStatus = 'passed' | 'failed' | 'warning'

function getGateStatus(gate: GateCheckResult): GateStatus {
  if (gate.passed) return 'passed'
  if (gate.severity === 'warning' || gate.severity === 'info') return 'warning'
  return 'failed'
}

function GateStatusTag({ gate }: { gate: GateCheckResult }) {
  const status = getGateStatus(gate)
  if (status === 'passed') {
    return (
      <Tag icon={<CheckCircleOutlined />} color="success" style={{ fontSize: 13, padding: '2px 10px' }}>
        通过
      </Tag>
    )
  }
  if (status === 'warning') {
    return (
      <Tag icon={<WarningOutlined />} color="warning" style={{ fontSize: 13, padding: '2px 10px' }}>
        待定
      </Tag>
    )
  }
  return (
    <Tag icon={<CloseCircleOutlined />} color="error" style={{ fontSize: 13, padding: '2px 10px' }}>
      失败
    </Tag>
  )
}

function GateSeverityDot({ severity }: { severity: string }) {
  const color = {
    blocker: '#DC2626',
    warning: '#D97706',
    info: '#059669',
  }[severity] || '#64748B'
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        backgroundColor: color,
        marginRight: 6,
      }}
    />
  )
}

// ─── Overall Status Banner ────────────────────────────────────────────────

function OverallStatusBanner({ overall, report }: { overall: string; report?: GateReport }) {
  const isReady = overall === 'READY'
  const color = isReady ? '#059669' : '#DC2626'
  const bgColor = isReady ? '#ECFDF5' : '#FEF2F2'
  const borderColor = isReady ? '#A7F3D0' : '#FECACA'
  const icon = isReady ? <CheckCircleOutlined /> : <CloseCircleOutlined />

  return (
    <div
      style={{
        padding: '24px 32px',
        borderRadius: 12,
        background: bgColor,
        border: `2px solid ${borderColor}`,
        marginBottom: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: '50%',
            background: color,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 28,
            color: '#fff',
          }}
        >
          {icon}
        </div>
        <div>
          <Title level={3} style={{ margin: 0, color }}>
            {isReady ? '✅ 全部门禁通过' : '❌ 存在阻塞项'}
          </Title>
          <Text style={{ color: '#475569', fontSize: 14 }}>
            {isReady
              ? '所有 Gate 通过，可以申请小资金实盘'
              : `${report?.blockers?.length || 0} 个阻塞项需要修复后再检查`}
          </Text>
        </div>
      </div>
      {report && (
        <div style={{ textAlign: 'right' }}>
          <Text style={{ color: '#64748B', fontSize: 12, display: 'block' }}>
            {report.run_id}
          </Text>
          <Text style={{ color: '#64748B', fontSize: 12 }}>
            {dayjs(report.scanned_at).format('YYYY-MM-DD HH:mm:ss')}
          </Text>
        </div>
      )}
    </div>
  )
}

// ─── Gate Checklist Table ─────────────────────────────────────────────────

const GATE_TABLE_COLUMNS = [
  {
    title: '#',
    key: 'index',
    width: 50,
    render: (_: unknown, __: unknown, i: number) => i + 1,
  },
  {
    title: 'Gate 名称',
    dataIndex: 'gate_name',
    key: 'gate_name',
    width: 200,
    render: (name: string) => (
      <Space>
        <Text strong style={{ fontSize: 14 }}>
          {getGateLabel(name)}
        </Text>
        <Text style={{ color: '#94A3B8', fontSize: 11 }}>{name}</Text>
      </Space>
    ),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (_: unknown, record: GateCheckResult) => <GateStatusTag gate={record} />,
  },
  {
    title: '严重程度',
    key: 'severity',
    width: 100,
    render: (_: unknown, record: GateCheckResult) => (
      <Space>
        <GateSeverityDot severity={record.severity} />
        <Text style={{ fontSize: 12, color: '#475569' }}>
          {
            {
              blocker: '阻塞',
              warning: '警告',
              info: '信息',
            }[record.severity] || record.severity
          }
        </Text>
      </Space>
    ),
  },
  {
    title: '消息',
    dataIndex: 'message',
    key: 'message',
    width: 280,
    render: (msg: string) => (
      <Text style={{ color: '#334155', fontSize: 13 }}>{msg || '-'}</Text>
    ),
  },
  {
    title: '证据',
    dataIndex: 'evidence',
    key: 'evidence',
    width: 280,
    render: (ev: string) => (
      <Tooltip title={ev}>
        <Text
          style={{ color: '#64748B', fontSize: 12, maxWidth: 260, display: 'inline-block' }}
          ellipsis
        >
          {ev || '-'}
        </Text>
      </Tooltip>
    ),
  },
  {
    title: '修复建议',
    dataIndex: 'fix_suggestion',
    key: 'fix_suggestion',
    width: 260,
    render: (fix: string) =>
      fix ? (
        <Text style={{ color: '#DC2626', fontSize: 12 }}>{fix}</Text>
      ) : (
        <Text style={{ color: '#94A3B8', fontSize: 12 }}>-</Text>
      ),
  },
]

function GateChecklist({ gates }: { gates: GateCheckResult[] }) {
  return (
    <Table
      dataSource={gates}
      columns={GATE_TABLE_COLUMNS}
      rowKey="gate_name"
      pagination={false}
      size="small"
      bordered
      style={{ fontSize: 13 }}
      rowClassName={(record) => {
        if (record.passed) return ''
        if (record.severity === 'blocker') return 'gate-row-blocker'
        return 'gate-row-warning'
      }}
    />
  )
}

// ─── Blockers Section ─────────────────────────────────────────────────────

function BlockersSection({ blockers }: { blockers: GateReport['blockers'] }) {
  if (!blockers || blockers.length === 0) return null

  return (
    <div
      style={{
        background: '#FEF2F2',
        border: '1px solid #FECACA',
        borderRadius: 10,
        padding: 20,
        marginBottom: 24,
      }}
    >
      <Space style={{ marginBottom: 16 }}>
        <CloseCircleOutlined style={{ color: '#DC2626', fontSize: 20 }} />
        <Title level={5} style={{ margin: 0, color: '#991B1B' }}>
          阻塞项 ({blockers.length})
        </Title>
      </Space>
      {blockers.map((b, i) => (
        <div
          key={b.gate_name}
          style={{
            padding: '12px 16px',
            background: '#FFF',
            borderRadius: 8,
            marginBottom: i < blockers.length - 1 ? 10 : 0,
            border: '1px solid #FECACA',
          }}
        >
          <Row gutter={16} align="top">
            <Col flex="200px">
              <Space>
                <CloseCircleOutlined style={{ color: '#DC2626' }} />
                <Text strong style={{ color: '#991B1B' }}>
                  {getGateLabel(b.gate_name)}
                </Text>
              </Space>
            </Col>
            <Col flex="auto">
              <Text style={{ color: '#7F1D1D', display: 'block', marginBottom: 4 }}>
                {b.message}
              </Text>
              {b.evidence && (
                <Text style={{ color: '#92400E', fontSize: 12, display: 'block', marginBottom: 4 }}>
                  证据: {b.evidence}
                </Text>
              )}
              {b.fix_suggestion && (
                <div style={{ marginTop: 6 }}>
                  <Text style={{ color: '#DC2626', fontSize: 12, fontWeight: 600 }}>
                    修复建议: {b.fix_suggestion}
                  </Text>
                </div>
              )}
            </Col>
          </Row>
        </div>
      ))}
    </div>
  )
}

// ─── Summary Metrics ──────────────────────────────────────────────────────

function SummaryMetrics({ report }: { report: GateReport }) {
  const total = report.gates?.length || 0
  const passed = report.gates?.filter((g) => g.passed).length || 0
  const warnings = report.warnings?.length || 0
  const failed = report.gates?.filter((g) => !g.passed && g.severity === 'blocker').length || 0

  const metrics = [
    {
      label: 'Gate 总数',
      value: total,
      color: '#0F172A',
      bg: '#F1F5F9',
    },
    {
      label: '通过',
      value: passed,
      color: '#059669',
      bg: '#D1FAE5',
    },
    {
      label: '阻塞',
      value: failed,
      color: '#DC2626',
      bg: '#FEE2E2',
    },
    {
      label: '警告',
      value: warnings,
      color: '#D97706',
      bg: '#FEF3C7',
    },
  ]

  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      {metrics.map((m) => (
        <Col span={6} key={m.label}>
          <div
            style={{
              background: m.bg,
              borderRadius: 10,
              padding: '16px 20px',
              textAlign: 'center',
            }}
          >
            <Text style={{ color: m.color, fontSize: 28, fontWeight: 700, display: 'block' }}>
              {m.value}
            </Text>
            <Text style={{ color: '#475569', fontSize: 13 }}>{m.label}</Text>
          </div>
        </Col>
      ))}
    </Row>
  )
}

// ─── History Table ────────────────────────────────────────────────────────

const HISTORY_COLUMNS = [
  {
    title: '运行 ID',
    dataIndex: 'run_id',
    key: 'run_id',
    width: 200,
    render: (id: string) => (
      <Text code style={{ fontSize: 11 }}>
        {id}
      </Text>
    ),
  },
  {
    title: '检查时间',
    dataIndex: 'scanned_at',
    key: 'scanned_at',
    width: 180,
    render: (t: string) => (
      <Tooltip title={dayjs(t).format('YYYY-MM-DD HH:mm:ss')}>
        <Text style={{ fontSize: 12 }}>{dayjs(t).fromNow()}</Text>
      </Tooltip>
    ),
  },
  {
    title: '总体状态',
    dataIndex: 'overall',
    key: 'overall',
    width: 120,
    render: (overall: string) => (
      <Tag
        icon={overall === 'READY' ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        color={overall === 'READY' ? 'success' : 'error'}
      >
        {overall === 'READY' ? 'READY' : 'NOT_READY'}
      </Tag>
    ),
  },
  {
    title: '通过率',
    key: 'pass_rate',
    width: 120,
    render: (_: unknown, record: GateHistoryItem) => (
      <Text style={{ fontSize: 13 }}>
        {record.passed_count}/{record.total_count}
      </Text>
    ),
  },
  {
    title: '阻塞数',
    dataIndex: 'blocker_count',
    key: 'blocker_count',
    width: 80,
    render: (n: number) =>
      n > 0 ? (
        <Text style={{ color: '#DC2626', fontWeight: 600 }}>{n}</Text>
      ) : (
        <Text style={{ color: '#059669' }}>{n}</Text>
      ),
  },
]

function HistorySection({ history }: { history: GateHistoryItem[] }) {
  if (!history || history.length === 0) {
    return (
      <Card style={CARD}>
        <div style={SECTION_TITLE}>
          <Space>
            <HistoryOutlined />
            <span>历史记录</span>
          </Space>
        </div>
        <Empty description="暂无历史检查记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Card>
    )
  }

  return (
    <Card style={CARD}>
      <div style={SECTION_TITLE}>
        <Space>
          <HistoryOutlined />
          <span>历史记录（最近 {history.length} 次）</span>
        </Space>
      </div>
      <Table
        dataSource={history}
        columns={HISTORY_COLUMNS}
        rowKey="run_id"
        pagination={false}
        size="small"
        bordered
      />
    </Card>
  )
}

// ─── Approval Records Section ─────────────────────────────────────────────

function ApprovalRecordsSection() {
  return (
    <Card style={CARD}>
      <div style={SECTION_TITLE}>
        <Space>
          <FileTextOutlined />
          <span>审批记录</span>
        </Space>
      </div>
      <Empty
        description="暂无审批记录。通过全部门禁后，需人工审批才能实盘交易。"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      >
        <Text style={{ color: '#64748B', fontSize: 12, display: 'block' }}>
          审批流程: 执行 check_all() → READY → 生成 ManualApprovalPackage → 审批人确认
        </Text>
      </Empty>
    </Card>
  )
}

// ─── Run Button ───────────────────────────────────────────────────────────

function RunButton({
  onRun,
  loading,
}: {
  onRun: () => void
  loading: boolean
}) {
  return (
    <Button
      type="primary"
      size="large"
      icon={<PlayCircleOutlined />}
      onClick={onRun}
      loading={loading}
      style={{
        height: 44,
        borderRadius: 8,
        fontSize: 15,
        fontWeight: 600,
        background: '#0F172A',
        borderColor: '#0F172A',
      }}
    >
      运行检查
    </Button>
  )
}

// ─── Gate Info Sidebar ────────────────────────────────────────────────────

function GateInfoSidebar({ report }: { report: GateReport }) {
  const infoItems = [
    { label: '运行 ID', value: report.run_id },
    { label: '检查时间', value: dayjs(report.scanned_at).format('YYYY-MM-DD HH:mm:ss') },
    {
      label: 'Gate 数量',
      value: `${report.gates?.length || 0} 道`,
    },
    {
      label: '通过',
      value: `${report.gates?.filter((g) => g.passed).length || 0} 道`,
    },
    {
      label: '阻塞',
      value: `${report.blockers?.length || 0} 道`,
    },
    {
      label: '警告',
      value: `${report.warnings?.length || 0} 道`,
    },
  ]

  return (
    <Card
      style={{ ...CARD, marginBottom: 24 }}
      styles={{ body: { padding: 20 } }}
    >
      <div style={SECTION_TITLE}>检查摘要</div>
      <Descriptions column={1} size="small" bordered>
        {infoItems.map((item) => (
          <Descriptions.Item
            key={item.label}
            label={<Text style={{ fontSize: 12, color: '#64748B' }}>{item.label}</Text>}
          >
            <Text style={{ fontSize: 13 }}>{item.value}</Text>
          </Descriptions.Item>
        ))}
      </Descriptions>
    </Card>
  )
}

// ─── Main Page Component ──────────────────────────────────────────────────

const LiveGate: React.FC = () => {
  const {
    data: latestResp,
    isLoading: loadingLatest,
    isError: errorLatest,
    error: latestError,
    refetch: refetchLatest,
  } = useLiveGateLatest()

  const {
    data: historyResp,
  } = useLiveGateHistory()

  const runMutation = useRunLiveGate()

  const report = latestResp?.data
  const history = historyResp?.data?.history

  // ── Run check handler ──
  const handleRun = () => {
    runMutation.mutate()
  }

  // ── Error state ──
  if (errorLatest && !report) {
    return (
      <div style={{ padding: 24 }}>
        <div
          style={{
            marginBottom: 24,
            paddingBottom: 16,
            borderBottom: '1px solid #E2E8F0',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <Space size={12}>
            <SafetyCertificateOutlined style={{ fontSize: 22, color: '#0F172A' }} />
            <div>
              <Title level={4} style={{ margin: 0, color: '#0F172A' }}>
                Live Gate
              </Title>
              <Text style={{ fontSize: 13, color: '#64748B' }}>
                实盘信号网关 — 管理从策略信号到实盘执行的完整链路
              </Text>
            </div>
          </Space>
        </div>
        <ErrorState
          message={latestError instanceof Error ? latestError.message : '加载 Gate 检查数据失败'}
          onRetry={() => refetchLatest()}
        />
        <Card style={CARD}>
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Space direction="vertical" size="middle">
              <RunButton onRun={handleRun} loading={runMutation.isPending} />
              {runMutation.data?.data && (
                <Alert
                  type="success"
                  message="检查完成"
                  description={
                    <Text>
                      总体状态:{' '}
                      <Text strong style={{ color: runMutation.data.data.overall === 'READY' ? '#059669' : '#DC2626' }}>
                        {runMutation.data.data.overall}
                      </Text>
                    </Text>
                  }
                  showIcon
                />
              )}
              {runMutation.isError && (
                <Alert
                  type="error"
                  message="检查失败"
                  description={runMutation.error?.message}
                  showIcon
                />
              )}
            </Space>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      {/* ─── Custom Page Header ──────────────────────────── */}
      <div
        style={{
          marginBottom: 24,
          paddingBottom: 16,
          borderBottom: '1px solid #E2E8F0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <Space size={12}>
          <SafetyCertificateOutlined style={{ fontSize: 22, color: '#0F172A' }} />
          <div>
            <Title level={4} style={{ margin: 0, color: '#0F172A' }}>
              Live Gate
            </Title>
            <Text style={{ fontSize: 13, color: '#64748B' }}>
              实盘信号网关 — 管理从策略信号到实盘执行的完整链路
            </Text>
          </div>
        </Space>
        <RunButton onRun={handleRun} loading={runMutation.isPending} />
      </div>

      {/* ─── Loading ─────────────────────────────────────── */}
      {loadingLatest && !report && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 48,
            gap: 16,
          }}
        >
          <Spin size="large" />
          <Text type="secondary" style={{ fontSize: 14 }}>
            正在加载 Gate 检查数据...
          </Text>
        </div>
      )}

      {/* ─── Run mutation feedback ────────────────────────── */}
      {runMutation.isPending && (
        <Alert
          type="info"
          message="正在运行 Gate 检查..."
          description="正在依次执行 13 道门禁检查，请稍候..."
          showIcon
          icon={<ReloadOutlined spin />}
          style={{ marginBottom: 16, borderRadius: 8 }}
        />
      )}
      {runMutation.isError && (
        <Alert
          type="error"
          message="检查执行失败"
          description={runMutation.error?.message}
          showIcon
          closable
          style={{ marginBottom: 16, borderRadius: 8 }}
        />
      )}
      {runMutation.data?.data && !latestResp?.data && (
        <Alert
          type="success"
          message="检查完成"
          description={
            <Text>
              总体状态:{' '}
              <Text strong style={{ color: runMutation.data.data.overall === 'READY' ? '#059669' : '#DC2626' }}>
                {runMutation.data.data.overall}
              </Text>
            </Text>
          }
          showIcon
          style={{ marginBottom: 16, borderRadius: 8 }}
        />
      )}

      {report && (
        <>
          {/* ─── 1. Overall Status ────────────────────────── */}
          <OverallStatusBanner overall={report.overall} report={report} />

          {/* ─── Sidebar + Main Content ───────────────────── */}
          <Row gutter={24}>
            {/* Left: Gate Info */}
            <Col xs={24} lg={6}>
              <GateInfoSidebar report={report} />
              <RunButton onRun={handleRun} loading={runMutation.isPending} />
            </Col>

            {/* Right: Main Content */}
            <Col xs={24} lg={18}>
              {/* ─── Summary Metrics ──────────────────────── */}
              <SummaryMetrics report={report} />

              {/* ─── 3. Blockers ─────────────────────────── */}
              <BlockersSection blockers={report.blockers} />

              {/* ─── 2. Gate Checklist Table ──────────────── */}
              <Card style={CARD}>
                <div style={SECTION_TITLE}>
                  <Space>
                    <ThunderboltOutlined />
                    <span>Gate 检查清单（{report.gates?.length || 0} 道）</span>
                  </Space>
                </div>
                <GateChecklist gates={report.gates || []} />
              </Card>

              {/* ─── 4. History ───────────────────────────── */}
              <HistorySection history={history || []} />

              {/* ─── 5. Approval Records ──────────────────── */}
              <ApprovalRecordsSection />
            </Col>
          </Row>
        </>
      )}
    </div>
  )
}

export default LiveGate
