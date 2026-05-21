import {
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  ToolOutlined
} from '@ant-design/icons';
import { Alert, Button, Card, Col, Row, Space, Statistic, Table, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';

import { api } from '../api';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { ApprovalRecord, FunctionToolSpec, HealthzResponse } from '../types';

const { Title } = Typography;

export default function Dashboard() {
  const [health, setHealth] = useState<HealthzResponse | null>(null);
  const [tools, setTools] = useState<FunctionToolSpec[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const { loading, run } = useAsyncAction();

  const refresh = async () => {
    const [healthz, toolSpecs, pending] = await Promise.all([
      api.healthz(),
      api.listTools(),
      api.listPendingApprovals()
    ]);
    setHealth(healthz);
    setTools(toolSpecs);
    setApprovals(pending);
  };

  useEffect(() => {
    void run(refresh);
  }, []);

  return (
    <Space direction="vertical" size="large" className="full-width">
      <div className="page-title">
        <Title level={2}>Agent Workflow 控制台</Title>
        <Button loading={loading} onClick={() => void run(refresh, '状态已刷新')}>
          刷新状态
        </Button>
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={6}>
          <Card>
            <Statistic
              title="API 状态"
              value={health?.status ?? 'unknown'}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="版本" value={health?.version ?? '-'} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="已注册工具" value={tools.length} prefix={<ToolOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic
              title="待审批"
              value={approvals.length}
              prefix={<SafetyCertificateOutlined />}
            />
          </Card>
        </Col>
      </Row>
      <Alert
        type="info"
        showIcon
        message="前端采用 React + Vite + TypeScript + Ant Design。"
        description="当前页面覆盖模型调用、会话编排、审批、RAG 摄取/检索、MCP 能力发现与调用。"
      />
      <Card title="工具清单">
        <Table
          rowKey="name"
          size="small"
          dataSource={tools}
          pagination={false}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '风险', dataIndex: 'risk_level', render: (value) => <Tag>{value}</Tag> },
            { title: '审批策略', dataIndex: 'approval_policy' },
            { title: '说明', dataIndex: 'description' }
          ]}
        />
      </Card>
    </Space>
  );
}
