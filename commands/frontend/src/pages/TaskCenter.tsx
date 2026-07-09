import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Card, Table, Button, Modal, Form, Select, Input, Tag, Space, Typography,
  Alert, Spin, Empty, Descriptions, message, Tooltip, Divider,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, PlayCircleOutlined, CodeOutlined,
  ClockCircleOutlined, FileTextOutlined, BugOutlined, CloseOutlined,
  CheckSquareOutlined,
} from '@ant-design/icons'
import StatusBadge from '../components/common/StatusBadge'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import { useJobs } from '../hooks/useJobs'
import { useJobStream } from '../hooks/useJobStream'
import { API } from '../App'
import { postJobRun, postJobRerun, getJobDetail } from '../api/endpoints'
import type { Job, JobDetail } from '../api/schemas'

const { Text, Title } = Typography
const { TextArea } = Input

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

const TASK_TYPES = [
  { value: 'data_sync', label: '数据同步' },
  { value: 'factor_compute', label: '因子计算' },
  { value: 'backtest', label: '回测' },
  { value: 'report_gen', label: '报告生成' },
  { value: 'maintenance', label: '维护任务' },
  { value: 'data_import', label: '数据导入' },
]

/** Compute duration from created_at / updated_at */
function calcDuration(job: Job): string {
  if (!job.created_at) return '-'
  const start = new Date(job.created_at).getTime()
  if (isNaN(start)) return '-'
  const end = job.updated_at ? new Date(job.updated_at).getTime() : Date.now()
  const ms = Math.max(0, end - start)
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}m ${s}s`
}

/** Format ISO datetime to locale string */
function fmtTime(iso: string | undefined): string {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    return isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function TaskCenter() {
  // ── Job list (10s polling via useJobs) ──
  const { data: result, isLoading, error, refetch } = useJobs()
  // Guard: API may return non-array; antd Table's InternalTable calls .some() on dataSource
  const raw = result?.data
  const jobs: Job[] = Array.isArray(raw) ? raw : []

  // ── Detail modal ──
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  const [detailData, setDetailData] = useState<JobDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  // ── Run job modal ──
  const [runModalOpen, setRunModalOpen] = useState(false)
  const [runLoading, setRunLoading] = useState(false)
  const [runForm] = Form.useForm()

  // ── SSE stream for running job detail ──
  const isRunningDetail = selectedJob?.status === 'running' || detailData?.status === 'running'
  const streamRunId = isRunningDetail && detailModalOpen
    ? (detailData?.run_id || selectedJob?.id || null)
    : null
  const { data: streamData, isConnected } = useJobStream(streamRunId, {
    autoConnect: true, reconnectDelay: 2000, maxRetries: 3,
  })
  const [sseLogs, setSseLogs] = useState<string[]>([])
  const logContainerRef = useRef<HTMLDivElement>(null)

  // Accumulate SSE log lines
  useEffect(() => {
    if (!streamData) return
    if (typeof streamData === 'string') {
      setSseLogs(prev => [...prev, streamData])
    } else if (typeof streamData === 'object' && streamData !== null) {
      const obj = streamData as Record<string, unknown>
      if (obj.stream && obj.line) {
        setSseLogs(prev => [...prev, `[${obj.stream}] ${obj.line}`])
      } else {
        setSseLogs(prev => [...prev, JSON.stringify(obj)])
      }
    }
  }, [streamData])

  // Auto-scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [sseLogs])

  // Clear SSE logs when closing modal or switching job
  useEffect(() => {
    if (!detailModalOpen) {
      setSseLogs([])
    }
  }, [detailModalOpen])

  // ── Handlers ──

  /** Fetch job detail and open modal */
  const showDetail = useCallback(async (job: Job) => {
    setSelectedJob(job)
    setDetailModalOpen(true)
    setDetailLoading(true)
    setDetailError(null)
    setDetailData(null)
    setSseLogs([])
    try {
      const resp = await getJobDetail(job.id)
      if (resp.ok && resp.data) {
        setDetailData(resp.data)
      } else {
        setDetailError(resp.error || '获取任务详情失败')
      }
    } catch (e: unknown) {
      setDetailError(e instanceof Error ? e.message : '网络错误')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  /** Close detail modal */
  const closeDetail = () => {
    setDetailModalOpen(false)
    setSelectedJob(null)
    setDetailData(null)
    setDetailError(null)
    setSseLogs([])
  }

  /** Re-run a job */
  const handleRerun = async (jobId: string) => {
    try {
      const resp = await postJobRerun(jobId)
      if (resp.ok) {
        message.success('任务已重新提交')
        refetch()
        closeDetail()
      } else {
        message.error(resp.error || '重跑失败')
      }
    } catch (e: unknown) {
      message.error('网络错误: ' + (e instanceof Error ? e.message : ''))
    }
  }

  /** Submit new job */
  const handleRunJob = async () => {
    try {
      const values = await runForm.validateFields()
      setRunLoading(true)
      let params: Record<string, unknown> = {}
      if (values.params) {
        try {
          params = JSON.parse(values.params)
        } catch {
          message.error('参数格式错误，请输入有效的 JSON')
          setRunLoading(false)
          return
        }
      }
      const resp = await postJobRun(values.type, params)
      if (resp.ok) {
        message.success('任务已提交')
        setRunModalOpen(false)
        runForm.resetFields()
        refetch()
      } else {
        message.error(resp.error || '提交失败')
      }
    } catch {
      // validation error
    } finally {
      setRunLoading(false)
    }
  }

  // ── Table columns ──
  const columns = [
    {
      title: 'Run ID',
      dataIndex: 'id',
      key: 'id',
      width: 180,
      render: (v: string) => (
        <Tooltip title={v}>
          <code style={{ color: '#2563EB', fontSize: 11 }}>{v.slice(0, 24)}{v.length > 24 ? '…' : ''}</code>
        </Tooltip>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 120,
      render: (v: string) => <Tag color="geekblue">{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: Job['status']) => <StatusBadge status={s} />,
    },
    {
      title: '开始时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (v: string) => (
        <span style={{ color: '#64748B', fontSize: 12 }}>
          <ClockCircleOutlined style={{ marginRight: 4 }} />
          {fmtTime(v)}
        </span>
      ),
    },
    {
      title: '耗时',
      key: 'duration',
      width: 80,
      render: (_: unknown, record: Job) => (
        <Text style={{ fontSize: 12, color: '#64748B' }}>{calcDuration(record)}</Text>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: Job) => (
        <Space size="small">
          <Button size="small" type="primary" ghost onClick={(e) => { e.stopPropagation(); showDetail(record) }}>
            详情
          </Button>
          <Button
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={(e) => { e.stopPropagation(); handleRerun(record.id) }}
          >
            重跑
          </Button>
        </Space>
      ),
    },
  ]

  // ── Render ──
  return (
    <div>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #E2E8F0',
      }}>
        <Title level={4} style={{ margin: 0, color: '#0F172A' }}>
          <CheckSquareOutlined style={{ marginRight: 8, color: '#2563EB' }} />
          任务中心
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setRunModalOpen(true)}>
            新任务
          </Button>
        </Space>
      </div>

      {/* Fetch error banner */}
      {error && (
        <Alert
          type="error"
          message="刷新失败"
          description={error instanceof Error ? error.message : '后台静默刷新失败'}
          showIcon closable
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Loading state (initial only) */}
      {isLoading && jobs.length === 0 ? (
        <LoadingState tip="正在加载任务列表..." />
      ) : /* Empty state */
      jobs.length === 0 ? (
        <Card style={cardStyle}>
          <Empty description="暂无任务记录" image={Empty.PRESENTED_IMAGE_SIMPLE}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setRunModalOpen(true)}>
              运行新任务
            </Button>
          </Empty>
        </Card>
      ) : (
        /* Main table */
        <Card style={cardStyle}>
          <Table
            dataSource={jobs}
            columns={columns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
            locale={{ emptyText: '暂无任务' }}
            onRow={(record) => ({
              style: {
                cursor: 'pointer',
                ...(record.status === 'running' ? { background: '#F0FDF4', borderLeft: '3px solid #22C55E' } : {}),
                ...(record.status === 'failed' ? { borderLeft: '3px solid #FCA5A5' } : {}),
              },
              onClick: () => showDetail(record),
            })}
          />
        </Card>
      )}

      {/* ── Detail Modal ── */}
      <Modal
        title={
          <Space>
            <CodeOutlined style={{ color: '#2563EB' }} />
            <span>任务详情</span>
            {detailData?.run_id && (
              <code style={{ fontSize: 11, color: '#64748B' }}>{detailData.run_id.slice(0, 30)}</code>
            )}
          </Space>
        }
        open={detailModalOpen}
        onCancel={closeDetail}
        footer={null}
        width={900}
        destroyOnClose
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>
        ) : detailError ? (
          <Alert type="error" message="加载详情失败" description={detailError} showIcon
            action={<Button size="small" onClick={() => selectedJob && showDetail(selectedJob)}>重试</Button>}
          />
        ) : detailData ? (
          <div>
            {/* Status bar */}
            <div style={{ display: 'flex', gap: 24, marginBottom: 20, flexWrap: 'wrap' }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>状态</Text>
                <div style={{ marginTop: 4 }}><StatusBadge status={detailData.status} /></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>类型</Text>
                <div style={{ marginTop: 4 }}><Tag color="geekblue">{detailData.type}</Tag></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>开始时间</Text>
                <div style={{ marginTop: 4 }}>
                  <Text style={{ fontSize: 13 }}>{fmtTime(detailData.created_at)}</Text>
                </div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>耗时</Text>
                <div style={{ marginTop: 4 }}>
                  <Text style={{ fontSize: 13 }}>{detailData.duration || calcDuration(detailData)}</Text>
                </div>
              </div>
            </div>

            {/* Input parameters */}
            {/* @ts-expect-error: Divider orientation type mismatch */}
            <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13, color: '#64748B' }}>
              <CodeOutlined /> 输入参数
            </Divider>
            <pre style={{
              background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8,
              padding: 12, fontSize: 12, maxHeight: 200, overflow: 'auto',
              color: '#334155', marginBottom: 16,
            }}>
              {JSON.stringify(detailData.params || {}, null, 2)}
            </pre>

            {/* Running logs: stdout + stderr */}
            {/* @ts-expect-error: Divider orientation type mismatch */}
            <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13, color: '#64748B' }}>
              <FileTextOutlined /> 运行日志
              {isConnected && (
                <Tag color="processing" style={{ marginLeft: 8, fontSize: 10, lineHeight: '16px' }}>
                  实时
                </Tag>
              )}
            </Divider>

            {/* Stdout */}
            {detailData.stdout_tail && detailData.stdout_tail.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 11, color: '#059669' }}>stdout:</Text>
                <pre style={{
                  background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6,
                  padding: 8, fontSize: 11, maxHeight: 150, overflow: 'auto',
                  color: '#334155', marginTop: 4,
                }}>
                  {detailData.stdout_tail.join('\n')}
                </pre>
              </div>
            )}

            {/* Stderr */}
            {detailData.stderr_tail && detailData.stderr_tail.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 11, color: '#DC2626' }}>stderr:</Text>
                <pre style={{
                  background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 6,
                  padding: 8, fontSize: 11, maxHeight: 150, overflow: 'auto',
                  color: '#991B1B', marginTop: 4,
                }}>
                  {detailData.stderr_tail.join('\n')}
                </pre>
              </div>
            )}

            {/* SSE live logs (running jobs) */}
            {isRunningDetail && (
              <div style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 11, color: '#2563EB' }}>
                  📡 实时日志 {isConnected ? '(已连接)' : '(重连中...)'}
                </Text>
                <div
                  ref={logContainerRef}
                  style={{
                    background: '#1E293B', border: '1px solid #334155', borderRadius: 6,
                    padding: 8, fontSize: 11, maxHeight: 200, overflow: 'auto',
                    color: '#E2E8F0', fontFamily: "'Fira Code', 'Consolas', monospace",
                    marginTop: 4, lineHeight: 1.6,
                  }}
                >
                  {sseLogs.length === 0 ? (
                    <span style={{ color: '#64748B' }}>等待日志...</span>
                  ) : (
                    sseLogs.map((line, i) => <div key={i}>{line}</div>)
                  )}
                </div>
              </div>
            )}

            {/* Artifacts */}
            {detailData.artifacts && detailData.artifacts.length > 0 && (
              <>
                {/* @ts-expect-error: Divider orientation type mismatch */}
                <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13, color: '#64748B' }}>
                  <FileTextOutlined /> 输出 Artifacts
                </Divider>
                <div style={{ marginBottom: 16 }}>
                  {detailData.artifacts.map((a, i) => (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 10px', background: '#F8FAFC', borderRadius: 6,
                      border: '1px solid #E2E8F0', marginBottom: 4,
                    }}>
                      <FileTextOutlined style={{ color: '#2563EB' }} />
                      <Text style={{ fontSize: 13 }}>{a.name}</Text>
                      {a.size !== undefined && (
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          ({(a.size / 1024).toFixed(1)} KB)
                        </Text>
                      )}
                      <code style={{ fontSize: 10, color: '#64748B', marginLeft: 'auto' }}>{a.path}</code>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Error details */}
            {(detailData.error || detailData.status === 'failed') && (
              <>
                {/* @ts-expect-error: Divider orientation type mismatch */}
                <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13, color: '#DC2626' }}>
                  <BugOutlined /> 错误详情
                </Divider>
                <Alert
                  type="error"
                  message={detailData.error || '任务执行失败'}
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              </>
            )}

            {/* Bottom actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
              {detailData.status === 'failed' && (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleRerun(detailData.id)}
                >
                  重跑
                </Button>
              )}
              {detailData.status === 'completed' && (
                <Button
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleRerun(detailData.id)}
                >
                  再次运行
                </Button>
              )}
              <Button onClick={closeDetail}>关闭</Button>
            </div>
          </div>
        ) : (
          <Empty description="无数据" />
        )}
      </Modal>

      {/* ── Run Job Modal ── */}
      <Modal
        title={
          <Space>
            <PlusOutlined style={{ color: '#2563EB' }} />
            <span>运行新任务</span>
          </Space>
        }
        open={runModalOpen}
        onCancel={() => { setRunModalOpen(false); runForm.resetFields() }}
        footer={null}
        width={520}
        destroyOnClose
      >
        <Form form={runForm} layout="vertical" initialValues={{ type: undefined, params: '' }}>
          <Form.Item name="type" label="任务类型" rules={[{ required: true, message: '请选择任务类型' }]}>
            <Select placeholder="选择任务类型" options={TASK_TYPES} />
          </Form.Item>
          <Form.Item
            name="params"
            label={
              <span>
                参数 <Text type="secondary" style={{ fontSize: 11 }}>(JSON 格式，可选)</Text>
              </span>
            }
          >
            <TextArea
              rows={6}
              placeholder='{"key": "value"}'
              style={{ fontFamily: "'Fira Code', 'Consolas', monospace", fontSize: 12 }}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => { setRunModalOpen(false); runForm.resetFields() }}>取消</Button>
              <Button type="primary" loading={runLoading} onClick={handleRunJob} icon={<PlayCircleOutlined />}>
                运行
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
