import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Drawer, Menu, Typography, Divider } from 'antd'
import type { MenuProps } from 'antd'
import {
  ToolOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'

interface AgentOpsDrawerProps {
  open: boolean
  onClose: () => void
}

const SYSTEM_MENU: MenuProps['items'] = [
  { key: '/ops', icon: <ToolOutlined />, label: '运维中心' },
  { key: '/code-audit', icon: <SafetyCertificateOutlined />, label: '代码审计中心' },
]

const AgentOpsDrawer: React.FC<AgentOpsDrawerProps> = ({ open, onClose }) => {
  const navigate = useNavigate()

  const handleClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key)
    onClose()
  }

  return (
    <Drawer
      title={
        <Typography.Text strong style={{ fontSize: 16 }}>
          ⚙ 系统中心
        </Typography.Text>
      }
      placement="left"
      onClose={onClose}
      open={open}
      width={280}
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ padding: '12px 0' }}>
        <Typography.Text
          type="secondary"
          style={{ fontSize: 11, padding: '0 24px', display: 'block', marginBottom: 4 }}
        >
          系统管理
        </Typography.Text>
        <Menu
          mode="inline"
          items={SYSTEM_MENU}
          onClick={handleClick}
          style={{ borderInlineEnd: 'none' }}
        />
      </div>

      <Divider style={{ margin: '8px 0' }} />

      <div style={{ padding: '12px 24px' }}>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          投研系统之外仅保留本地运维和代码质量审计。
        </Typography.Text>
      </div>
    </Drawer>
  )
}

export default AgentOpsDrawer
