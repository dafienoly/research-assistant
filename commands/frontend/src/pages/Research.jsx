import { useState } from 'react'
import {
  Card,
  Input,
  List,
  Tag,
  Typography,
  Space,
  Empty,
  Button,
  Segmented,
  Spin,
} from 'antd'
import {
  SearchOutlined,
  FileTextOutlined,
  GlobalOutlined,
  BulbOutlined,
  DownloadOutlined,
  StarOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography

const CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: 'market', label: '市场分析' },
  { key: 'industry', label: '行业研究' },
  { key: 'company', label: '公司调研' },
  { key: 'policy', label: '政策解读' },
]

// Mock data — replace with real API
const MOCK_RESULTS = [
  {
    id: '1',
    title: '2025年A股市场中期策略展望',
    category: 'market',
    source: '研究报告',
    date: '2025-06-28',
    summary: '基于宏观经济数据与资金流向的综合分析，预判下半年市场走势与结构性机会。',
    tags: ['A股', '策略', '宏观'],
    starred: true,
  },
  {
    id: '2',
    title: '半导体行业国产替代深度报告',
    category: 'industry',
    source: '行业分析',
    date: '2025-06-25',
    summary: '梳理半导体产业链各环节国产化率，分析设备、材料、EDA等关键领域的替代进程。',
    tags: ['半导体', '国产替代', '硬科技'],
    starred: false,
  },
  {
    id: '3',
    title: '贵州茅台：品牌护城河与增长天花板',
    category: 'company',
    source: '公司研究',
    date: '2025-06-22',
    summary: '从品牌溢价、渠道改革、产能扩张等维度评估贵州茅台的长期投资价值。',
    tags: ['白酒', '消费', '龙头'],
    starred: true,
  },
  {
    id: '4',
    title: '新国九条政策影响评估',
    category: 'policy',
    source: '政策研究',
    date: '2025-06-20',
    summary: '分析新国九条对资本市场制度建设的深远影响，以及重点受益方向。',
    tags: ['政策', '制度', '改革'],
    starred: false,
  },
  {
    id: '5',
    title: '新能源汽车产业链2025中期景气度分析',
    category: 'industry',
    source: '行业分析',
    date: '2025-06-18',
    summary: '从终端销量、电池装机、锂价走势等高频数据判断产业链景气度拐点。',
    tags: ['新能源车', '锂电', '景气度'],
    starred: false,
  },
]

export default function Research() {
  const [searchText, setSearchText] = useState('')
  const [category, setCategory] = useState('all')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(MOCK_RESULTS)

  const handleSearch = (value) => {
    setSearchText(value)
    setLoading(true)
    // Simulate API call
    setTimeout(() => {
      const filtered = MOCK_RESULTS.filter(
        (r) =>
          (category === 'all' || r.category === category) &&
          (!value || r.title.includes(value) || r.summary.includes(value) || r.tags.some((t) => t.includes(value)))
      )
      setResults(filtered)
      setLoading(false)
    }, 300)
  }

  const handleCategoryChange = (val) => {
    setCategory(val)
    setLoading(true)
    setTimeout(() => {
      const filtered = MOCK_RESULTS.filter(
        (r) =>
          (val === 'all' || r.category === val) &&
          (!searchText || r.title.includes(searchText) || r.summary.includes(searchText) || r.tags.some((t) => t.includes(searchText)))
      )
      setResults(filtered)
      setLoading(false)
    }, 200)
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>
        <SearchOutlined style={{ marginRight: 8 }} />
        研究
      </h2>

      {/* Search Bar */}
      <Input.Search
        placeholder="搜索研究报告、公司、行业、政策..."
        allowClear
        enterButton={<span><SearchOutlined /> 搜索</span>}
        size="large"
        onSearch={handleSearch}
        style={{ maxWidth: 640, marginBottom: 16 }}
      />

      {/* Category Filter */}
      <Segmented
        options={CATEGORIES.map((c) => ({
          value: c.key,
          label: (
            <span>
              {c.key === 'market' && <GlobalOutlined />}
              {c.key === 'industry' && <BulbOutlined />}
              {c.key === 'company' && <FileTextOutlined />}
              {c.key === 'policy' && <FileTextOutlined />}
              {c.key === 'all' && <SearchOutlined />}
              <span style={{ marginLeft: 4 }}>{c.label}</span>
            </span>
          ),
        }))}
        value={category}
        onChange={handleCategoryChange}
        style={{ marginBottom: 20 }}
      />

      {/* Results */}
      <Spin spinning={loading}>
        {results.length === 0 ? (
          <Empty description="未找到相关研究" style={{ marginTop: 60 }} />
        ) : (
          <List
            dataSource={results}
            renderItem={(item) => (
              <List.Item
                key={item.id}
                actions={[
                  <Button type="text" icon={<DownloadOutlined />} title="下载" />,
                  <Button
                    type="text"
                    icon={<StarOutlined style={{ color: item.starred ? '#faad14' : undefined }} />}
                    title="收藏"
                  />,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Text strong style={{ fontSize: 15 }}>{item.title}</Text>
                      <Tag color="blue">{item.source}</Tag>
                    </Space>
                  }
                  description={
                    <div>
                      <Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                        {item.summary}
                      </Paragraph>
                      <Space>
                        {item.tags.map((t) => (
                          <Tag key={t} style={{ fontSize: 11 }}>{t}</Tag>
                        ))}
                        <Text type="secondary" style={{ fontSize: 12 }}>{item.date}</Text>
                      </Space>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>
    </div>
  )
}
