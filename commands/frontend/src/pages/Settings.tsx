import { useState, useEffect, useCallback, type FC } from 'react'
import {
  Card, Button, Spin, Alert, Typography, Space, Tag, Divider,
  InputNumber, Input, message, Modal, Descriptions, Tooltip, Empty
} from 'antd'
import {
  SafetyOutlined, ReloadOutlined, EditOutlined, SaveOutlined,
  ApiOutlined, LinkOutlined, ThunderboltOutlined, WarningOutlined,
  LockOutlined, KeyOutlined, FileSearchOutlined, CheckCircleOutlined,
  CloseCircleOutlined, EyeOutlined, EyeInvisibleOutlined
} from '@ant-design/icons'
import { API } from '../App'
import PageHeader from '../components/common/PageHeader'

const { Title, Text } = Typography

const CARD_STYLE: React.CSSProperties = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

// ─── Types ────────────────────────────────────────────────────────
interface SettingsData {
  tushare_token?: string
  qmt_bridge_address?: string
  qmt_bridge_port?: number
  wecom_webhook?: string
  risk_max_single_position_pct?: number
  risk_max_sector_concentration_pct?: number
  risk_stop_loss_pct?: number
  account_permissions?: string[]
  hermes_ui_token_status?: 'set' | 'not_set'
}

interface AuditLogEntry {
  id: string
  action: string
  user: string
  target: string
  detail?: string
  created_at: string
}

interface SettingsDraft {
  tushare: string
  qmtAddr: string
  qmtPort: number
  wecom: string
  singlePct: number
  sectorPct: number
  stopLoss: number
  permissions: string[]
}

const DEFAULT_DRAFT: SettingsDraft = {
  tushare: '',
  qmtAddr: '',
  qmtPort: 0,
  wecom: '',
  singlePct: 20,
  sectorPct: 30,
  stopLoss: 10,
  permissions: [],
}

const SECTION_LABELS: Record<string, string> = {
  tushare: 'Tushare Token',
  qmt: 'QMT Bridge',
  wecom: '企业微信 Webhook',
  risk: '风险阈值',
  permissions: '账户权限',
}

const AVAILABLE_PERMISSIONS = [
  { key: 'trade', label: '交易权限' },
  { key: 'view_positions', label: '查看持仓' },
  { key: 'view_orders', label: '查看订单' },
  { key: 'manage_strategies', label: '管理策略' },
  { key: 'export_data', label: '导出数据' },
  { key: 'admin', label: '管理员' },
]

// ─── Helpers ──────────────────────────────────────────────────────
function maskToken(token: string | undefined): string {
  if (!token || token.length === 0) return '—'
  return '••••' + token.slice(-4)
}

function maskWebhook(url: string | undefined): string {
  if (!url || url.length === 0) return '—'
  return '••••' + url.slice(-4)
}

function maskAddress(addr: string | undefined): string {
  if (!addr || addr.length === 0) return '—'
  if (addr.length <= 8) return '••••'
  return addr.slice(0, 4) + '••••' + addr.slice(-4)
}

function getSectionLabel(section: string): string {
  return SECTION_LABELS[section] || section
}

// ─── Component ────────────────────────────────────────────────────
const Settings: FC = () => {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)

  // Single draft object instead of 8 individual useState
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [draft, setDraft] = useState<SettingsDraft>(DEFAULT_DRAFT)

  // Audit
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)

  // ── Data Loading ──
  const loadSettings = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${API}/api/settings`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setSettings(d.data || d)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载设置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadSettings() }, [loadSettings])

  // ── Edit Management ──
  const startEdit = (section: string) => {
    if (!settings) return
    setEditingSection(section)

    const next: SettingsDraft = { ...DEFAULT_DRAFT, ...draft }
    switch (section) {
      case 'tushare':
        next.tushare = settings.tushare_token || ''
        break
      case 'qmt':
        next.qmtAddr = settings.qmt_bridge_address || ''
        next.qmtPort = settings.qmt_bridge_port || 0
        break
      case 'wecom':
        next.wecom = settings.wecom_webhook || ''
        break
      case 'risk':
        next.singlePct = settings.risk_max_single_position_pct ?? 20
        next.sectorPct = settings.risk_max_sector_concentration_pct ?? 30
        next.stopLoss = settings.risk_stop_loss_pct ?? 10
        break
      case 'permissions':
        next.permissions = settings.account_permissions || []
        break
    }
    setDraft(next)
  }

  const cancelEdit = () => {
    setEditingSection(null)
  }

  // ── Save ──
  const saveSection = async (section: string, key: string, value: unknown) => {
    setSaving(section)
    try {
      const r = await fetch(`${API}/api/settings/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      })
      if (!r.ok) {
        const errBody = await r.json().catch(() => ({}))
        throw new Error((errBody as Record<string, unknown>).error as string || `HTTP ${r.status}`)
      }
      message.success(`${getSectionLabel(section)} 已更新`)
      setEditingSection(null)
      loadSettings()
    } catch (e: unknown) {
      message.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(null)
    }
  }

  const saveTushare = () => saveSection('tushare', 'tushare_token', draft.tushare)
  const saveQmtAddr = () => saveSection('qmt', 'qmt_bridge_address', draft.qmtAddr)
  const saveQmtPort = () => saveSection('qmt', 'qmt_bridge_port', draft.qmtPort)
  const saveWecom = () => saveSection('wecom', 'wecom_webhook', draft.wecom)
  const saveRiskSingle = () => saveSection('risk', 'risk_max_single_position_pct', draft.singlePct)
  const saveRiskSector = () => saveSection('risk', 'risk_max_sector_concentration_pct', draft.sectorPct)
  const saveRiskStopLoss = () => saveSection('risk', 'risk_stop_loss_pct', draft.stopLoss)
  const savePermissions = () => saveSection('permissions', 'account_permissions', draft.permissions)

  // ── Audit ──
  const loadAuditLogs = async () => {
    setAuditLoading(true)
    try {
      const r = await fetch(`${API}/api/audit/logs?limit=50`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setAuditLogs(d.data || d.logs || d.items || [])
      setAuditOpen(true)
    } catch (e: unknown) {
      message.error(`加载审计日志失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setAuditLoading(false)
    }
  }

  const exportAudit = async () => {
    setExportLoading(true)
    try {
      const r = await fetch(`${API}/api/audit/export`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit-export-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
      message.success('审计日志导出成功')
    } catch (e: unknown) {
      message.error(`导出失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setExportLoading(false)
    }
  }

  // ── Loading / Error ──
  if (loading && !settings) {
    return <Spin style={{ display: 'block', marginTop: 80 }} />
  }

  if (error && !settings) {
    return <Alert message="加载失败" description={error} type="error" showIcon style={{ margin: 24 }} />
  }

  // ── Render sections ──

  const renderEditButtons = (section: string, onSave: () => void) => (
    editingSection === section ? (
      <>
        <Button size="small" onClick={cancelEdit}>取消</Button>
        <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving === section} onClick={onSave}>保存</Button>
      </>
    ) : (
      <Button size="small" icon={<EditOutlined />} onClick={() => startEdit(section)}>编辑</Button>
    )
  )

  const renderTushareSection = () => (
    <Card style={CARD_STYLE} key="tushare">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Space>
            <ApiOutlined style={{ color: '#2563EB', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>数据源设置</Title>
          </Space>
          <div style={{ marginTop: 12 }}>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={<Text style={{ color: '#64748B' }}>Tushare Token</Text>}>
                {editingSection === 'tushare' ? (
                  <Input.Password
                    value={draft.tushare}
                    onChange={e => setDraft(p => ({ ...p, tushare: e.target.value }))}
                    placeholder="输入新的 Tushare Token"
                    style={{ width: 320 }}
                    iconRender={visible => (visible ? <EyeOutlined /> : <EyeInvisibleOutlined />)}
                  />
                ) : (
                  <Space>
                    <code style={{ color: '#64748B', fontSize: 13, letterSpacing: 1 }}>
                      {maskToken(settings?.tushare_token)}
                    </code>
                    <Tag color={settings?.tushare_token ? 'success' : 'default'} style={{ fontSize: 11 }}>
                      {settings?.tushare_token ? '已配置' : '未配置'}
                    </Tag>
                  </Space>
                )}
              </Descriptions.Item>
            </Descriptions>
          </div>
        </div>
        <Space>
          {renderEditButtons('tushare', saveTushare)}
        </Space>
      </div>
    </Card>
  )

  const renderQmtSection = () => (
    <Card style={CARD_STYLE} key="qmt">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Space>
            <LinkOutlined style={{ color: '#7C3AED', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>QMT Bridge 设置</Title>
          </Space>
          {editingSection === 'qmt' ? (
            <div style={{ marginTop: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <div>
                <Text style={{ color: '#64748B', fontSize: 12, display: 'block', marginBottom: 4 }}>地址</Text>
                <Input
                  value={draft.qmtAddr}
                  onChange={e => setDraft(p => ({ ...p, qmtAddr: e.target.value }))}
                  placeholder="127.0.0.1"
                  style={{ width: 200 }}
                />
              </div>
              <div>
                <Text style={{ color: '#64748B', fontSize: 12, display: 'block', marginBottom: 4 }}>端口</Text>
                <InputNumber
                  value={draft.qmtPort}
                  onChange={v => setDraft(p => ({ ...p, qmtPort: v ?? 0 }))}
                  min={1} max={65535}
                  style={{ width: 120 }}
                />
              </div>
              <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving === 'qmt'} onClick={saveQmtAddr} style={{ marginTop: 18 }}>保存地址</Button>
              <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving === 'qmt'} onClick={saveQmtPort} style={{ marginTop: 18 }}>保存端口</Button>
            </div>
          ) : (
            <div style={{ marginTop: 12 }}>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label={<Text style={{ color: '#64748B' }}>连接地址</Text>}>
                  <code style={{ color: '#475569', fontSize: 13 }}>{maskAddress(settings?.qmt_bridge_address)}</code>
                </Descriptions.Item>
                <Descriptions.Item label={<Text style={{ color: '#64748B' }}>端口</Text>}>
                  <code style={{ color: '#475569', fontSize: 13 }}>{settings?.qmt_bridge_port ?? '—'}</code>
                </Descriptions.Item>
              </Descriptions>
            </div>
          )}
        </div>
        {editingSection !== 'qmt' && (
          <Button size="small" icon={<EditOutlined />} onClick={() => startEdit('qmt')}>编辑</Button>
        )}
      </div>
    </Card>
  )

  const renderWecomSection = () => (
    <Card style={CARD_STYLE} key="wecom">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Space>
            <ThunderboltOutlined style={{ color: '#D97706', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>企业微信设置</Title>
          </Space>
          <div style={{ marginTop: 12 }}>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={<Text style={{ color: '#64748B' }}>Webhook URL</Text>}>
                {editingSection === 'wecom' ? (
                  <Input.Password
                    value={draft.wecom}
                    onChange={e => setDraft(p => ({ ...p, wecom: e.target.value }))}
                    placeholder="输入新的 Webhook URL"
                    style={{ width: 420 }}
                    iconRender={visible => (visible ? <EyeOutlined /> : <EyeInvisibleOutlined />)}
                  />
                ) : (
                  <Space>
                    <code style={{ color: '#64748B', fontSize: 13, letterSpacing: 1 }}>
                      {maskWebhook(settings?.wecom_webhook)}
                    </code>
                    <Tag color={settings?.wecom_webhook ? 'success' : 'default'} style={{ fontSize: 11 }}>
                      {settings?.wecom_webhook ? '已配置' : '未配置'}
                    </Tag>
                    <Text style={{ color: '#94A3B8', fontSize: 11 }}>仅显示末尾4位</Text>
                  </Space>
                )}
              </Descriptions.Item>
            </Descriptions>
          </div>
        </div>
        <Space>
          {renderEditButtons('wecom', saveWecom)}
        </Space>
      </div>
    </Card>
  )

  const renderRiskSection = () => (
    <Card style={CARD_STYLE} key="risk">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <Space>
            <WarningOutlined style={{ color: '#DC2626', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>风险阈值设置</Title>
          </Space>
          <div style={{ marginTop: 12, maxWidth: 500 }}>
            {editingSection === 'risk' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <Text style={{ color: '#475569', fontSize: 13 }}>单票仓位上限: <strong>{draft.singlePct}%</strong></Text>
                  <InputNumber value={draft.singlePct} onChange={v => setDraft(p => ({ ...p, singlePct: v ?? 0 }))} min={1} max={100} formatter={v => `${v}%`} parser={v => Number(v?.replace('%', '') || 0)} style={{ width: 120, marginLeft: 12 }} />
                  <Button size="small" type="primary" ghost icon={<SaveOutlined />} loading={saving === 'risk'} onClick={saveRiskSingle} style={{ marginLeft: 8 }} />
                </div>
                <div>
                  <Text style={{ color: '#475569', fontSize: 13 }}>行业集中度上限: <strong>{draft.sectorPct}%</strong></Text>
                  <InputNumber value={draft.sectorPct} onChange={v => setDraft(p => ({ ...p, sectorPct: v ?? 0 }))} min={1} max={100} formatter={v => `${v}%`} parser={v => Number(v?.replace('%', '') || 0)} style={{ width: 120, marginLeft: 12 }} />
                  <Button size="small" type="primary" ghost icon={<SaveOutlined />} loading={saving === 'risk'} onClick={saveRiskSector} style={{ marginLeft: 8 }} />
                </div>
                <div>
                  <Text style={{ color: '#475569', fontSize: 13 }}>止损线: <strong>{draft.stopLoss}%</strong></Text>
                  <InputNumber value={draft.stopLoss} onChange={v => setDraft(p => ({ ...p, stopLoss: v ?? 0 }))} min={1} max={50} formatter={v => `${v}%`} parser={v => Number(v?.replace('%', '') || 0)} style={{ width: 120, marginLeft: 12 }} />
                  <Button size="small" type="primary" ghost icon={<SaveOutlined />} loading={saving === 'risk'} onClick={saveRiskStopLoss} style={{ marginLeft: 8 }} />
                </div>
              </div>
            ) : (
              <Descriptions size="small" column={3}>
                <Descriptions.Item label={<Text style={{ color: '#64748B' }}>单票仓位上限</Text>}>
                  <Text strong style={{ color: '#0F172A' }}>{settings?.risk_max_single_position_pct ?? '—'}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label={<Text style={{ color: '#64748B' }}>行业集中度上限</Text>}>
                  <Text strong style={{ color: '#0F172A' }}>{settings?.risk_max_sector_concentration_pct ?? '—'}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label={<Text style={{ color: '#64748B' }}>止损线</Text>}>
                  <Text strong style={{ color: '#0F172A' }}>{settings?.risk_stop_loss_pct ?? '—'}%</Text>
                </Descriptions.Item>
              </Descriptions>
            )}
          </div>
        </div>
        {editingSection !== 'risk' && (
          <Button size="small" icon={<EditOutlined />} onClick={() => startEdit('risk')}>编辑</Button>
        )}
      </div>
    </Card>
  )

  const renderPermissionsSection = () => (
    <Card style={CARD_STYLE} key="permissions">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Space>
            <LockOutlined style={{ color: '#059669', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>账户权限设置</Title>
          </Space>
          <div style={{ marginTop: 12 }}>
            {editingSection === 'permissions' ? (
              <Space wrap>
                {AVAILABLE_PERMISSIONS.map(p => (
                  <Tag
                    key={p.key}
                    color={draft.permissions.includes(p.key) ? 'blue' : 'default'}
                    style={{ cursor: 'pointer', padding: '2px 12px', fontSize: 13 }}
                    onClick={() => {
                      setDraft(prev => ({
                        ...prev,
                        permissions: prev.permissions.includes(p.key)
                          ? prev.permissions.filter(k => k !== p.key)
                          : [...prev.permissions, p.key]
                      }))
                    }}
                  >
                    {draft.permissions.includes(p.key) ? '✓ ' : ''}{p.label}
                  </Tag>
                ))}
                <Divider type="vertical" />
                <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving === 'permissions'} onClick={savePermissions}>保存</Button>
                <Button size="small" onClick={cancelEdit}>取消</Button>
              </Space>
            ) : (
              <Space wrap>
                {(settings?.account_permissions?.length ?? 0) > 0 ? (
                  settings?.account_permissions?.map(p => (
                    <Tag key={p} color="blue" style={{ fontSize: 12 }}>{p}</Tag>
                  ))
                ) : (
                  <Text style={{ color: '#94A3B8' }}>未设置权限</Text>
                )}
              </Space>
            )}
          </div>
        </div>
        {editingSection !== 'permissions' && (
          <Button size="small" icon={<EditOutlined />} onClick={() => startEdit('permissions')}>编辑</Button>
        )}
      </div>
    </Card>
  )

  const renderTokenSecuritySection = () => (
    <Card style={CARD_STYLE} key="token-security">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Space>
            <KeyOutlined style={{ color: '#7C3AED', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>Token 安全</Title>
          </Space>
          <div style={{ marginTop: 12 }}>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={<Text style={{ color: '#64748B' }}>HERMES_UI_TOKEN</Text>}>
                <Space>
                  {settings?.hermes_ui_token_status === 'set' ? (
                    <>
                      <CheckCircleOutlined style={{ color: '#059669' }} />
                      <Tag color="success" style={{ fontSize: 12 }}>已设置</Tag>
                    </>
                  ) : (
                    <>
                      <CloseCircleOutlined style={{ color: '#DC2626' }} />
                      <Tag color="error" style={{ fontSize: 12 }}>未设置</Tag>
                      <Text style={{ color: '#94A3B8', fontSize: 12 }}>建议通过环境变量 HERMES_UI_TOKEN 设置</Text>
                    </>
                  )}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          </div>
        </div>
        <Tooltip title="Token 状态为只读，请在服务端环境变量中配置">
          <SafetyOutlined style={{ color: '#94A3B8', fontSize: 20 }} />
        </Tooltip>
      </div>
    </Card>
  )

  const renderAuditSection = () => (
    <Card style={CARD_STYLE} key="audit">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Space>
            <FileSearchOutlined style={{ color: '#2563EB', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0, color: '#0F172A' }}>审计日志</Title>
          </Space>
          <div style={{ marginTop: 8 }}>
            <Text style={{ color: '#64748B', fontSize: 13 }}>查看和导出系统审计日志，追踪所有配置变更记录。</Text>
          </div>
        </div>
        <Space>
          <Button icon={<FileSearchOutlined />} onClick={loadAuditLogs} loading={auditLoading}>查看审计日志</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={exportAudit} loading={exportLoading}>导出审计日志</Button>
        </Space>
      </div>
    </Card>
  )

  // ── Main Render ──
  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0, color: '#0F172A' }}>
          <SafetyOutlined style={{ marginRight: 8, color: '#2563EB' }} />
          设置
        </Title>
        <Space>
          <Text style={{ color: '#94A3B8', fontSize: 12 }}>所有设置变更将自动记录审计日志</Text>
          <Button icon={<ReloadOutlined />} onClick={loadSettings} loading={loading}>刷新</Button>
        </Space>
      </div>

      {error && <Alert message={error} type="error" showIcon closable style={{ marginBottom: 16 }} />}

      {/* Settings Sections */}
      {renderTushareSection()}
      {renderQmtSection()}
      {renderWecomSection()}
      {renderRiskSection()}
      {renderPermissionsSection()}
      {renderTokenSecuritySection()}
      {renderAuditSection()}

      {/* ── Audit Log Modal ── */}
      <Modal
        title={<span><FileSearchOutlined /> 审计日志</span>}
        open={auditOpen}
        onCancel={() => setAuditOpen(false)}
        footer={null}
        width={800}
      >
        {auditLoading ? (
          <Spin style={{ display: 'block', marginTop: 40 }} />
        ) : auditLogs.length === 0 ? (
          <div style={{ padding: 40 }}><Empty description="暂无审计日志" /></div>
        ) : (
          <div>
            {auditLogs.map((log, i) => (
              <div
                key={log.id || i}
                style={{
                  padding: '8px 12px',
                  background: i % 2 === 0 ? '#F8FAFC' : '#FFFFFF',
                  borderBottom: '1px solid #E2E8F0',
                  fontSize: 13,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <Tag color="geekblue" style={{ fontSize: 11 }}>{log.action}</Tag>
                  <Text style={{ color: '#475569' }}>{log.target}</Text>
                  {log.detail && (
                    <Text style={{ color: '#94A3B8', fontSize: 11, marginLeft: 8 }}>— {log.detail}</Text>
                  )}
                </div>
                <div>
                  <Text style={{ color: '#94A3B8', fontSize: 11 }}>
                    {log.user} · {log.created_at?.slice(0, 16).replace('T', ' ')}
                  </Text>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}

export default Settings
