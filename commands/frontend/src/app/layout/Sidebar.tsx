import React from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Menu, Typography, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  DashboardOutlined,
  DatabaseOutlined,
  FundOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  BarChartOutlined,
  PieChartOutlined,
  DollarOutlined,
  WalletOutlined,
  SafetyOutlined,
  FileTextOutlined,
  AlertOutlined,
  SettingOutlined,
} from '@ant-design/icons'

interface SidebarProps {
  collapsed: boolean
  onOpenAgentOps: () => void
}

type MenuItem = Required<MenuProps>['items'][number]

const RESEARCH_MENU: MenuItem[] = [
  { key: '/', icon: <DashboardOutlined />, label: '首页' },
  { key: '/data', icon: <DatabaseOutlined />, label: '数据中心' },
  { key: '/stocks', icon: <FundOutlined />, label: '股票池' },
  { key: '/semi', icon: <ThunderboltOutlined />, label: '半导体主题' },
  { key: '/factors', icon: <ExperimentOutlined />, label: '因子实验室' },
  { key: '/backtest', icon: <BarChartOutlined />, label: '回测实验室' },
  { key: '/portfolio', icon: <PieChartOutlined />, label: '组合推荐' },
  { key: '/qmt', icon: <DollarOutlined />, label: 'QMT 实盘' },
  { key: '/paper', icon: <WalletOutlined />, label: 'Paper / Shadow' },
  { key: '/livegate', icon: <SafetyOutlined />, label: 'Live Gate' },
  { key: '/reports', icon: <FileTextOutlined />, label: '报告审计' },
  { key: '/events', icon: <AlertOutlined />, label: '事件研报' },
]

const Sidebar: React.FC<SidebarProps> = ({ collapsed, onOpenAgentOps }) => {
  const navigate = useNavigate()
  const location = useLocation()

  const handleClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key)
  }

  const selectedKey = '/' + location.pathname.split('/').filter(Boolean)[0]
  const activeKey = selectedKey === '/' ? '/' : location.pathname

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: '#0F172A',
      }}
    >
      {/* Logo / Brand */}
      <div
        style={{
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid #1E293B',
          transition: 'padding 0.2s ease',
        }}
      >
        <Typography.Title
          level={5}
          style={{
            margin: 0,
            color: '#FFFFFF',
            fontSize: collapsed ? 18 : 14,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
          }}
        >
          {collapsed ? (
            <Tooltip title="Hermes 投研系统" placement="right">
              <span>⚡</span>
            </Tooltip>
          ) : (
            '⚡ 投研系统'
          )}
        </Typography.Title>
      </div>

      {/* Research Navigation */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {collapsed ? (
          /* Collapsed mode: show icons with tooltips */
          <div style={{ padding: '4px 0' }}>
            {RESEARCH_MENU.map((item: any) => {
              const isActive = item.key === activeKey || (item.key !== '/' && activeKey.startsWith(item.key))
              return (
                <Tooltip key={item.key} title={item.label} placement="right">
                  <div
                    onClick={() => {
                      navigate(item.key)
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      height: 40,
                      margin: '2px 8px',
                      borderRadius: 8,
                      cursor: 'pointer',
                      color: isActive ? '#2563EB' : '#94A3B8',
                      background: isActive ? 'rgba(37,99,235,0.1)' : 'transparent',
                      transition: 'all 0.15s ease',
                      fontSize: 18,
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                        e.currentTarget.style.color = '#FFFFFF'
                      }
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = isActive ? 'rgba(37,99,235,0.1)' : 'transparent'
                      e.currentTarget.style.color = isActive ? '#2563EB' : '#94A3B8'
                    }}
                  >
                    {item.icon}
                  </div>
                </Tooltip>
              )
            })}
          </div>
        ) : (
          <Menu
            mode="inline"
            theme="dark"
            selectedKeys={[activeKey]}
            defaultSelectedKeys={['/']}
            items={RESEARCH_MENU}
            onClick={handleClick}
            style={{
              background: 'transparent',
              borderInlineEnd: 'none',
            }}
          />
        )}
      </div>

      {/* System & Automation Button */}
      <div
        style={{
          borderTop: '1px solid #1E293B',
          padding: collapsed ? '4px 0' : '8px 12px',
        }}
      >
        {collapsed ? (
          <Tooltip title="系统与自动化" placement="right">
            <div
              onClick={onOpenAgentOps}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 40,
                margin: '0 8px',
                borderRadius: 8,
                cursor: 'pointer',
                color: '#94A3B8',
                fontSize: 18,
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                e.currentTarget.style.color = '#FFFFFF'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.color = '#94A3B8'
              }}
            >
              <SettingOutlined />
            </div>
          </Tooltip>
        ) : (
          <Menu
            mode="inline"
            theme="dark"
            selectedKeys={[]}
            items={[
              {
                key: 'system-ops',
                icon: <SettingOutlined />,
                label: '系统与自动化',
              },
            ]}
            onClick={onOpenAgentOps}
            style={{ background: 'transparent', borderInlineEnd: 'none' }}
          />
        )}
      </div>
    </div>
  )
}

export default Sidebar
