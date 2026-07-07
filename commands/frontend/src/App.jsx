import { useState } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined, RobotOutlined, ForkOutlined, FileTextOutlined, HistoryOutlined, DatabaseOutlined
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import AgentConsole from './pages/AgentConsole'
import Roadmap from './pages/Roadmap'
import Reports from './pages/Reports'
import SessionHistory from './pages/SessionHistory'
import DataStatus from './pages/DataStatus'

const API = 'http://127.0.0.1:8766'
export { API }

const { Sider, Content } = Layout

const MENU = [
  { key: '/', icon: <DashboardOutlined />, label: <NavLink to="/" end>总览</NavLink> },
  { key: '/data', icon: <DatabaseOutlined />, label: <NavLink to="/data">数据状态</NavLink> },
  { key: '/console', icon: <RobotOutlined />, label: <NavLink to="/console">Agent Console</NavLink> },
  { key: '/roadmap', icon: <ForkOutlined />, label: <NavLink to="/roadmap">路线图</NavLink> },
  { key: '/reports', icon: <FileTextOutlined />, label: <NavLink to="/reports">版本报告</NavLink> },
  { key: '/history', icon: <HistoryOutlined />, label: <NavLink to="/history">Session 历史</NavLink> },
]

export default function App() {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <Layout style={{ minHeight: '100vh', background: '#F8FAFC' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}
        theme="dark" width={200}
        style={{ background: '#0F172A', borderRight: '1px solid #E2E8F0' }}>
        <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center', borderBottom: '1px solid #1E293B' }}>
          <Typography.Title level={5} style={{ margin: 0, color: '#FFFFFF', fontSize: 14 }}>
            {collapsed ? '⚡' : '⚡ Hermes Dashboard'}
          </Typography.Title>
        </div>
        <Menu mode="inline" theme="dark" defaultSelectedKeys={['/']}
          items={MENU} style={{ background: 'transparent', borderInlineEnd: 'none' }} />
      </Sider>
      <Layout style={{ background: '#F8FAFC' }}>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/data" element={<DataStatus />} />
            <Route path="/console" element={<AgentConsole />} />
            <Route path="/roadmap" element={<Roadmap />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/history" element={<SessionHistory />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
