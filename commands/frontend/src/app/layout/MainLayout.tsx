import React, { useState } from 'react'
import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopStatusBar from './TopStatusBar'
import AgentOpsDrawer from './AgentOpsDrawer'

const { Sider, Content } = Layout

const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false)
  const [agentOpsOpen, setAgentOpsOpen] = useState(false)

  return (
    <Layout style={{ minHeight: '100vh', background: '#F8FAFC' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={200}
        collapsedWidth={56}
        style={{
          background: '#0F172A',
          overflow: 'hidden',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100,
          transition: 'width 0.2s ease',
        }}
      >
        <Sidebar
          collapsed={collapsed}
          onOpenAgentOps={() => setAgentOpsOpen(true)}
        />
      </Sider>

      <Layout
        style={{
          marginLeft: collapsed ? 56 : 200,
          background: '#F8FAFC',
          transition: 'margin-left 0.2s ease',
        }}
      >
        <TopStatusBar />
        <Content
          style={{
            padding: 24,
            overflow: 'auto',
            animation: 'fadeIn 0.25s ease',
          }}
        >
          <Outlet />
        </Content>
      </Layout>

      <AgentOpsDrawer
        open={agentOpsOpen}
        onClose={() => setAgentOpsOpen(false)}
      />
    </Layout>
  )
}

export default MainLayout
