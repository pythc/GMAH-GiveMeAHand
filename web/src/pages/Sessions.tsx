import { Button, Card, Col, Form, Input, Row, Select, Space } from 'antd';
import { useMemo, useState } from 'react';

import { api, parseJsonObject } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { RunSessionResult, SessionState } from '../types';

const { TextArea } = Input;

export default function Sessions() {
  const [session, setSession] = useState<SessionState | null>(null);
  const [result, setResult] = useState<RunSessionResult | null>(null);
  const { loading, run } = useAsyncAction();
  const defaultPayload = useMemo(
    () =>
      JSON.stringify(
        {
          user_id: 'teacher-1',
          message: '保存反馈草稿',
          tool_call: {
            tool_name: 'save_feedback_draft',
            arguments: {
              submission_id: 'submission-1',
              draft_revision: 'ui-r1',
              feedback_markdown: '结构清晰，建议补充评估指标。'
            }
          }
        },
        null,
        2
      ),
    []
  );

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <Card title="会话操作">
          <Space direction="vertical" className="full-width">
            <Button
              onClick={() =>
                void run(async () => {
                  setSession(await api.createSession('console-user'));
                }, '会话已创建')
              }
            >
              创建会话
            </Button>
            <Form
              layout="vertical"
              initialValues={{ payload: defaultPayload, runtime: 'normal' }}
              onFinish={(values: { payload: string; runtime: 'normal' | 'langgraph' }) =>
                void run(async () => {
                  const response = await api.runSession(
                    parseJsonObject(values.payload),
                    values.runtime === 'langgraph'
                  );
                  setResult(response);
                  setSession(response.state);
                }, '会话执行完成')
              }
            >
              <Form.Item name="runtime" label="运行方式">
                <Select
                  options={[
                    { label: '普通编排', value: 'normal' },
                    { label: 'LangGraph', value: 'langgraph' }
                  ]}
                />
              </Form.Item>
              <Form.Item name="payload" label="RunSessionRequest JSON" rules={[{ required: true }]}>
                <TextArea rows={14} className="mono" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={loading}>
                执行会话
              </Button>
            </Form>
          </Space>
        </Card>
      </Col>
      <Col xs={24} lg={14}>
        <Card title="会话结果">
          <JsonPreview value={{ session, result }} />
        </Card>
      </Col>
    </Row>
  );
}
