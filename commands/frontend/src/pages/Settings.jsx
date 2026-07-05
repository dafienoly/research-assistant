import { useState } from 'react'
import {
  Card,
  Tabs,
  Form,
  Input,
  Switch,
  Select,
  Button,
  InputNumber,
  Divider,
  Typography,
  Space,
  message,
  Segmented,
} from 'antd'
import {
  SettingOutlined,
  ApiOutlined,
  BellOutlined,
  SafetyOutlined,
  SaveOutlined,
} from '@ant-design/icons'

const { Text, Title } = Typography

export default function Settings() {
  const [activeTab, setActiveTab] = useState('general')
  const [saving, setSaving] = useState(false)

  const [generalForm] = Form.useForm()
  const [apiForm] = Form.useForm()

  // LLM provider list
  const LLM_PROVIDERS = [
    { label: 'OpenAI', value: 'openai' },
    { label: 'Anthropic', value: 'anthropic' },
    { label: 'DeepSeek', value: 'deepseek' },
    { label: 'Ollama (本地)', value: 'ollama' },
    { label: '自定义', value: 'custom' },
  ]

  const handleSave = (formName) => {
    setSaving(true)
    // Simulate saving
    setTimeout(() => {
      setSaving(false)
      message.success('设置已保存')
    }, 500)
  }

  const TAB_ITEMS = [
    {
      key: 'general',
      label: (
        <span>
          <SettingOutlined /> 通用
        </span>
      ),
      children: (
        <Form
          form={generalForm}
          layout="vertical"
          initialValues={{
            appName: 'Research Assistant',
            language: 'zh-CN',
            maxHistory: 100,
            autoSave: true,
            darkMode: false,
          }}
          style={{ maxWidth: 480 }}
        >
          <Form.Item label="应用名称" name="appName">
            <Input />
          </Form.Item>
          <Form.Item label="界面语言" name="language">
            <Select
              options={[
                { label: '简体中文', value: 'zh-CN' },
                { label: 'English', value: 'en-US' },
                { label: '日本語', value: 'ja-JP' },
              ]}
            />
          </Form.Item>
          <Form.Item label="最大历史记录数" name="maxHistory">
            <InputNumber min={10} max={1000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="自动保存" name="autoSave" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="深色模式" name="darkMode" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={() => handleSave('general')}
            >
              保存设置
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'api',
      label: (
        <span>
          <ApiOutlined /> API
        </span>
      ),
      children: (
        <Form
          form={apiForm}
          layout="vertical"
          initialValues={{
            llmProvider: 'deepseek',
            apiKey: '',
            apiBase: '',
            maxTokens: 4096,
            temperature: 0.7,
          }}
          style={{ maxWidth: 480 }}
        >
          <Form.Item label="LLM 提供商" name="llmProvider">
            <Select options={LLM_PROVIDERS} />
          </Form.Item>
          <Form.Item label="API Key" name="apiKey">
            <Input.Password placeholder="输入 API Key" />
          </Form.Item>
          <Form.Item label="API 地址 (可选)" name="apiBase">
            <Input placeholder="https://api.example.com/v1" />
          </Form.Item>
          <Form.Item label="最大 Token 数" name="maxTokens">
            <InputNumber min={256} max={32768} step={256} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="温度 (Temperature)" name="temperature">
            <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={() => handleSave('api')}
            >
              保存 API 设置
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'notifications',
      label: (
        <span>
          <BellOutlined /> 通知
        </span>
      ),
      children: (
        <div style={{ maxWidth: 480 }}>
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>任务完成通知</Text>
                  <br />
                  <Text type="secondary">智能体任务完成后推送通知</Text>
                </div>
                <Switch defaultChecked />
              </div>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>错误告警</Text>
                  <br />
                  <Text type="secondary">任务执行出错时推送告警</Text>
                </div>
                <Switch defaultChecked />
              </div>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>研究报告更新</Text>
                  <br />
                  <Text type="secondary">有新研究报告生成时通知</Text>
                </div>
                <Switch defaultChecked />
              </div>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>系统更新</Text>
                  <br />
                  <Text type="secondary">系统版本升级与维护通知</Text>
                </div>
                <Switch />
              </div>
            </div>
            <Button type="primary" icon={<SaveOutlined />}>
              保存通知设置
            </Button>
          </Space>
        </div>
      ),
    },
    {
      key: 'security',
      label: (
        <span>
          <SafetyOutlined /> 安全
        </span>
      ),
      children: (
        <div style={{ maxWidth: 480 }}>
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>数据加密存储</Text>
                  <br />
                  <Text type="secondary">对本地缓存的研究数据进行加密</Text>
                </div>
                <Switch defaultChecked />
              </div>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>会话超时</Text>
                  <br />
                  <Text type="secondary">闲置超过指定时间后自动登出</Text>
                </div>
                <Select
                  defaultValue="30m"
                  size="small"
                  style={{ width: 100 }}
                  options={[
                    { label: '15分钟', value: '15m' },
                    { label: '30分钟', value: '30m' },
                    { label: '1小时', value: '1h' },
                    { label: '4小时', value: '4h' },
                    { label: '永不', value: 'never' },
                  ]}
                />
              </div>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <Text strong>日志记录级别</Text>
                  <br />
                  <Text type="secondary">控制控制台日志的详细程度</Text>
                </div>
                <Select
                  defaultValue='info'
                  size="small"
                  style={{ width: 100 }}
                  options={[
                    { label: 'Debug', value: 'debug' },
                    { label: 'Info', value: 'info' },
                    { label: 'Warning', value: 'warn' },
                    { label: 'Error', value: 'error' },
                  ]}
                />
              </div>
            </div>
            <Button type="primary" icon={<SaveOutlined />}>
              保存安全设置
            </Button>
          </Space>
        </div>
      ),
    },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>
        <SettingOutlined style={{ marginRight: 8 }} />
        设置
      </h2>

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={TAB_ITEMS}
          tabPosition="left"
          style={{ minHeight: 400 }}
        />
      </Card>
    </div>
  )
}
