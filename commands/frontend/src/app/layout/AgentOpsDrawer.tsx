import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Drawer, Menu, Typography, Divider } from 'antd'
import type { MenuProps } from 'antd'
import {
  RobotOutlined,
  ForkOutlined,
  ToolOutlined,
  HistoryOutlined,
  CommentOutlined,
  CloudUploadOutlined,
  SettingOutlined,
  CheckSquareOutlined,
} from '@ant-design/icons'

interface AgentOpsDrawerProps {
  open: boolean
  onClose: () => void
}

const SYSTEM_MENU: MenuProps['items'] = [
  { key: '/console', icon: <RobotOutlined />, label: 'Agent Console' },
  { key: '/roadmap', icon: <ForkOutlined />, label: '路线图' },
  { key: '/tasks', icon: <CheckSquareOutlined />, label: '任务中心' },
  { key: '/ops', icon: <ToolOutlined />, label: '运维中心' },
  { key: '/history', icon: <HistoryOutlined />, label: 'Session 历史' },
  { key: '/feedback', icon: <CommentOutlined />, label: '反馈' },
  { key: '/backup', icon: <CloudUploadOutlined />, label: '备份恢复' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
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
          ⚙ 系统与自动化
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
          这些功能与投研系统独立，用于管理 Hermes 自动版本推进、Agent 会话和运维操作。
        </Typography.Text>
      </div>
    </Drawer>
  )
}

export default AgentOpsDrawer
