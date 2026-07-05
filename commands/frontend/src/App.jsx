import { useState } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  SearchOutlined,
  BookOutlined,
  SettingOutlined,
} from '@ant-design/icons'

import Dashboard from './pages/Dashboard'
import AgentConsole from './pages/AgentConsole'
import Research from './pages/Research'
import KnowledgeBase from './pages/KnowledgeBase'
import Settings from './pages/Settings'

const { Sider, Content, Header } = Layout

const MENU_ITEMS = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: <NavLink to="/" end>总览</NavLink>,
  },
  {
    key: '/console',
    icon: <RobotOutlined />,
    label: <NavLink to="/console">智能体控制台</NavLink>,
  },
  {
    key: '/research',
    icon: <SearchOutlined />,
    label: <NavLink to="/research">研究</NavLink>,
  },
  {
    key: '/knowledge',
    icon: <BookOutlined />,
    label: <NavLink to="/knowledge">知识库</NavLink>,
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: <NavLink to="/settings">设置</NavLink>,
  },
]

export default function App() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        style={{
          borderRight: '1px solid #f0f0f0',
          boxShadow: '2px 0 8px rgba(0,0,0,0.04)',
        }}
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Typography.Title level={4} style={{ margin: 0, whiteSpace: 'nowrap' }}>
            {collapsed ? '🧠' : '🧠 Research Assistant'}
          </Typography.Title>
        </div>
        <Menu
          mode="inline"
          defaultSelectedKeys={['/']}
          items={MENU_ITEMS}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>

      <Layout>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/console" element={<AgentConsole />} />
            <Route path="/research" element={<Research />} />
            <Route path="/knowledge" element={<KnowledgeBase />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
