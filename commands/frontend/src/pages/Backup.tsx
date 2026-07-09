import React from 'react'
import NotReadyState from '../components/common/NotReadyState'

const Backup: React.FC = () => (
  <NotReadyState
    title="备份恢复"
    description="系统配置和数据备份管理。"
    suggestions={[
      '确认备份服务 API 可用',
      '配置备份策略和存储位置',
    ]}
  />
)

export default Backup
