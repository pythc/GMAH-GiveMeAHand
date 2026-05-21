import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Descriptions, Form, Input, Row, Space, Tag, Typography } from 'antd';
import { useState } from 'react';

import { api } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { JsonObject } from '../types';

const { Title, Paragraph, Text } = Typography;

interface AuthState {
  token: string;
  user: JsonObject;
}

export default function Login() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [apiKeyResult, setApiKeyResult] = useState<JsonObject | null>(null);
  const { loading, run } = useAsyncAction();

  const handleLogin = async (values: { username: string; password: string }) => {
    const result = await api.login(values.username, values.password);
    setAuth(result as unknown as AuthState);
    // Store token for subsequent API calls
    if (result?.token) {
      localStorage.setItem('auth_token', result.token as string);
    }
  };

  const handleLogout = () => {
    setAuth(null);
    setApiKeyResult(null);
    localStorage.removeItem('auth_token');
  };

  return (
    <Space direction="vertical" size="large" className="full-width">
      <Alert
        type="info"
        showIcon
        message="认证管理"
        description="当后端开启 AUTH_ENABLED=true 时，所有 API 请求需要携带 JWT Token 或 API Key。默认关闭时此页面仅供测试。"
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card title="登录">
            <Form
              layout="vertical"
              initialValues={{ username: 'admin', password: 'admin' }}
              onFinish={(values: { username: string; password: string }) =>
                void run(async () => {
                  await handleLogin(values);
                }, '登录成功')
              }
            >
              <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                <Input prefix={<UserOutlined />} />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                <Input.Password prefix={<LockOutlined />} />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={loading}>
                  登录获取 Token
                </Button>
                {auth && (
                  <Button danger onClick={handleLogout}>
                    退出
                  </Button>
                )}
              </Space>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card title="认证状态">
            {auth ? (
              <Space direction="vertical" className="full-width">
                <Tag color="green">已认证</Tag>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="Token">
                    <Text copyable ellipsis style={{ maxWidth: 400 }}>
                      {auth.token}
                    </Text>
                  </Descriptions.Item>
                </Descriptions>
                <JsonPreview value={auth.user} />
              </Space>
            ) : (
              <Alert message="未登录。使用左侧表单获取 JWT Token。" type="warning" showIcon />
            )}
          </Card>
        </Col>
      </Row>

      {auth && (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card title="生成 API Key">
              <Paragraph>
                API Key 可以代替 JWT Token 进行认证，适合程序化访问或自动化集成。
              </Paragraph>
              <Button
                type="primary"
                onClick={() =>
                  void run(async () => {
                    const result = await api.generateApiKey();
                    setApiKeyResult(result);
                  }, 'API Key 已生成')
                }
                loading={loading}
              >
                生成新 API Key
              </Button>
              {apiKeyResult && (
                <>
                  <Alert
                    className="result-table"
                    type="success"
                    showIcon
                    message="请立即保存此 API Key，关闭后无法再次查看"
                  />
                  <JsonPreview value={apiKeyResult} />
                </>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="使用说明">
              <Title level={5}>JWT Token</Title>
              <Paragraph>
                <Text code>Authorization: Bearer {'<token>'}</Text>
              </Paragraph>
              <Title level={5}>API Key</Title>
              <Paragraph>
                <Text code>X-API-Key: {'<api_key>'}</Text>
              </Paragraph>
              <Paragraph>或</Paragraph>
              <Paragraph>
                <Text code>Authorization: Bearer {'<api_key>'}</Text>
              </Paragraph>
            </Card>
          </Col>
        </Row>
      )}
    </Space>
  );
}
