import { SettingOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Form, Input, Row, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';

import { api } from '../api';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { ModelSettings } from '../types';

const { Text, Paragraph } = Typography;

export default function Settings() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const { loading, run } = useAsyncAction();

  const refresh = async () => setSettings(await api.getModelSettings());

  useEffect(() => {
    void run(refresh);
  }, []);

  return (
    <Space direction="vertical" size="large" className="full-width">
      <Alert
        type="warning"
        showIcon
        message="API Key 只保存在当前后端进程内存中"
        description="这里设置的密钥不会写入仓库、README、.env.example 或前端本地存储；后端重启后需要重新填写。生产环境建议使用环境变量 MODEL_API_KEY 或密钥管理服务。"
      />
      <Card title="模型设置" extra={<Button onClick={() => void run(refresh)}>刷新</Button>}>
        <Form
          layout="vertical"
          initialValues={{
            base_url: settings?.base_url ?? 'https://ark.cn-beijing.volces.com/api/v3',
            model: settings?.model ?? 'doubao-seed-2-0-code-preview-260215'
          }}
          onFinish={(values: { base_url: string; model: string; api_key?: string }) =>
            void run(async () => {
              const payload = {
                base_url: values.base_url,
                model: values.model,
                ...(values.api_key ? { api_key: values.api_key } : {})
              };
              setSettings(await api.updateModelSettings(payload));
            }, '模型设置已更新')
          }
          key={`${settings?.base_url ?? ''}-${settings?.model ?? ''}`}
        >
          <Row gutter={16}>
            <Col xs={24} lg={12}>
              <Form.Item
                name="base_url"
                label="Base URL"
                tooltip="火山方舟 OpenAI 兼容接口默认是 https://ark.cn-beijing.volces.com/api/v3"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} lg={12}>
              <Form.Item
                name="model"
                label="模型名称"
                tooltip="当前默认模型是 doubao-seed-2-0-code-preview-260215"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="api_key"
            label="API Key"
            tooltip="留空表示不修改当前密钥；若后端刚启动且未设置环境变量，需要在这里填入密钥。"
          >
            <Input.Password placeholder="ark-..." autoComplete="off" />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={loading} icon={<SettingOutlined />}>
              保存设置
            </Button>
            <Tag color={settings?.api_key_configured ? 'green' : 'red'}>
              {settings?.api_key_configured ? '已配置 API Key' : '未配置 API Key'}
            </Tag>
          </Space>
        </Form>
      </Card>
      <Card title="怎么用">
        <Paragraph>
          1. 填写或确认 <Text code>Base URL</Text> 与 <Text code>模型名称</Text>。
        </Paragraph>
        <Paragraph>2. 填写 API Key 并保存。保存后前往"模型调用"页测试。</Paragraph>
        <Paragraph>
          3. 如果模型调用返回 502，通常是上游接口鉴权失败、模型名不正确或网络不可达。
        </Paragraph>
      </Card>
    </Space>
  );
}
