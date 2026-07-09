import { useState, useEffect, type FC, type ReactNode } from 'react'
import { Card, Row, Col, Table, Tag, Button, Spin, Alert, Typography, Tabs, Space, Statistic,
  Form, Input, Select, Divider, Modal, message, Timeline, Empty, Badge, Tooltip, Popconfirm } from 'antd'
import {
  CommentOutlined, PlusOutlined, ReloadOutlined, BugOutlined, BulbOutlined,
  QuestionCircleOutlined, RocketOutlined, BarsOutlined, DeleteOutlined,
  CheckCircleOutlined, CloseCircleOutlined, HistoryOutlined, InfoCircleOutlined,
  MessageOutlined, EditOutlined, FilterOutlined
} from '@ant-design/icons'
import { API } from '../App'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const cardStyle: React.CSSProperties = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }
const statCard = (color: string): React.CSSProperties => ({ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, borderLeft: `4px solid ${color}`, marginBottom: 16 })

// ─── Types ────────────────────────────────────────────────────────
interface FeedbackItem {
  id: string
  category: string
  title: string
  status: string
  user_name?: string
  created_at?: string
  comments?: Array<{ id: string; user?: string; text: string; created_at?: string }>
}

interface FeedbackStats {
  total: number
  by_category?: Record<string, number>
}

interface FeedbackDetail extends FeedbackItem {
  content?: string
  contact?: string
}

interface CategoryConfig {
  color: string
  label: string
  icon: ReactNode
  bg: string
}

interface StatusConfig {
  color: string
  label: string
  icon: ReactNode
  bg: string
  dot: string
}

const CATEGORY_CONFIG: Record<string, CategoryConfig> = {
  bug:         { color: '#DC2626', label: '🐛 缺陷',     icon: <BugOutlined />,       bg: '#FEE2E2' },
  feature:     { color: '#7C3AED', label: '✨ 功能请求', icon: <RocketOutlined />,    bg: '#EDE9FE' },
  improvement: { color: '#2563EB', label: '📈 改进建议', icon: <BulbOutlined />,     bg: '#DBEAFE' },
  question:    { color: '#D97706', label: '❓ 疑问',     icon: <QuestionCircleOutlined />, bg: '#FEF3C7' },
  other:       { color: '#64748B', label: '📝 其他',     icon: <InfoCircleOutlined />,    bg: '#F1F5F9' },
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  new:           { color: 'default',   label: '新建',       icon: <InfoCircleOutlined />,       bg: '#F1F5F9', dot: '#64748B' },
  acknowledged:  { color: 'processing', label: '已确认',    icon: <MessageOutlined />,          bg: '#DBEAFE', dot: '#2563EB' },
  in_progress:   { color: 'warning',   label: '处理中',    icon: <EditOutlined />,             bg: '#FEF3C7', dot: '#D97706' },
  resolved:      { color: 'success',   label: '已解决',    icon: <CheckCircleOutlined />,      bg: '#D1FAE5', dot: '#059669' },
  closed:        { color: 'default',   label: '已关闭',    icon: <CloseCircleOutlined />,      bg: '#F3F4F6', dot: '#9CA3AF' },
}

const categoryOptions = Object.entries(CATEGORY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))

const Feedback: FC = () => {
  const [items, setItems] = useState<FeedbackItem[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<FeedbackStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [filterCategory, setFilterCategory] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  // Submit form
  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  // Detail
  const [detail, setDetail] = useState<FeedbackDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Comment
  const [commentText, setCommentText] = useState('')
  const [commentUser, setCommentUser] = useState('')
  const [commenting, setCommenting] = useState(false)

  // Status update
  const [statusUpdating, setStatusUpdating] = useState(false)

  const fetchItems = async () => {
    setLoading(true)
    setError(null)
    try {
      let url = `${API}/api/feedback?limit=200&offset=0`
      if (filterCategory) url += `&category=${filterCategory}`
      if (filterStatus) url += `&status=${filterStatus}`
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d: { items?: FeedbackItem[]; total?: number } = await r.json()
      setItems(d.items || [])
      setTotal(d.total || 0)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const r = await fetch(`${API}/api/feedback/stats`)
      setStats(await r.json() as FeedbackStats)
    } catch { /* ignore */ }
  }

  useEffect(() => { fetchItems(); fetchStats() }, [])
  useEffect(() => { fetchItems() }, [filterCategory, filterStatus])

  // ── Submit ──
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      const r = await fetch(`${API}/api/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      message.success('反馈已提交，感谢！')
      setSubmitOpen(false)
      form.resetFields()
      fetchItems()
      fetchStats()
    } catch (e: unknown) {
      if (e instanceof Error) message.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  // ── Detail ──
  const openDetail = async (fid: string) => {
    setDetailLoading(true)
    setDetail(null)
    try {
      const r = await fetch(`${API}/api/feedback/${fid}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setDetail(await r.json() as FeedbackDetail)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDetail = () => setDetail(null)

  // ── Comment ──
  const addComment = async () => {
    if (!commentText.trim() || !detail) return
    setCommenting(true)
    try {
      const r = await fetch(`${API}/api/feedback/${detail.id}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: commentUser || 'anonymous', text: commentText }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setCommentText('')
      message.success('评论已添加')
      const dr = await fetch(`${API}/api/feedback/${detail.id}`)
      setDetail(await dr.json() as FeedbackDetail)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setCommenting(false)
    }
  }

  // ── Status update ──
  const updateItemStatus = async (fid: string, newStatus: string) => {
    setStatusUpdating(true)
    try {
      const r = await fetch(`${API}/api/feedback/${fid}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      message.success(`状态已更新为: ${STATUS_CONFIG[newStatus]?.label || newStatus}`)
      const dr = await fetch(`${API}/api/feedback/${fid}`)
      setDetail(await dr.json() as FeedbackDetail)
      fetchItems()
      fetchStats()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setStatusUpdating(false)
    }
  }

  // ── Delete ──
  const deleteItem = async (fid: string) => {
    try {
      const r = await fetch(`${API}/api/feedback/${fid}`, { method: 'DELETE' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      message.success('反馈已删除')
      if (detail?.id === fid) setDetail(null)
      fetchItems()
      fetchStats()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : String(e))
    }
  }

  // ── Columns ──
  const cols = [
    { title: '分类', dataIndex: 'category', key: 'cat', width: 80,
      render: (v: string) => {
        const cfg = CATEGORY_CONFIG[v]
        return cfg ? <Tag color={cfg.color} style={{ fontSize: 11 }}>{cfg.label}</Tag> : v
      }
    },
    { title: '标题', dataIndex: 'title', key: 't', ellipsis: true,
      render: (v: string, r: FeedbackItem) => <a onClick={() => openDetail(r.id)} style={{ color: '#2563EB' }}>{v}</a>
    },
    { title: '状态', dataIndex: 'status', key: 's', width: 80,
      render: (v: string) => {
        const cfg = STATUS_CONFIG[v]
        return cfg ? <Tag color={cfg.color}>{cfg.label}</Tag> : <Tag>{v}</Tag>
      }
    },
    { title: '提交人', dataIndex: 'user_name', key: 'u', width: 80, render: (v?: string) => v || '-' },
    { title: '时间', dataIndex: 'created_at', key: 'c', width: 110,
      render: (v?: string) => v?.slice(0, 16).replace('T', ' ')
    },
    { title: '评论', key: 'cmt', width: 50,
      render: (_: unknown, r: FeedbackItem) => r.comments?.length
        ? <Badge count={r.comments.length} size="small" style={{ backgroundColor: '#2563EB' }} />
        : <span style={{ color: '#94A3B8' }}>0</span>
    },
    { title: '操作', key: 'act', width: 60,
      render: (_: unknown, r: FeedbackItem) => (
        <Space>
          <Popconfirm title="确定删除？" onConfirm={() => deleteItem(r.id)} okText="删除" cancelText="取消">
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  const statusOptions = Object.entries(STATUS_CONFIG).map(([k, v]) => ({
    value: k, label: v.label
  }))

  // ── Render ──
  return <div>
    {/* Header */}
    <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
      <Col>
        <Title level={4} style={{ margin: 0, color: '#0F172A' }}>
          <CommentOutlined /> 用户反馈
        </Title>
        <Text style={{ color: '#64748B', fontSize: 13 }}>提交问题、建议或功能请求 — {total} 条反馈</Text>
      </Col>
      <Col>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => { fetchItems(); fetchStats() }}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setSubmitOpen(true)}>提交反馈</Button>
        </Space>
      </Col>
    </Row>

    {/* Stats */}
    {stats && <Row gutter={12} style={{ marginBottom: 16 }}>
      <Col span={4}>
        <div style={statCard('#0F172A')}>
          <div style={{ color: '#64748B', fontSize: 12 }}>总计</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{stats.total}</div>
        </div>
      </Col>
      {Object.entries(CATEGORY_CONFIG).map(([k, v]) => (
        <Col span={4} key={k}>
          <div style={statCard(v.color)}>
            <div style={{ color: '#64748B', fontSize: 12 }}>{v.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: v.color }}>
              {stats.by_category?.[k] || 0}
            </div>
          </div>
        </Col>
      ))}
    </Row>}

    {/* Filters */}
    <Row gutter={12} style={{ marginBottom: 12 }}>
      <Col span={6}>
        <Select
          placeholder="按分类过滤"
          allowClear
          value={filterCategory || undefined}
          onChange={v => setFilterCategory(v || '')}
          style={{ width: '100%' }}
          options={categoryOptions}
        />
      </Col>
      <Col span={6}>
        <Select
          placeholder="按状态过滤"
          allowClear
          value={filterStatus || undefined}
          onChange={v => setFilterStatus(v || '')}
          style={{ width: '100%' }}
          options={statusOptions}
        />
      </Col>
      <Col span={12}>
        <Text style={{ color: '#94A3B8', fontSize: 12, lineHeight: '32px' }}>
          {filterCategory || filterStatus ? `已过滤 — 显示 ${items.length}/${total} 条` : ''}
        </Text>
      </Col>
    </Row>

    {/* List */}
    <Card style={cardStyle}>
      {loading
        ? <Spin style={{ display: 'block', marginTop: 40 }} />
        : error
        ? <Alert message="加载失败" description={error} type="error" showIcon />
        : <Table dataSource={items} columns={cols} rowKey="id" size="small"
            pagination={{ pageSize: 15, showTotal: (t: number) => `共 ${t} 条` }}
            locale={{ emptyText: <Empty description="暂无反馈" /> }} />
      }
    </Card>

    {/* ── Submit Modal ── */}
    <Modal
      title={<span><PlusOutlined /> 提交反馈</span>}
      open={submitOpen}
      onCancel={() => { setSubmitOpen(false); form.resetFields() }}
      onOk={handleSubmit}
      confirmLoading={submitting}
      okText="提交"
      width={600}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item name="category" label="分类" initialValue="other" rules={[{ required: true }]}>
          <Select options={categoryOptions} />
        </Form.Item>
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input placeholder="简明扼要地描述反馈" maxLength={200} showCount />
        </Form.Item>
        <Form.Item name="content" label="详细内容" rules={[{ required: true, message: '请输入内容' }]}>
          <TextArea rows={4} placeholder="请详细描述你的反馈…" maxLength={10000} showCount />
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="user_name" label="你的名字">
              <Input placeholder="可选" maxLength={100} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="user_contact" label="联系方式">
              <Input placeholder="可选，方便跟进" maxLength={200} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>

    {/* ── Detail Modal ── */}
    <Modal
      title={<span style={{ color: '#0F172A', fontWeight: 600 }}>反馈详情</span>}
      open={!!detail}
      onCancel={closeDetail}
      footer={null}
      width={680}
    >
      {detailLoading
        ? <Spin style={{ display: 'block', marginTop: 40 }} />
        : detail && <div>
            {/* Meta */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <div>
                  <div style={{ color: '#64748B', fontSize: 12, marginBottom: 4 }}>分类</div>
                  <span style={{ fontSize: 14, color: CATEGORY_CONFIG[detail.category]?.color }}>
                    {CATEGORY_CONFIG[detail.category]?.label || detail.category}
                  </span>
                </div>
              </Col>
              <Col span={6}>
                <div>
                  <div style={{ color: '#64748B', fontSize: 12, marginBottom: 4 }}>状态</div>
                  <Tag color={STATUS_CONFIG[detail.status]?.color}>{STATUS_CONFIG[detail.status]?.label || detail.status}</Tag>
                </div>
              </Col>
              <Col span={6}>
                <Statistic title="提交人" value={detail.user_name || '匿名'} valueStyle={{ fontSize: 14 }} />
              </Col>
              <Col span={6}>
                <Statistic title="提交时间" value={detail.created_at?.slice(0, 16).replace('T', ' ')}
                  valueStyle={{ fontSize: 13 }} />
              </Col>
            </Row>

            {/* Title & Content */}
            <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 16, marginBottom: 16 }}>
              <h4 style={{ margin: '0 0 8px', color: '#0F172A' }}>{detail.title}</h4>
              <Paragraph style={{ color: '#475569', margin: 0, whiteSpace: 'pre-wrap', fontSize: 13 }}>
                {detail.content}
              </Paragraph>
            </div>

            {/* Status Update */}
            <Divider style={{ fontSize: 12, color: '#64748B' }}>状态更新</Divider>
            <Row gutter={8} style={{ marginBottom: 16 }}>
              {statusOptions.map(opt => (
                <Col key={opt.value}>
                  <Button
                    size="small"
                    type={detail.status === opt.value ? 'primary' : 'default'}
                    disabled={detail.status === opt.value}
                    loading={statusUpdating && detail.status !== opt.value}
                    onClick={() => updateItemStatus(detail.id, opt.value)}
                    style={{
                      background: detail.status === opt.value ? STATUS_CONFIG[opt.value]?.bg : undefined,
                      borderColor: detail.status === opt.value ? STATUS_CONFIG[opt.value]?.dot : undefined,
                      color: detail.status === opt.value ? STATUS_CONFIG[opt.value]?.dot : undefined,
                    }}
                  >
                    {STATUS_CONFIG[opt.value]?.label}
                  </Button>
                </Col>
              ))}
            </Row>

            {/* Contact */}
            {detail.contact && <div style={{ marginBottom: 12 }}>
              <Text style={{ color: '#64748B', fontSize: 12 }}>联系方式: {detail.contact}</Text>
            </div>}

            <Divider style={{ fontSize: 12, color: '#64748B' }}>评论 ({(detail.comments ?? []).length || 0})</Divider>

            {(detail.comments ?? []).length > 0 ? (
              <div style={{ marginBottom: 16 }}>
                <Timeline
                  items={(detail.comments ?? []).map(c => ({
                    key: c.id,
                    color: '#2563EB',
                    children: <div style={{ fontSize: 13 }}>
                      <div style={{ color: '#64748B', fontSize: 11 }}>
                        <strong>{c.user || 'anonymous'}</strong> · {c.created_at?.slice(0, 16).replace('T', ' ')}
                      </div>
                      <div style={{ color: '#334155', marginTop: 4 }}>{c.text}</div>
                    </div>
                  }))}
                />
              </div>
            ) : (
              <div style={{ color: '#94A3B8', fontSize: 13, marginBottom: 16, textAlign: 'center' }}>暂无评论</div>
            )}

            {/* Add Comment */}
            <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, padding: 12 }}>
              <Row gutter={12} style={{ marginBottom: 8 }}>
                <Col span={6}>
                  <Input
                    placeholder="你的名字"
                    value={commentUser}
                    onChange={e => setCommentUser(e.target.value)}
                    size="small"
                  />
                </Col>
              </Row>
              <TextArea
                placeholder="输入评论…"
                value={commentText}
                onChange={e => setCommentText(e.target.value)}
                rows={2}
                style={{ marginBottom: 8 }}
              />
              <Button
                type="primary"
                size="small"
                icon={<MessageOutlined />}
                onClick={addComment}
                loading={commenting}
                disabled={!commentText.trim()}
              >
                发送评论
              </Button>
            </div>
          </div>
      }
    </Modal>
  </div>
}

export default Feedback
