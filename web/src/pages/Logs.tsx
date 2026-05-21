import { ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Select, Space, Switch, Table, Tag, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { api } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { ToolLogEntry } from '../types';

const { Text, Paragraph } = Typography;

const kindColors: Record<string, string> = {
  tool_call: 'blue',
  model_request: 'purple',
  model_response: 'geekblue',
  progress: 'green',
  error: 'red',
  system: 'default'
};
const kindLabels: Record<string, string> = {
  tool_call: '工具调用',
  model_request: '模型请求',
  model_response: '模型返回',
  progress: '进度汇报',
  error: '错误',
  system: '系统'
};

export default function Logs() {
  const [logs, setLogs] = useState<ToolLogEntry[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [kindFilter, setKindFilter] = useState<string | undefined>(undefined);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { loading, run } = useAsyncAction();

  const refresh = async () => setLogs(await api.getToolLogs(500));

  useEffect(() => {
    void run(refresh);
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => void refresh(), 2000);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh]);

  const filtered = kindFilter ? logs.filter((l) => l.kind === kindFilter) : logs;

  return (
    <Card
      title="AI 活动日志"
      extra={
        <Space>
          <Select
            allowClear
            placeholder="筛选类型"
            style={{ width: 130 }}
            value={kindFilter}
            onChange={setKindFilter}
            options={[
              { label: '全部', value: undefined },
              { label: '模型请求', value: 'model_request' },
              { label: '模型返回', value: 'model_response' },
              { label: '工具调用', value: 'tool_call' },
              { label: '进度汇报', value: 'progress' },
              { label: '错误', value: 'error' }
            ]}
          />
          <Text>自动刷新</Text>
          <Switch
            checked={autoRefresh}
            onChange={setAutoRefresh}
            checkedChildren="开"
            unCheckedChildren="关"
          />
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void run(refresh)}>
            刷新
          </Button>
        </Space>
      }
    >
      <Alert
        className="section-help"
        type="info"
        showIcon
        message="所有 AI 活动的完整日志"
        description="包括所有模型请求/响应、工具调用、进度汇报、错误等。不仅限于课题评测——任何经过系统的模型调用都会记录。"
      />
      <Table
        rowKey={(_, i) => String(i)}
        dataSource={[...filtered].reverse()}
        size="small"
        pagination={{ pageSize: 100 }}
        columns={[
          { title: '时间', dataIndex: 'timestamp', width: 160 },
          {
            title: '类型',
            dataIndex: 'kind',
            width: 100,
            render: (kind: string) => (
              <Tag color={kindColors[kind] || 'default'}>{kindLabels[kind] || kind}</Tag>
            )
          },
          { title: '会话', dataIndex: 'session_id', width: 120, ellipsis: true },
          {
            title: '工具/模型',
            dataIndex: 'tool',
            width: 150,
            ellipsis: true,
            render: (tool: string | null) => tool || '-'
          },
          {
            title: '内容',
            key: 'display',
            ellipsis: true,
            render: (_: unknown, record: ToolLogEntry) => {
              if (record.content) return record.content;
              if (record.detail) return record.detail;
              if (record.target) return record.target;
              return '-';
            }
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 80,
            render: (s: string | null) => {
              if (!s) return '-';
              const color =
                s === 'success' || s === 'received'
                  ? 'green'
                  : s === 'error' || s === 'failed'
                    ? 'red'
                    : s === 'sending'
                      ? 'orange'
                      : 'default';
              return <Tag color={color}>{s}</Tag>;
            }
          }
        ]}
        expandable={{
          expandedRowRender: (record) => (
            <Space direction="vertical" className="full-width">
              {record.content && (
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  <Text strong>内容：</Text> {record.content}
                </Paragraph>
              )}
              {record.detail && (
                <Paragraph style={{ margin: 0 }}>
                  <Text strong>详情：</Text> {record.detail}
                </Paragraph>
              )}
              {Object.keys(record.arguments).length > 0 && <JsonPreview value={record.arguments} />}
              {Object.keys(record.metadata).length > 0 && <JsonPreview value={record.metadata} />}
            </Space>
          )
        }}
      />
    </Card>
  );
}
