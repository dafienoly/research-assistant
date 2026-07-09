import { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Table, Tag, Button, Spin, Alert, Typography, Tabs, Space, Statistic, Empty, Modal, message, Descriptions, Progress } from 'antd'
import {
  DashboardOutlined, ReloadOutlined, PlayCircleOutlined, StopOutlined, SyncOutlined,
  CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined, BugOutlined,
  ApiOutlined, CloudServerOutlined, ThunderboltOutlined, ExperimentOutlined,
  CodeOutlined, ToolOutlined, FileProtectOutlined, InfoCircleOutlined,
  WarningOutlined
} from '@ant-design/icons'
import { API } from '../App'
import StatusDot from '../components/common/StatusDot'

const { Title, Text } = Typography

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }
const statCard = (color) => ({ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, borderLeft: `4px solid ${color}`, marginBottom: 16 })

const SERVICE_ICONS = {
  dashboard: <ApiOutlined />,
  'auto-loop': <SyncOutlined />,
  'agent-runner': <CloudServerOutlined />,
  mcp: <ExperimentOutlined />,
  vite: <CodeOutlined />,
}

const RUNNING_CONFIG = {
  true: { color: 'success', icon: <CheckCircleOutlined />, label: '运行中', dot: '#059669', bg: '#D1FAE5', text: '#059669' },
  false: { color: 'error', icon: <CloseCircleOutlined />, label: '已停止', dot: '#DC2626', bg: '#FEE2E2', text: '#DC2626' },
}

const STATUS_CONFIG = {
  healthy: { color: 'success', icon: <CheckCircleOutlined />, label: '健康', dot: '#059669' },
  degraded: { color: 'warning', icon: <WarningOutlined />, label: '降级', dot: '#D97706' },
  critical: { color: 'error', icon: <CloseCircleOutlined />, label: '危急', dot: '#DC2626' },
  warning: { color: 'warning', icon: <WarningOutlined />, label: '警告', dot: '#D97706' },
  unknown: { color: 'default', icon: <MinusCircleOutlined />, label: '未知', dot: '#94A3B8' },
}

const STATUS_DOT_MAP = {
  healthy: 'running',
  degraded: 'warning',
  critical: 'error',
  warning: 'warning',
  unknown: 'idle',
}

export default function OpsCenter() {
  const [health, setHealth] = useState(null)
  const [diagnostics, setDiagnostics] = useState(null)
  const [ports, setPorts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [actionLoading, setActionLoading] = useState({})
  const [diagLoading, setDiagLoading] = useState(false)
  const [backupLoading, setBackupLoading] = useState(false)
  const [backupResult, setBackupResult] = useState(null)
  const [logModal, setLogModal] = useState({ visible: false, serviceId: null, logs: [] })

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [h, p] = await Promise.all([
        fetch(`${API}/api/ops/health`).then(r => r.json()),
        fetch(`${API}/api/ops/ports`).then(r => r.json()),
      ])
      setHealth(h)
      setPorts(p?.ports || [])
    } catch (e) {
      setError(e?.message || '加载运维中心失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDiagnostics = async () => {
    setDiagLoading(true)
    try {
      const d = await fetch(`${API}/api/ops/diagnostics`).then(r => r.json())
      setDiagnostics(d)
    } catch (e) {
      message.error('诊断加载失败: ' + (e?.message || String(e)))
    } finally {
      setDiagLoading(false)
    }
  }

  const doBackup = async () => {
    setBackupLoading(true)
    setBackupResult(null)
    try {
      const r = await fetch(`${API}/api/ops/backup`, { method: 'POST' }).then(r => r.json())
      setBackupResult(r)
      if (r.success) {
        message.success('备份成功')
      } else {
        message.warning('备份部分失败')
      }
    } catch (e) {
      message.error('备份失败: ' + (e?.message || String(e)))
    } finally {
      setBackupLoading(false)
    }
  }

  const serviceAction = async (serviceId, action) => {
    const key = `${serviceId}:${action}`
    setActionLoading(prev => ({ ...prev, [key]: true }))
    try {
      const r = await fetch(`${API}/api/ops/${action}/${serviceId}`, { method: 'POST' }).then(r => r.json())
      if (r.success) {
        message.success(r.message || `${action} ${serviceId} 成功`)
      } else {
        message.warning(r.error || `${action} ${serviceId} 返回异常`)
      }
      load()
    } catch (e) {
      message.error(`${action} ${serviceId} 失败: ${e?.message || String(e)}`)
    } finally {
      setActionLoading(prev => ({ ...prev, [key]: false }))
    }
  }

  const showLogs = (serviceId, logs) => {
    setLogModal({ visible: true, serviceId, logs: logs || [] })
  }

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 15000); return () => clearInterval(t) }, [load])

  // ── Loading / Error ──
  if (loading && !health) {
    return <Spin style={{ display: 'block', marginTop: 80 }} />
  }

  if (error && !health) {
    return <Alert message="加载失败" description={error} type="error" showIcon style={{ margin: 24 }} />
  }

  const overallCfg = STATUS_CONFIG[health?.overall] || STATUS_CONFIG.unknown
  const services = health?.services || {}
  const nServices = health?.n_services || 0
  const nRunning = health?.n_running || 0

  // ── Tab items ──
  const tabItems = [
    {
      key: 'overview',
      label: <span><DashboardOutlined /> 概览</span>,
      children: renderOverview(),
    },
    {
      key: 'services',
      label: <span><CloudServerOutlined /> 服务管理</span>,
      children: renderServices(),
    },
    {
      key: 'ports',
      label: <span><ApiOutlined /> 端口</span>,
      children: renderPorts(),
    },
    {
      key: 'diagnostics',
      label: <span><BugOutlined /> 诊断</span>,
      children: renderDiagnostics(),
    },
    {
      key: 'backup',
      label: <span><FileProtectOutlined /> 备份</span>,
      children: renderBackup(),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0, color: '#0F172A' }}>
          <ToolOutlined style={{ marginRight: 8, color: '#2563EB' }} />
          运维中心
        </Title>
        <Space>
          <Tag color={overallCfg.color} style={{ padding: '2px 12px', borderRadius: 12, fontSize: 13 }}>
            {overallCfg.icon} {overallCfg.label}
          </Tag>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        </Space>
      </div>

      {error && <Alert message={error} type="error" showIcon closable style={{ marginBottom: 16 }} />}

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />

      {/* Log Modal */}
      <Modal
        title={`日志: ${logModal.serviceId}`}
        open={logModal.visible}
        onCancel={() => setLogModal({ visible: false, serviceId: null, logs: [] })}
        footer={null}
        width={800}
      >
        <pre style={{
          background: '#1E293B', color: '#E2E8F0', padding: 16, borderRadius: 8,
          fontSize: 12, maxHeight: 500, overflow: 'auto', whiteSpace: 'pre-wrap',
          fontFamily: "'Fira Code', 'Consolas', monospace", lineHeight: 1.6,
        }}>
          {logModal.logs.length > 0
            ? logModal.logs.map((l, i) => <div key={i}>{l}</div>)
            : '(暂无日志)'}
        </pre>
      </Modal>
    </div>
  )

  // ── Overview tab ──
  function renderOverview() {
    const h = health || {}

    return (
      <div>
        {/* Stats */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#2563EB')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>整体状态</Text>}
                value={overallCfg.label}
                prefix={<span><StatusDot status={STATUS_DOT_MAP[health?.overall] || 'idle'} size={10} /> {overallCfg.icon}</span>}
                valueStyle={{ color: overallCfg.dot, fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#059669')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>服务总数</Text>}
                value={nServices}
                prefix={<CloudServerOutlined />}
                valueStyle={{ color: '#059669', fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard(nRunning === nServices ? '#059669' : '#D97706')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>运行中</Text>}
                value={`${nRunning}/${nServices}`}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: nRunning === nServices ? '#059669' : '#D97706', fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#2563EB')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>Python 环境</Text>}
                value={h.venv_python?.split('/').pop() || '?'}
                prefix={<CodeOutlined />}
                valueStyle={{ color: '#2563EB', fontSize: 16, fontWeight: 600 }}
              />
            </Card>
          </Col>
        </Row>

        {/* Service Cards */}
        <Title level={5} style={{ marginTop: 24, marginBottom: 12, color: '#0F172A' }}>服务状态</Title>
        <Row gutter={[16, 16]}>
          {Object.entries(services).map(([sid, s]) => {
            const runCfg = RUNNING_CONFIG[s.running ? 'true' : 'false']
            return (
              <Col xs={24} sm={12} lg={8} key={sid}>
                <Card
                  hoverable
                  style={{
                    ...cardStyle,
                    borderLeft: `4px solid ${runCfg.dot}`,
                    cursor: 'default',
                  }}
                  styles={{ body: { padding: '16px 20px' } }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ fontSize: 24, marginBottom: 4 }}>
                        {SERVICE_ICONS[sid] || <CloudServerOutlined />}
                      </div>
                      <Text strong style={{ fontSize: 14, color: '#0F172A', display: 'block' }}>
                        {s.name_zh}
                      </Text>
                      <Text style={{ fontSize: 11, color: '#64748B' }}>{s.name}</Text>
                    </div>
                    <Tag color={runCfg.color} style={{ border: 'none', borderRadius: 12 }}>
                      <StatusDot status={s.running ? 'running' : 'error'} size={7} /> {runCfg.label}
                    </Tag>
                  </div>
                  {s.port && (
                    <div style={{ marginTop: 8 }}>
                      <Text style={{ fontSize: 12, color: '#64748B' }}>端口: {s.port}</Text>
                    </div>
                  )}
                </Card>
              </Col>
            )
          })}
        </Row>
      </div>
    )
  }

  // ── Services tab ──
  function renderServices() {
    const svcEntries = Object.entries(services)
    if (!svcEntries.length) {
      return <Card style={cardStyle}><Empty description="暂无服务数据" image={Empty.PRESENTED_IMAGE_SIMPLE} /></Card>
    }

    const cols = [
      {
        title: '服务', dataIndex: 'id', key: 'id', width: 100,
        render: (v) => (
          <Space>
            {SERVICE_ICONS[v] || <CloudServerOutlined />}
            <Text strong>{services[v]?.name_zh || v}</Text>
          </Space>
        ),
      },
      {
        title: '标识', dataIndex: 'id', key: 'id2', width: 120,
        render: (v) => <code style={{ color: '#2563EB', fontSize: 11 }}>{v}</code>,
      },
      {
        title: '状态', dataIndex: 'running', key: 'running', width: 90,
        render: (v) => {
          const cfg = RUNNING_CONFIG[v ? 'true' : 'false']
          return <Tag color={cfg.color} style={{ border: 'none', borderRadius: 12 }}><StatusDot status={v ? 'running' : 'error'} size={7} /> {cfg.label}</Tag>
        },
      },
      {
        title: '端口', dataIndex: 'port', key: 'port', width: 60,
        render: (v) => v ? <Text style={{ fontSize: 12 }}>{v}</Text> : '-',
      },
      {
        title: '检测来源', dataIndex: 'detected_by', key: 'detected_by', width: 80,
        render: (v) => {
          const map = { pid: 'PID', port: '端口', cron: 'Cron', none: '无' }
          return <Tag color="geekblue">{map[v] || v}</Tag>
        },
      },
      {
        title: '操作', key: 'actions', width: 240,
        render: (_, record) => {
          const sid = record.id
          const isRunning = record.running
          return (
            <Space size="small">
              <Button
                size="small"
                type="primary"
                icon={<PlayCircleOutlined />}
                disabled={isRunning}
                loading={actionLoading[`${sid}:start`]}
                onClick={() => serviceAction(sid, 'start')}
              >
                启动
              </Button>
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                disabled={!isRunning}
                loading={actionLoading[`${sid}:stop`]}
                onClick={() => serviceAction(sid, 'stop')}
              >
                停止
              </Button>
              <Button
                size="small"
                icon={<SyncOutlined />}
                loading={actionLoading[`${sid}:restart`]}
                onClick={() => serviceAction(sid, 'restart')}
              >
                重启
              </Button>
              <Button
                size="small"
                type="text"
                icon={<InfoCircleOutlined />}
                onClick={() => showLogs(sid, record.log_tail)}
              >
                日志
              </Button>
            </Space>
          )
        },
      },
    ]

    const dataSource = svcEntries.map(([sid, s]) => ({ ...s, id: sid, key: sid }))

    return (
      <Card style={cardStyle} title={<Space><CloudServerOutlined style={{ color: '#2563EB' }} /> 服务管理</Space>}>
        <Table
          dataSource={dataSource}
          columns={cols}
          size="small"
          pagination={false}
        />
      </Card>
    )
  }

  // ── Ports tab ──
  function renderPorts() {
    const portCols = [
      { title: '服务', dataIndex: 'service', key: 'service', width: 120,
        render: (v) => <Text strong>{v}</Text> },
      { title: '服务名', dataIndex: 'service_name', key: 'service_name', width: 120 },
      { title: '端口', dataIndex: 'port', key: 'port', width: 80,
        render: (v) => <code style={{ fontSize: 13 }}>{v}</code> },
      { title: '状态', dataIndex: 'in_use', key: 'in_use', width: 80,
        render: (v) => v
          ? <Tag color="error" icon={<CheckCircleOutlined />}>占用中</Tag>
          : <Tag icon={<MinusCircleOutlined />}>空闲</Tag> },
      { title: 'PID', dataIndex: 'pid', key: 'pid', width: 80,
        render: (v) => v ? <code>{v}</code> : '-' },
      { title: '进程', dataIndex: 'process_name', key: 'process_name', width: 120 },
    ]

    return (
      <Card style={cardStyle} title={<Space><ApiOutlined style={{ color: '#2563EB' }} /> 端口占用扫描</Space>}>
        {ports.length === 0
          ? <Empty description="无端口数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          : <Table dataSource={ports} columns={portCols} rowKey="port" size="small" pagination={false} />
        }
      </Card>
    )
  }

  // ── Diagnostics tab ──
  function renderDiagnostics() {
    const d = diagnostics || {}

    return (
      <div>
        <div style={{ marginBottom: 16 }}>
          <Button
            type="primary"
            icon={<BugOutlined />}
            onClick={loadDiagnostics}
            loading={diagLoading}
          >
            运行全面诊断
          </Button>
        </div>

        {!diagnostics && !diagLoading && (
          <Card style={cardStyle}>
            <Empty description="点击「运行全面诊断」查看系统状态" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          </Card>
        )}

        {diagLoading && <Spin style={{ display: 'block', marginTop: 40 }} />}

        {diagnostics && (
          <div>
            {/* System Info */}
            <Card style={cardStyle} title={<span><InfoCircleOutlined style={{ color: '#2563EB' }} /> 系统信息</span>}>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="时间">{d.timestamp}</Descriptions.Item>
                <Descriptions.Item label="主机名">{d.hostname}</Descriptions.Item>
                <Descriptions.Item label="系统">{d.system?.platform || '?'}</Descriptions.Item>
                <Descriptions.Item label="Python">{d.system?.python?.split(' ')[0] || '?'}</Descriptions.Item>
                <Descriptions.Item label="虚拟环境" span={2}>
                  <Tag color={d.venv?.exists ? 'success' : 'error'}>
                    {d.venv?.exists ? '✅ 正常' : '❌ 缺失'}
                  </Tag>
                  <Text style={{ fontSize: 11, color: '#64748B', marginLeft: 8 }}>{d.venv?.path || '?'}</Text>
                </Descriptions.Item>
              </Descriptions>
            </Card>

            {/* Disk & Memory */}
            <Row gutter={16}>
              <Col xs={24} lg={12}>
                <Card style={cardStyle} title={<span><CloudServerOutlined style={{ color: '#2563EB' }} /> 磁盘</span>}>
                  {d.disk?.status
                    ? <div>
                        <Progress
                          percent={d.disk.usage_pct}
                          status={d.disk.status === 'critical' ? 'exception' : d.disk.status === 'warning' ? 'active' : 'success'}
                          format={() => `${d.disk.usage_pct}%`}
                        />
                        <Descriptions size="small" style={{ marginTop: 12 }}>
                          <Descriptions.Item label="总容量">{d.disk.total_gb} GB</Descriptions.Item>
                          <Descriptions.Item label="已用">{d.disk.used_gb} GB</Descriptions.Item>
                          <Descriptions.Item label="可用">{d.disk.free_gb} GB</Descriptions.Item>
                        </Descriptions>
                      </div>
                    : <Empty description="磁盘信息不可用" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  }
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card style={cardStyle} title={<span><ThunderboltOutlined style={{ color: '#2563EB' }} /> 内存</span>}>
                  {d.memory?.status
                    ? <div>
                        <Progress
                          percent={d.memory.usage_pct}
                          status={d.memory.status === 'critical' ? 'exception' : d.memory.status === 'warning' ? 'active' : 'success'}
                          format={() => `${d.memory.usage_pct}%`}
                        />
                        <Descriptions size="small" style={{ marginTop: 12 }}>
                          <Descriptions.Item label="总量">{d.memory.total_gb} GB</Descriptions.Item>
                          <Descriptions.Item label="可用">{d.memory.available_gb} GB</Descriptions.Item>
                        </Descriptions>
                      </div>
                    : <Empty description="内存信息不可用 (需 psutil)" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  }
                </Card>
              </Col>
            </Row>

            {/* Python Dependencies */}
            <Card style={cardStyle} title={<span><CodeOutlined style={{ color: '#2563EB' }} /> Python 依赖</span>}>
              <Row gutter={[16, 16]}>
                {(d.python_deps || []).map(dep => (
                  <Col key={dep.name}>
                    <Card size="small" style={{
                      border: `1px solid ${dep.available ? '#D1FAE5' : '#FEE2E2'}`,
                      borderRadius: 8, minWidth: 120, textAlign: 'center',
                    }}>
                      <Text strong style={{ display: 'block', marginBottom: 4 }}>{dep.name}</Text>
                      <Tag color={dep.available ? 'success' : 'error'}>
                        {dep.available ? '✅' : '❌'}
                      </Tag>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>

            {/* Git Status */}
            {d.git && (
              <Card style={cardStyle} title="Git 状态">
                <Descriptions size="small">
                  <Descriptions.Item label="未提交变更">
                    <Tag color={d.git.has_changes ? 'warning' : 'success'}>
                      {d.git.has_changes ? `有 ${d.git.changed_files} 个文件` : '干净'}
                    </Tag>
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            )}

            {/* Workspace */}
            <Card style={cardStyle} title="工作目录">
              <Row gutter={[16, 16]}>
                {[
                  { label: 'CLI', key: 'cli_exists' },
                  { label: 'Scripts', key: 'scripts_dir_exists' },
                  { label: '前端构建', key: 'frontend_dist_exists' },
                  { label: 'Factor Lab', key: 'factor_lab_exists' },
                ].map(check => (
                  <Col key={check.key}>
                    <Tag color={d.workspace?.[check.key] ? 'success' : 'error'}>
                      {check.label}: {d.workspace?.[check.key] ? '✅' : '❌'}
                    </Tag>
                  </Col>
                ))}
              </Row>
            </Card>

            {/* Cron */}
            <Card style={cardStyle} title="Cron 状态">
              <Tag color={d.cron?.registered ? 'success' : 'default'}>
                {d.cron?.registered ? '✅ 已注册' : '❌ 未发现 Hermes cron 任务'}
              </Tag>
            </Card>
          </div>
        )}
      </div>
    )
  }

  // ── Backup tab ──
  function renderBackup() {
    return (
      <div>
        <Card style={cardStyle} title={<span><FileProtectOutlined style={{ color: '#2563EB' }} /> 一键备份</span>}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Button
              type="primary"
              icon={<FileProtectOutlined />}
              onClick={doBackup}
              loading={backupLoading}
              size="large"
            >
              执行备份
            </Button>
            <Text style={{ color: '#64748B', fontSize: 12 }}>
              备份内容包括: 路线图状态、配置文件、服务日志
            </Text>
          </Space>
        </Card>

        {backupResult && (
          <Card style={cardStyle} title="备份结果">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="时间">{backupResult.timestamp}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={backupResult.success ? 'success' : 'error'}>
                  {backupResult.success ? '成功' : '部分失败'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
            <div style={{ borderTop: '1px solid #E2E8F0', margin: '12px 0' }} />
            {Object.entries(backupResult.results || {}).map(([key, val]) => (
              <div key={key} style={{ marginBottom: 8 }}>
                <Tag color={val.success ? 'success' : 'error'} style={{ marginRight: 8 }}>
                  {val.success ? '✅' : '❌'}
                </Tag>
                <Text strong>{key}</Text>
                {val.backup_id && <Text style={{ marginLeft: 8, fontSize: 12, color: '#64748B' }}>ID: {val.backup_id}</Text>}
                {val.path && <Text style={{ marginLeft: 8, fontSize: 12, color: '#64748B' }}>{val.path}</Text>}
                {val.error && <Text style={{ marginLeft: 8, fontSize: 12, color: '#DC2626' }}>{val.error}</Text>}
              </div>
            ))}
          </Card>
        )}
      </div>
    )
  }
}
