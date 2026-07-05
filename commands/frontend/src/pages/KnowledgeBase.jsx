import { useState } from 'react'
import {
  Card,
  Row,
  Col,
  Input,
  Tag,
  Typography,
  List,
  Tree,
  Empty,
  Space,
  Button,
  Progress,
} from 'antd'
import {
  FolderOutlined,
  FolderOpenOutlined,
  FileOutlined,
  SearchOutlined,
  ReloadOutlined,
  DatabaseOutlined,
  BookOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography

// Mock tree data
const TREE_DATA = [
  {
    title: '市场研究',
    key: 'market',
    icon: <FolderOutlined />,
    children: [
      { title: 'A股策略', key: 'market-a', icon: <FileOutlined />, isLeaf: true },
      { title: '宏观分析', key: 'market-macro', icon: <FileOutlined />, isLeaf: true },
      { title: '资金流向', key: 'market-flow', icon: <FileOutlined />, isLeaf: true },
    ],
  },
  {
    title: '行业研究',
    key: 'industry',
    icon: <FolderOutlined />,
    children: [
      { title: '半导体', key: 'ind-semi', icon: <FileOutlined />, isLeaf: true },
      { title: '新能源', key: 'ind-new', icon: <FileOutlined />, isLeaf: true },
      { title: '消费', key: 'ind-consumer', icon: <FileOutlined />, isLeaf: true },
      { title: '医药', key: 'ind-pharma', icon: <FileOutlined />, isLeaf: true },
    ],
  },
  {
    title: '公司调研',
    key: 'company',
    icon: <FolderOutlined />,
    children: [
      { title: '贵州茅台', key: 'comp-mt', icon: <FileOutlined />, isLeaf: true },
      { title: '宁德时代', key: 'comp-catl', icon: <FileOutlined />, isLeaf: true },
      { title: '比亚迪', key: 'comp-byd', icon: <FileOutlined />, isLeaf: true },
    ],
  },
  {
    title: '政策法规',
    key: 'policy',
    icon: <FolderOutlined />,
    children: [
      { title: '资本市场政策', key: 'pol-capital', icon: <FileOutlined />, isLeaf: true },
      { title: '产业政策', key: 'pol-industry', icon: <FileOutlined />, isLeaf: true },
    ],
  },
  {
    title: '数据面板',
    key: 'data',
    icon: <DatabaseOutlined />,
    children: [
      { title: '财务指标', key: 'data-fin', icon: <FileOutlined />, isLeaf: true },
      { title: '估值数据', key: 'data-val', icon: <FileOutlined />, isLeaf: true },
    ],
  },
]

// Mock doc list
const MOCK_DOCS = [
  { key: '1', title: '2025年A股市场中期策略展望', folder: 'A股策略', size: '2.4 MB', updated: '2025-06-28', chunks: 156 },
  { key: '2', title: '半导体行业国产替代深度报告', folder: '半导体', size: '3.1 MB', updated: '2025-06-25', chunks: 203 },
  { key: '3', title: '新能源汽车产业链景气度分析', folder: '新能源', size: '1.8 MB', updated: '2025-06-18', chunks: 124 },
  { key: '4', title: '贵州茅台深度调研报告', folder: '贵州茅台', size: '2.2 MB', updated: '2025-06-15', chunks: 178 },
  { key: '5', title: '新国九条政策解读', folder: '资本市场政策', size: '1.2 MB', updated: '2025-06-12', chunks: 89 },
  { key: '6', title: '大消费板块2025下半年投资策略', folder: '消费', size: '2.8 MB', updated: '2025-06-10', chunks: 192 },
]

export default function KnowledgeBase() {
  const [selectedFolder, setSelectedFolder] = useState(null)
  const [searchText, setSearchText] = useState('')
  const [docs] = useState(MOCK_DOCS)

  const handleTreeSelect = (keys) => {
    setSelectedFolder(keys[0] || null)
  }

  const filteredDocs = docs.filter(
    (d) =>
      (!selectedFolder ||
        d.folder === TREE_DATA.flatMap((n) => n.children || []).find((c) => c.key === selectedFolder)?.title) &&
      (!searchText || d.title.includes(searchText))
  )

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>
        <BookOutlined style={{ marginRight: 8 }} />
        知识库
      </h2>

      <Row gutter={[16, 16]}>
        {/* Left sidebar — folder tree */}
        <Col xs={24} sm={8} md={6}>
          <Card
            title={
              <Space>
                <FolderOutlined />
                <span>分类</span>
              </Space>
            }
            size="small"
            bodyStyle={{ padding: '8px 0' }}
          >
            <Tree
              showIcon
              defaultExpandAll
              treeData={TREE_DATA}
              onSelect={handleTreeSelect}
              selectedKeys={selectedFolder ? [selectedFolder] : []}
              style={{ fontSize: 13 }}
            />
          </Card>

          {/* Index stats */}
          <Card size="small" style={{ marginTop: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                <DatabaseOutlined />
                <Text type="secondary">索引状态</Text>
              </Space>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>向量索引</Text>
                  <Text style={{ fontSize: 12 }}>942 / 1,000</Text>
                </div>
                <Progress percent={94} size="small" showInfo={false} />
              </div>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>全文索引</Text>
                  <Text style={{ fontSize: 12 }}>1,248 / 1,250</Text>
                </div>
                <Progress percent={99} size="small" showInfo={false} />
              </div>
            </Space>
          </Card>
        </Col>

        {/* Right — document list */}
        <Col xs={24} sm={16} md={18}>
          <Card
            title={
              <Space>
                <FileOutlined />
                <span>{selectedFolder ? '已选分类' : '全部文档'}</span>
              </Space>
            }
            extra={
              <Space>
                <Input.Search
                  placeholder="搜索文档..."
                  allowClear
                  size="small"
                  style={{ width: 200 }}
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                />
                <Button size="small" icon={<ReloadOutlined />}>
                  刷新
                </Button>
              </Space>
            }
            bodyStyle={{ padding: 0 }}
          >
            {filteredDocs.length === 0 ? (
              <Empty description="暂无文档" style={{ padding: '40px 0' }} />
            ) : (
              <List
                dataSource={filteredDocs}
                renderItem={(doc) => (
                  <List.Item
                    key={doc.key}
                    style={{ padding: '12px 16px' }}
                    extra={
                      <Space direction="vertical" align="end" size={0}>
                        <Text type="secondary" style={{ fontSize: 12 }}>{doc.size}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{doc.chunks} 分块</Text>
                      </Space>
                    }
                  >
                    <List.Item.Meta
                      avatar={<FileOutlined style={{ fontSize: 20, color: '#1677ff' }} />}
                      title={
                        <Space>
                          <Text strong>{doc.title}</Text>
                          <Tag color="blue" style={{ fontSize: 11 }}>{doc.folder}</Tag>
                        </Space>
                      }
                      description={
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          更新于 {doc.updated}
                        </Text>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
