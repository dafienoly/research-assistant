import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Select, Space, Spin, Table, Tag, Typography, message } from 'antd'
import { ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { API } from '../App'

const { Title, Text } = Typography

interface Finding {
  fingerprint: string
  rule_id: string
  severity: 'FAIL' | 'WARN' | 'INFO'
  file: string
  line: number
  message: string
  blocking: boolean
}

interface AuditRun {
  run_id: string
  profile: 'fast' | 'full' | 'security'
  scope: string
  state: string
  passed: boolean
  change_set_hash: string
  started_at: string
  durations?: Record<string, number>
  findings: Finding[]
  extras?: { files?: string[] }
}

function unwrap<T>(payload: { data?: T } | T): T {
  return ((payload as { data?: T }).data ?? payload) as T
}

export default function CodeAudit() {
  const [runs, setRuns] = useState<AuditRun[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [profile, setProfile] = useState<'fast' | 'full' | 'security'>('fast')
  const [selected, setSelected] = useState<AuditRun | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await fetch(`${API}/api/code-audits/runs`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = unwrap<{ runs: AuditRun[] }>(await response.json())
      setRuns(payload.runs || [])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '代码审计记录加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const trigger = async () => {
    setRunning(true)
    try {
      const response = await fetch(`${API}/api/code-audits/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, scope: 'working-tree' }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const run = unwrap<AuditRun>(await response.json())
      message.success(`审计完成：${run.state}`)
      await load()
      setSelected(run)
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '代码审计启动失败')
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => { load() }, [load])

  const columns = [
    { title: '运行', dataIndex: 'run_id', key: 'run_id', render: (value: string) => <Text code>{value}</Text> },
    { title: '档位', dataIndex: 'profile', key: 'profile', render: (value: string) => <Tag>{value}</Tag> },
    { title: '范围', dataIndex: 'scope', key: 'scope' },
    { title: '状态', dataIndex: 'state', key: 'state', render: (value: string, row: AuditRun) => <Tag color={row.passed ? 'success' : 'error'}>{value}</Tag> },
    { title: '发现', key: 'findings', render: (_: unknown, row: AuditRun) => row.findings?.length || 0 },
    { title: '变更集', dataIndex: 'change_set_hash', key: 'change_set_hash', render: (value: string) => <Text code>{value}</Text> },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}><SafetyCertificateOutlined /> 代码审计中心</Title>
          <Text type="secondary">快速档用于编辑反馈；完整档用于里程碑；安全档要求安全扫描工具可用。</Text>
        </div>
        {error && <Alert type="error" showIcon message="加载失败" description={error} />}
        <Card>
          <Space>
            <Select value={profile} onChange={setProfile} style={{ width: 140 }} options={[
              { value: 'fast', label: '快速审计' },
              { value: 'full', label: '完整审计' },
              { value: 'security', label: '安全审计' },
            ]} />
            <Button type="primary" loading={running} onClick={trigger}>运行审计</Button>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          </Space>
        </Card>
        <Card title="审计运行记录">
          {loading && !runs.length ? <Spin /> : (
            <Table rowKey="run_id" dataSource={runs} columns={columns} pagination={{ pageSize: 20 }} onRow={(row) => ({ onClick: () => setSelected(row) })} />
          )}
        </Card>
      </Space>
      <Drawer width={720} title="审计详情" open={Boolean(selected)} onClose={() => setSelected(null)}>
        {selected && <>
          <Descriptions bordered size="small" column={1} items={[
            { key: 'run', label: '运行 ID', children: selected.run_id },
            { key: 'state', label: '状态', children: selected.state },
            { key: 'hash', label: '变更集', children: selected.change_set_hash },
            { key: 'files', label: '文件数', children: selected.extras?.files?.length || 0 },
          ]} />
          <Table style={{ marginTop: 16 }} rowKey="fingerprint" dataSource={selected.findings || []} pagination={false} columns={[
            { title: '级别', dataIndex: 'severity', key: 'severity', render: (value: string) => <Tag color={value === 'FAIL' ? 'error' : value === 'WARN' ? 'warning' : 'default'}>{value}</Tag> },
            { title: '规则', dataIndex: 'rule_id', key: 'rule_id' },
            { title: '位置', key: 'location', render: (_: unknown, row: Finding) => `${row.file}${row.line ? `:${row.line}` : ''}` },
            { title: '说明', dataIndex: 'message', key: 'message' },
          ]} />
        </>}
      </Drawer>
    </div>
  )
}
