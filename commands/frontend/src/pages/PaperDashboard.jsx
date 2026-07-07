import { useState, useEffect } from 'react'
import { Card, Row, Col, Table, Tag, Button, Spin, Alert, Typography, Tabs, Space, Statistic, Empty, Form, InputNumber, Select, Divider, Modal, message } from 'antd'
import {
  DollarOutlined, ReloadOutlined, WalletOutlined, BarsOutlined, SwapOutlined,
  CheckCircleOutlined, CloseCircleOutlined, HistoryOutlined, PlusOutlined,
  MinusCircleOutlined, FileTextOutlined, InfoCircleOutlined
} from '@ant-design/icons'
import { API } from '../App'

const { Title, Text } = Typography

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }
const statCard = (color) => ({ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, borderLeft: `4px solid ${color}`, marginBottom: 16 })

const SIDE_CONFIG = {
  buy:  { color: '#EF4444', label: '买入', bg: '#FEE2E2' },
  sell: { color: '#10B981', label: '卖出', bg: '#D1FAE5' },
}

const STATUS_CONFIG = {
  pending:  { color: 'default', label: '待成交', dot: '#F59E0B', bg: '#FEF3C7' },
  filled:   { color: 'success', label: '已成交', dot: '#10B981', bg: '#D1FAE5' },
  partial:  { color: 'processing', label: '部分成交', dot: '#3B82F6', bg: '#DBEAFE' },
  canceled: { color: 'default', label: '已撤销', dot: '#6B7280', bg: '#F3F4F6' },
  rejected: { color: 'error', label: '已拒绝', dot: '#EF4444', bg: '#FEE2E2' },
}

export default function PaperDashboard() {
  const [balance, setBalance] = useState(null)
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState({ total: 0, orders: [] })
  const [fills, setFills] = useState({ total: 0, fills: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [placeLoading, setPlaceLoading] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [bal, pos, ord, fil] = await Promise.all([
        fetch(`${API}/api/paper/balance`).then(r => r.json()),
        fetch(`${API}/api/paper/positions`).then(r => r.json()),
        fetch(`${API}/api/paper/orders?limit=100`).then(r => r.json()),
        fetch(`${API}/api/paper/fills?limit=100`).then(r => r.json()),
      ])
      setBalance(bal)
      setPositions(pos?.positions || [])
      setOrders(ord)
      setFills(fil)
    } catch (e) {
      setError(e.message || '加载纸面交易数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t) }, [])

  // ── Place order ──
  const handlePlaceOrder = async (values) => {
    setPlaceLoading(true)
    try {
      const params = new URLSearchParams({
        symbol: values.symbol.toUpperCase(),
        side: values.side,
        quantity: String(values.quantity),
        price: String(values.price),
        order_type: values.order_type || 'limit',
      })
      const resp = await fetch(`${API}/api/paper/orders?${params}`, { method: 'POST' })
      const result = await resp.json()
      if (result.error) {
        message.error(result.error)
      } else {
        message.success(`订单已提交: ${result.order_id} (${result.status})`)
        form.resetFields()
        load()
      }
    } catch (e) {
      message.error(e.message || '下单失败')
    } finally {
      setPlaceLoading(false)
    }
  }

  // ── Cancel order ──
  const handleCancelOrder = async (orderId) => {
    try {
      const resp = await fetch(`${API}/api/paper/orders/${orderId}`, { method: 'DELETE' })
      const result = await resp.json()
      if (result.error) {
        message.error(result.error)
      } else {
        message.success(`订单 ${orderId} 已撤销`)
        load()
      }
    } catch (e) {
      message.error(e.message || '撤销失败')
    }
  }

  // ── Reset account ──
  const handleReset = () => {
    Modal.confirm({
      title: '重置账户',
      content: '确定要重置虚拟账户吗？所有持仓、订单和成交记录将被清空。',
      okText: '确定',
      cancelText: '取消',
      onOk: async () => {
        setResetLoading(true)
        try {
          const resp = await fetch(`${API}/api/paper/reset?initial_cash=1000000`, { method: 'POST' })
          const result = await resp.json()
          message.success(result.message || '账户已重置')
          load()
        } catch (e) {
          message.error(e.message || '重置失败')
        } finally {
          setResetLoading(false)
        }
      },
    })
  }

  // ── Loading / Error ──
  if (loading && !balance) {
    return <Spin style={{ display: 'block', marginTop: 80 }} />
  }

  if (error && !balance) {
    return <Alert message="加载失败" description={error} type="error" showIcon style={{ margin: 24 }} />
  }

  // ── Column defs ──
  const positionCols = [
    { title: '代码', dataIndex: 'symbol', key: 'symbol', width: 100,
      render: v => <code style={{ color: '#2563EB', fontWeight: 600 }}>{v}</code> },
    { title: '持仓', dataIndex: 'shares', key: 'shares', width: 80, align: 'right' },
    { title: '均价', dataIndex: 'avg_cost', key: 'avg_cost', width: 100, align: 'right',
      render: v => <span>{v.toFixed(2)}</span> },
    { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 100, align: 'right',
      render: v => <span>{v.toFixed(2)}</span> },
    { title: '市值', dataIndex: 'market_value', key: 'market_value', width: 100, align: 'right',
      render: v => <span>{v.toFixed(2)}</span> },
    { title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 110, align: 'right',
      render: (v) => {
        const color = v >= 0 ? '#10B981' : '#EF4444'
        return <span style={{ color, fontWeight: 600 }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}</span>
      },
    },
    { title: '盈亏%', dataIndex: 'unrealized_pnl_pct', key: 'unrealized_pnl_pct', width: 90, align: 'right',
      render: (v) => {
        const pct = (v * 100).toFixed(2)
        const color = v >= 0 ? '#10B981' : '#EF4444'
        return <span style={{ color, fontWeight: 600 }}>{v >= 0 ? '+' : ''}{pct}%</span>
      },
    },
  ]

  const orderCols = [
    { title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 120,
      render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v}</code> },
    { title: '方向', dataIndex: 'side', key: 'side', width: 60,
      render: (v) => {
        const cfg = SIDE_CONFIG[v] || {}
        return <Tag color={cfg.color || 'default'} style={{ border: 'none' }}>{cfg.label || v}</Tag>
      },
    },
    { title: '代码', dataIndex: 'symbol', key: 'symbol', width: 80 },
    { title: '类型', dataIndex: 'order_type', key: 'order_type', width: 70 },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90, align: 'right',
      render: v => v.toFixed(2) },
    { title: '数量', dataIndex: 'quantity', key: 'quantity', width: 70, align: 'right' },
    { title: '成交', dataIndex: 'filled_quantity', key: 'filled', width: 70, align: 'right' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v) => {
        const cfg = STATUS_CONFIG[v] || STATUS_CONFIG.pending
        return <Tag color={cfg.color} style={{ border: 'none', borderRadius: 12, fontSize: 11 }}>{cfg.label}</Tag>
      },
    },
    { title: '原因', dataIndex: 'reason', key: 'reason', width: 100, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v) => {
        if (!v) return '-'
        return <Text style={{ fontSize: 11, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text>
      },
    },
    {
      title: '操作', key: 'action', width: 70, render: (_, record) => {
        if (record.status === 'pending' || record.status === 'partial') {
          return (
            <Button size="small" danger onClick={() => handleCancelOrder(record.order_id)}>
              撤销
            </Button>
          )
        }
        return null
      },
    },
  ]

  const fillCols = [
    { title: '成交号', dataIndex: 'fill_id', key: 'fill_id', width: 110,
      render: v => <code style={{ color: '#2563EB', fontSize: 11 }}>{v}</code> },
    { title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 110,
      render: v => <code style={{ color: '#6B7280', fontSize: 11 }}>{v}</code> },
    { title: '方向', dataIndex: 'side', key: 'side', width: 60,
      render: (v) => {
        const cfg = SIDE_CONFIG[v] || {}
        return <Tag color={cfg.color || 'default'} style={{ border: 'none' }}>{cfg.label || v}</Tag>
      },
    },
    { title: '代码', dataIndex: 'symbol', key: 'symbol', width: 80 },
    { title: '成交价', dataIndex: 'fill_price', key: 'fill_price', width: 90, align: 'right',
      render: v => v.toFixed(2) },
    { title: '数量', dataIndex: 'fill_quantity', key: 'fill_quantity', width: 70, align: 'right' },
    { title: '金额', dataIndex: 'fill_amount', key: 'fill_amount', width: 100, align: 'right',
      render: v => v.toFixed(2) },
    { title: '佣金', dataIndex: 'fee', key: 'fee', width: 80, align: 'right',
      render: v => v.toFixed(2) },
    { title: '印花税', dataIndex: 'tax', key: 'tax', width: 80, align: 'right',
      render: v => v.toFixed(2) },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v) => {
        if (!v) return '-'
        return <Text style={{ fontSize: 11, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text>
      },
    },
  ]

  // ── Tab items ──
  const tabItems = [
    {
      key: 'overview',
      label: <span><WalletOutlined /> 概览</span>,
      children: renderOverview(),
    },
    {
      key: 'positions',
      label: <span><BarsOutlined /> 持仓 ({positions.length})</span>,
      children: renderPositions(),
    },
    {
      key: 'place-order',
      label: <span><PlusOutlined /> 下单</span>,
      children: renderPlaceOrder(),
    },
    {
      key: 'orders',
      label: <span><FileTextOutlined /> 订单 ({orders?.total ?? 0})</span>,
      children: renderOrders(),
    },
    {
      key: 'fills',
      label: <span><HistoryOutlined /> 成交 ({fills?.total ?? 0})</span>,
      children: renderFills(),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0, color: '#0F172A' }}>
          <DollarOutlined style={{ marginRight: 8, color: '#10B981' }} />
          纸面交易仪表盘
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Button icon={<CloseCircleOutlined />} onClick={handleReset} loading={resetLoading} danger>重置</Button>
        </Space>
      </div>

      {error && <Alert message={error} type="error" showIcon closable style={{ marginBottom: 16 }} />}

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  )

  // ── Overview tab ──
  function renderOverview() {
    const b = balance || {}

    return (
      <div>
        {/* Stat cards */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#10B981')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>总资产</Text>}
                value={b.total_value ?? 0}
                prefix={<DollarOutlined />}
                precision={2}
                valueStyle={{ color: '#10B981', fontSize: 22, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#3B82F6')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>可用现金</Text>}
                value={b.cash ?? 0}
                prefix={<WalletOutlined />}
                precision={2}
                valueStyle={{ color: '#3B82F6', fontSize: 22, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#8B5CF6')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>持仓市值</Text>}
                value={b.market_value ?? 0}
                prefix={<BarsOutlined />}
                precision={2}
                valueStyle={{ color: '#8B5CF6', fontSize: 22, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard((b.total_pnl ?? 0) >= 0 ? '#10B981' : '#EF4444')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>总盈亏</Text>}
                value={b.total_pnl ?? 0}
                precision={2}
                prefix={(b.total_pnl ?? 0) >= 0 ? '+' : ''}
                valueStyle={{ color: (b.total_pnl ?? 0) >= 0 ? '#10B981' : '#EF4444', fontSize: 22, fontWeight: 700 }}
              />
            </Card>
          </Col>
        </Row>

        {/* P&L details */}
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#2563EB')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>初始资金</Text>}
                value={b.initial_cash ?? 0}
                precision={2}
                valueStyle={{ color: '#2563EB', fontSize: 18, fontWeight: 600 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#D97706')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>总收益率</Text>}
                value={((b.total_pnl_pct ?? 0) * 100).toFixed(2)}
                suffix="%"
                precision={2}
                prefix={b.total_pnl_pct >= 0 ? '+' : ''}
                valueStyle={{ color: (b.total_pnl_pct ?? 0) >= 0 ? '#10B981' : '#EF4444', fontSize: 18, fontWeight: 600 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#10B981')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>未实现盈亏</Text>}
                value={b.unrealized_pnl ?? 0}
                precision={2}
                prefix={(b.unrealized_pnl ?? 0) >= 0 ? '+' : ''}
                valueStyle={{ color: (b.unrealized_pnl ?? 0) >= 0 ? '#10B981' : '#EF4444', fontSize: 18, fontWeight: 600 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#8B5CF6')} bodyStyle={{ padding: '16px 20px' }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>已实现盈亏</Text>}
                value={b.realized_pnl ?? 0}
                precision={2}
                prefix={(b.realized_pnl ?? 0) >= 0 ? '+' : ''}
                valueStyle={{ color: (b.realized_pnl ?? 0) >= 0 ? '#10B981' : '#EF4444', fontSize: 18, fontWeight: 600 }}
              />
            </Card>
          </Col>
        </Row>

        {/* Summary cards for positions and orders */}
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} sm={12}>
            <Card style={cardStyle} bodyStyle={{ padding: '16px 20px' }}>
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                <Text style={{ fontSize: 14, fontWeight: 600, color: '#0F172A' }}>
                  <BarsOutlined style={{ marginRight: 6 }} />持仓摘要
                </Text>
                <Row gutter={16}>
                  <Col span={12}>
                    <Text style={{ color: '#64748B', fontSize: 12 }}>持仓数量</Text>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0F172A' }}>{positions.length} 只</div>
                  </Col>
                  <Col span={12}>
                    <Text style={{ color: '#64748B', fontSize: 12 }}>持仓市值占比</Text>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0F172A' }}>
                      {b.total_value > 0 ? ((b.market_value / b.total_value) * 100).toFixed(1) : 0}%
                    </div>
                  </Col>
                </Row>
              </Space>
            </Card>
          </Col>
          <Col xs={24} sm={12}>
            <Card style={cardStyle} bodyStyle={{ padding: '16px 20px' }}>
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                <Text style={{ fontSize: 14, fontWeight: 600, color: '#0F172A' }}>
                  <SwapOutlined style={{ marginRight: 6 }} />交易统计
                </Text>
                <Row gutter={16}>
                  <Col span={12}>
                    <Text style={{ color: '#64748B', fontSize: 12 }}>总订单数</Text>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0F172A' }}>{orders?.total ?? 0}</div>
                  </Col>
                  <Col span={12}>
                    <Text style={{ color: '#64748B', fontSize: 12 }}>成交笔数</Text>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0F172A' }}>{fills?.total ?? 0}</div>
                  </Col>
                </Row>
              </Space>
            </Card>
          </Col>
        </Row>

        {/* Security notice */}
        <Card style={{ ...cardStyle, marginTop: 16, background: '#F0FDF4', borderColor: '#BBF7D0' }} bodyStyle={{ padding: '12px 20px' }}>
          <Space>
            <CheckCircleOutlined style={{ color: '#10B981' }} />
            <Text style={{ color: '#166534', fontSize: 12 }}>
              🛡️ 模拟交易模式 — 所有操作均为纸面模拟，不会产生真实交易。不下达实际订单。
            </Text>
          </Space>
        </Card>
      </div>
    )
  }

  // ── Positions tab ──
  function renderPositions() {
    if (!positions.length) {
      return (
        <Card style={cardStyle}>
          <Empty description="暂无持仓" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </Card>
      )
    }

    return (
      <Card
        style={cardStyle}
        title={
          <Space>
            <BarsOutlined style={{ color: '#2563EB' }} />
            <span>当前持仓</span>
            <Tag>{positions.length} 只</Tag>
          </Space>
        }
      >
        <Table
          dataSource={positions}
          columns={positionCols}
          rowKey="symbol"
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
          summary={() => {
            if (!positions.length) return null
            const totalMv = positions.reduce((s, p) => s + p.market_value, 0)
            const totalPnl = positions.reduce((s, p) => s + p.unrealized_pnl, 0)
            return (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0}><Text strong>合计</Text></Table.Summary.Cell>
                <Table.Summary.Cell index={1}><Text strong>{positions.reduce((s, p) => s + p.shares, 0)}</Text></Table.Summary.Cell>
                <Table.Summary.Cell index={2}></Table.Summary.Cell>
                <Table.Summary.Cell index={3}></Table.Summary.Cell>
                <Table.Summary.Cell index={4}><Text strong>{totalMv.toFixed(2)}</Text></Table.Summary.Cell>
                <Table.Summary.Cell index={5}>
                  <Text strong style={{ color: totalPnl >= 0 ? '#10B981' : '#EF4444' }}>
                    {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}
                  </Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={6}></Table.Summary.Cell>
              </Table.Summary.Row>
            )
          }}
        />
      </Card>
    )
  }

  // ── Place Order tab ──
  function renderPlaceOrder() {
    return (
      <Row gutter={[24, 24]}>
        <Col xs={24} lg={12}>
          <Card
            style={cardStyle}
            title={<span><PlusOutlined style={{ color: '#2563EB' }} /> 模拟下单</span>}
          >
            <Form
              form={form}
              layout="vertical"
              onFinish={handlePlaceOrder}
              initialValues={{ side: 'buy', order_type: 'limit', quantity: 100 }}
            >
              <Form.Item name="symbol" label="股票代码" rules={[{ required: true, message: '请输入股票代码' }]}>
                <InputNumber style={{ width: '100%' }} placeholder="例如: 000001" min={0} />
              </Form.Item>

              <Form.Item name="side" label="方向" rules={[{ required: true }]}>
                <Select>
                  <Select.Option value="buy">
                    <span style={{ color: '#EF4444' }}>买入</span>
                  </Select.Option>
                  <Select.Option value="sell">
                    <span style={{ color: '#10B981' }}>卖出</span>
                  </Select.Option>
                </Select>
              </Form.Item>

              <Form.Item name="order_type" label="订单类型">
                <Select>
                  <Select.Option value="limit">限价单</Select.Option>
                  <Select.Option value="market">市价单</Select.Option>
                </Select>
              </Form.Item>

              <Form.Item name="price" label="价格" rules={[{ required: true, message: '请输入价格' }]}>
                <InputNumber style={{ width: '100%' }} placeholder="输入价格" min={0.01} step={0.01} precision={2} />
              </Form.Item>

              <Form.Item name="quantity" label="数量" rules={[{ required: true, message: '请输入数量' }]}>
                <InputNumber style={{ width: '100%' }} placeholder="输入数量（股）" min={100} step={100} />
              </Form.Item>

              <Form.Item>
                <Button type="primary" htmlType="submit" loading={placeLoading} block
                  style={{ background: '#2563EB', borderColor: '#2563EB', height: 40, fontSize: 15 }}>
                  提交模拟订单
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card style={cardStyle} title={<span><InfoCircleOutlined style={{ color: '#2563EB' }} /> 说明</span>}>
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <div>
                <Text strong style={{ color: '#0F172A' }}>📋 规则</Text>
                <ul style={{ marginTop: 8, paddingLeft: 20, color: '#64748B', fontSize: 13, lineHeight: 2 }}>
                  <li>初始资金: 1,000,000 元</li>
                  <li>限价单以指定价格成交</li>
                  <li>佣金: 万三 (0.03%)</li>
                  <li>印花税: 万分之五 (0.05%)，仅卖出时收取</li>
                  <li>现金不足时自动调整买入数量</li>
                  <li>可撤销待成交/部分成交订单</li>
                </ul>
              </div>
              <Divider style={{ margin: '8px 0' }} />
              <div>
                <Text strong style={{ color: '#0F172A' }}>🛡️ 安全</Text>
                <p style={{ marginTop: 8, color: '#64748B', fontSize: 13 }}>
                  所有交易均为模拟，不会产生真实交易。
                  系统不下达实际订单到市场。
                </p>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>
    )
  }

  // ── Orders tab ──
  function renderOrders() {
    const orderList = orders?.orders || []
    if (!orderList.length) {
      return (
        <Card style={cardStyle}>
          <Empty description="暂无订单" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </Card>
      )
    }

    return (
      <Card
        style={cardStyle}
        title={
          <Space>
            <FileTextOutlined style={{ color: '#2563EB' }} />
            <span>订单历史</span>
            <Tag>{orders?.total ?? 0} 条</Tag>
          </Space>
        }
      >
        <Table
          dataSource={orderList}
          columns={orderCols}
          rowKey="order_id"
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      </Card>
    )
  }

  // ── Fills tab ──
  function renderFills() {
    const fillList = fills?.fills || []
    if (!fillList.length) {
      return (
        <Card style={cardStyle}>
          <Empty description="暂无成交记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </Card>
      )
    }

    return (
      <Card
        style={cardStyle}
        title={
          <Space>
            <HistoryOutlined style={{ color: '#2563EB' }} />
            <span>成交记录</span>
            <Tag>{fills?.total ?? 0} 条</Tag>
          </Space>
        }
      >
        <Table
          dataSource={fillList}
          columns={fillCols}
          rowKey="fill_id"
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      </Card>
    )
  }
}
