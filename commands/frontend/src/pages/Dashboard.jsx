import { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Spin } from 'antd'
import {
  RobotOutlined,
  FileSearchOutlined,
  BookOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'

export default function Dashboard() {
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState({
    activeAgents: 0,
    totalResearch: 0,
    knowledgeEntries: 0,
    tasksCompleted: 0,
  })
  const [recentTasks, setRecentTasks] = useState([])
  const [chartData, setChartData] = useState({ dates: [], values: [] })

  useEffect(() => {
    setStats({
      activeAgents: 3,
      totalResearch: 128,
      knowledgeEntries: 456,
      tasksCompleted: 892,
    })
    setRecentTasks([
      { key: '1', name: 'A股市场情绪分析', agent: 'Research Agent', status: 'completed', time: '2分钟前' },
      { key: '2', name: '行业轮动策略回测', agent: 'Strategy Agent', status: 'running', time: '5分钟前' },
      { key: '3', name: '财报数据提取 — 茅台', agent: 'Data Agent', status: 'completed', time: '10分钟前' },
      { key: '4', name: '政策新闻监控', agent: 'Monitor Agent', status: 'pending', time: '15分钟前' },
      { key: '5', name: '知识库向量化更新', agent: 'Knowledge Agent', status: 'running', time: '20分钟前' },
    ])
    setChartData({
      dates: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
      values: [12, 18, 15, 22, 20, 8, 5],
    })
    setLoading(false)
  }, [])

  const statusColor = {
    completed: 'success',
    running: 'processing',
    pending: 'default',
  }
  const statusLabel = {
    completed: '已完成',
    running: '运行中',
    pending: '等待中',
  }

  const lineOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, bottom: 30, top: 10 },
    xAxis: {
      type: 'category',
      data: chartData.dates,
      axisLabel: { fontSize: 11 },
    },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        type: 'line',
        data: chartData.values,
        smooth: true,
        lineStyle: { color: '#1677ff', width: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(22,119,255,0.25)' },
              { offset: 1, color: 'rgba(22,119,255,0.02)' },
            ],
          },
        },
        symbol: 'circle',
        symbolSize: 6,
      },
    ],
  }

  const columns = [
    { title: '任务', dataIndex: 'name', key: 'name' },
    { title: '智能体', dataIndex: 'agent', key: 'agent' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s) => <Tag color={statusColor[s]}>{statusLabel[s]}</Tag>,
    },
    { title: '时间', dataIndex: 'time', key: 'time' },
  ]

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>总览</h2>

      <Row gutter={[16, 16]}>
        <Col xs={12} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="活跃智能体"
              value={stats.activeAgents}
              prefix={<RobotOutlined style={{ color: '#1677ff' }} />}
              suffix="个"
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="研究任务"
              value={stats.totalResearch}
              prefix={<FileSearchOutlined style={{ color: '#52c41a' }} />}
              suffix="项"
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="知识条目"
              value={stats.knowledgeEntries}
              prefix={<BookOutlined style={{ color: '#faad14' }} />}
              suffix="条"
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="完成任务"
              value={stats.tasksCompleted}
              prefix={<ThunderboltOutlined style={{ color: '#ff4d4f' }} />}
              suffix="次"
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={14}>
          <Card title="本周研究活动趋势">
            <ReactECharts
              option={lineOption}
              style={{ height: 280 }}
              notMerge
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="最近任务">
            <Table
              dataSource={recentTasks}
              columns={columns}
              pagination={false}
              size="small"
              showHeader={false}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
