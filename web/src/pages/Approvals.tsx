import { Button, Card, Space, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';

import { api } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { ApprovalRecord } from '../types';

export default function Approvals() {
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const { loading, run } = useAsyncAction();

  const refresh = async () => setApprovals(await api.listPendingApprovals());

  useEffect(() => {
    void run(refresh);
  }, []);

  const columns: ColumnsType<ApprovalRecord> = [
    { title: '审批 ID', dataIndex: 'approval_id', ellipsis: true },
    { title: '工具', dataIndex: 'tool_name' },
    { title: '请求人', dataIndex: 'requested_by' },
    { title: 'Trace', dataIndex: 'trace_id', ellipsis: true },
    {
      title: '操作',
      render: (_, record) => (
        <Space>
          <Button
            type="primary"
            size="small"
            onClick={() =>
              void run(async () => {
                await api.decideApproval(record.approval_id, true, '控制台审批通过');
                await refresh();
              }, '已批准')
            }
          >
            批准
          </Button>
          <Button
            danger
            size="small"
            onClick={() =>
              void run(async () => {
                await api.decideApproval(record.approval_id, false, '控制台拒绝');
                await refresh();
              }, '已拒绝')
            }
          >
            拒绝
          </Button>
        </Space>
      )
    }
  ];

  return (
    <Card
      title="人工审批"
      extra={
        <Button loading={loading} onClick={() => void run(refresh, '审批列表已刷新')}>
          刷新
        </Button>
      }
    >
      <Table
        rowKey="approval_id"
        columns={columns}
        dataSource={approvals}
        expandable={{
          expandedRowRender: (record) => <JsonPreview value={record} />
        }}
      />
    </Card>
  );
}
