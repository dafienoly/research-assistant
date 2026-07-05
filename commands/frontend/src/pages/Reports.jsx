import { useState, useEffect } from 'react'
import { Card, Table, Tag, Spin } from 'antd'
import { API } from '../App'

const cardStyle = { background: '#121a35', border: '1px solid #26304f', borderRadius: 12 }

export default function Reports() {
  const [data, setData] = useState(null)
  useEffect(() => {
    fetch(`${API}/api/versions/report`).then(r => r.json()).then(d => {
      fetch(`${API}/api/backups`).then(r => r.json()).then(b => setData({ ...d, backups: b.backups }))
    })
  }, [])

  if (!data) return <Spin />
  const vcols = [
    { title: '版本', dataIndex: 'version', key: 'v' },
    { title: '名称', dataIndex: 'name', key: 'n' },
    { title: '状态', dataIndex: 'status', key: 's', render: v => <Tag color={v === 'completed' ? 'green' : 'red'}>{v}</Tag> },
  ]
  const bcols = [
    { title: '备份', dataIndex: 'id', key: 'id', render: v => <code style={{ color: '#7df0bd' }}>{v.slice(0, 20)}...</code> },
    { title: '版本', dataIndex: 'current_version', key: 'v', width: 80 },
    { title: '已完成', dataIndex: 'completed', key: 'c', width: 80 },
  ]

  return <div>
    <Card title={<span style={{ color: '#cdd6f8' }}>📊 版本开发报告</span>} style={{ ...cardStyle, marginBottom: 16 }}>
      <p style={{ color: '#9aa7c7' }}>当前: {data.current_version} | 已完成: {data.total_completed} | 失败: {data.total_failed}</p>
      <Table dataSource={data.versions || []} columns={vcols} rowKey="version" size="small" pagination={false} />
    </Card>
    <Card title={<span style={{ color: '#cdd6f8' }}>💾 备份列表</span>} style={cardStyle}>
      <Table dataSource={data.backups || []} columns={bcols} rowKey="id" size="small" pagination={false} />
    </Card>
  </div>
}
