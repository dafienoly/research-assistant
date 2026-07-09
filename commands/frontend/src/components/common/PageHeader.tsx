import React from 'react'
import { Typography, Space, Tag } from 'antd'
import { ClockCircleOutlined, DatabaseOutlined, CodeOutlined } from '@ant-design/icons'

interface PageHeaderProps {
  title: string
  updatedAt?: string
  dataSource?: string
  runId?: string
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, updatedAt, dataSource, runId }) => (
  <div
    style={{
      marginBottom: 24,
      paddingBottom: 16,
      borderBottom: '1px solid #E2E8F0',
    }}
  >
    <Typography.Title level={4} style={{ margin: 0, color: '#0F172A' }}>
      {title}
    </Typography.Title>
    {(updatedAt || dataSource || runId) && (
      <Space size={16} style={{ marginTop: 8 }}>
        {updatedAt && (
          <Space size={4}>
            <ClockCircleOutlined style={{ fontSize: 12, color: '#64748B' }} />
            <Typography.Text style={{ fontSize: 12, color: '#64748B' }}>
              {updatedAt}
            </Typography.Text>
          </Space>
        )}
        {dataSource && (
          <Space size={4}>
            <DatabaseOutlined style={{ fontSize: 12, color: '#64748B' }} />
            <Typography.Text style={{ fontSize: 12, color: '#64748B' }}>
              {dataSource}
            </Typography.Text>
          </Space>
        )}
        {runId && (
          <Tag icon={<CodeOutlined />} style={{ fontSize: 11, margin: 0 }} color="default">
            {runId}
          </Tag>
        )}
      </Space>
    )}
  </div>
)

export default PageHeader
