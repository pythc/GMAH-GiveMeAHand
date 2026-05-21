import { ApiOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Form, Input, Row, Select, Table, Tag } from 'antd';
import { useState } from 'react';

import { api, parseJsonObject } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { JsonObject, McpCapability } from '../types';

const { TextArea } = Input;

export default function Mcp() {
  const [capabilities, setCapabilities] = useState<McpCapability[]>([]);
  const [result, setResult] = useState<JsonObject | null>(null);
  const { loading, run } = useAsyncAction();
  const toolPayload = JSON.stringify(
    {
      server_name: 'grading-system',
      tool_name: 'fetch_submission',
      arguments: { submission_id: 'submission-1' }
    },
    null,
    2
  );

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card
          title="MCP 能力"
          extra={
            <Button
              loading={loading}
              onClick={() =>
                void run(async () => {
                  setCapabilities(await api.listMcpCapabilities());
                }, 'MCP 能力已刷新')
              }
            >
              发现能力
            </Button>
          }
        >
          <Alert
            className="section-help"
            type="info"
            showIcon
            message="MCP 是外部系统接入层"
            description="这里会根据 configs/mcp-servers.example.yaml 中的 allowlist 发现 tools/resources/prompts。远程 MCP server 未启动时会显示 502 连接错误。"
          />
          <Table
            rowKey={(record) => `${record.server_name}-${record.primitive}-${record.name}`}
            dataSource={capabilities}
            columns={[
              { title: 'Server', dataIndex: 'server_name' },
              {
                title: '类型',
                dataIndex: 'primitive',
                render: (value) => <Tag>{value}</Tag>
              },
              { title: '名称', dataIndex: 'name' },
              { title: '说明', dataIndex: 'description' }
            ]}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="MCP 调用">
          <Form
            layout="vertical"
            initialValues={{ payload: toolPayload, kind: 'tool' }}
            onFinish={(values: { payload: string; kind: 'tool' | 'resource' }) =>
              void run(async () => {
                const payload = parseJsonObject(values.payload);
                setResult(
                  values.kind === 'tool'
                    ? await api.callMcpTool(payload)
                    : await api.readMcpResource(payload)
                );
              }, 'MCP 调用完成')
            }
          >
            <Form.Item name="kind" label="调用类型">
              <Select
                options={[
                  { label: 'Tool', value: 'tool' },
                  { label: 'Resource', value: 'resource' }
                ]}
              />
            </Form.Item>
            <Form.Item name="payload" label="请求 JSON">
              <TextArea rows={10} className="mono" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} icon={<ApiOutlined />}>
              调用
            </Button>
          </Form>
          {result && <JsonPreview value={result} />}
        </Card>
      </Col>
    </Row>
  );
}
