import { FileZipOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography
} from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { api, parseJsonObject } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type {
  ArchiveEvaluateResult,
  ArchiveInspectionResult,
  JsonObject,
  QqAutomationSettings,
  QqBlacklistEntry,
  QqEvent
} from '../types';

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export default function Qq() {
  const [archiveForm] = Form.useForm<{ path: string; topic_title: string; topic_goal: string }>();
  const [automationForm] = Form.useForm();
  const [blacklistForm] = Form.useForm<{
    entry_type: 'user' | 'conversation';
    value: string;
    reason?: string;
  }>();
  const [automation, setAutomation] = useState<QqAutomationSettings | null>(null);
  const [events, setEvents] = useState<QqEvent[]>([]);
  const [inspection, setInspection] = useState<ArchiveInspectionResult | null>(null);
  const [evaluation, setEvaluation] = useState<ArchiveEvaluateResult | null>(null);
  const [result, setResult] = useState<JsonObject | null>(null);
  const { loading, run } = useAsyncAction();
  const sampleEvent = useMemo(
    () =>
      JSON.stringify(
        {
          post_type: 'message',
          message_type: 'group',
          time: Math.floor(Date.now() / 1000),
          group_id: 123456,
          user_id: 10001,
          message_id: 'demo-message-1',
          sender: { nickname: '学生A', card: '学生A', role: 'student' },
          message: [
            { type: 'text', data: { text: '请分析这个课题压缩包' } },
            { type: 'file', data: { file: 'project.zip', path: '/tmp/project.zip', size: 1024 } }
          ]
        },
        null,
        2
      ),
    []
  );

  useEffect(() => {
    void run(async () => {
      const [qqEvents, qqAutomation] = await Promise.all([
        api.listQqEvents(),
        api.getQqAutomationSettings()
      ]);
      setEvents(qqEvents);
      setAutomation(qqAutomation);
    });
  }, []);

  const saveAutomation = async (values: Record<string, unknown>) => {
    const payload: Record<string, unknown> = {
      ...values,
      blacklist: automation?.blacklist ?? []
    };
    if (!values.access_token) delete payload.access_token;
    setAutomation(await api.updateQqAutomationSettings(payload as JsonObject));
    automationForm.resetFields(['access_token']);
  };

  const addBlacklist = async (values: QqBlacklistEntry) => {
    const next = [
      ...(automation?.blacklist ?? []),
      { entry_type: values.entry_type, value: values.value.trim(), reason: values.reason || null }
    ];
    setAutomation(
      await api.updateQqAutomationSettings({ ...(automation ?? {}), blacklist: next } as JsonObject)
    );
    blacklistForm.resetFields();
  };

  const removeBlacklist = async (index: number) => {
    const next = (automation?.blacklist ?? []).filter((_, i) => i !== index);
    setAutomation(
      await api.updateQqAutomationSettings({ ...(automation ?? {}), blacklist: next } as JsonObject)
    );
  };

  return (
    <Space direction="vertical" size="large" className="full-width">
      <Alert
        type="info"
        showIcon
        message="QQ/NapCat 接入说明"
        description="推荐 NapCatQQ 开启 OneBot HTTP/Webhook，把事件上报到 /qq/onebot/webhook。收到文件或群文件上传后，系统会归一化为内部事件；本地可访问的压缩包可以继续检查、解压并自动进入课题评价。"
      />
      <Card title="NapCat 配置参考">
        <Paragraph>将 NapCat 的 HTTP 上报地址配置为：</Paragraph>
        <Paragraph copyable>
          <Text code>http://127.0.0.1:8080/qq/onebot/webhook</Text>
        </Paragraph>
        <Paragraph>WebSocket 连接模式（需后端启动 WS 监听）：</Paragraph>
        <Paragraph copyable>
          <Text code>ws://127.0.0.1:8080/qq/ws</Text>
        </Paragraph>
      </Card>

      {/* Automation Settings */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card
            title="自动评价 / 自动回复"
            extra={
              <Button
                onClick={() =>
                  void run(async () => {
                    setAutomation(await api.getQqAutomationSettings());
                  }, '自动化设置已刷新')
                }
              >
                刷新
              </Button>
            }
          >
            <Alert
              className="section-help"
              type="info"
              showIcon
              message="收到 QQ 消息后自动处理"
              description="私聊默认会自动回复；群聊仅在消息包含课题/评价/分析等关键词、仓库链接、压缩包或 @ 机器人时触发。"
            />
            {automation ? (
              <Form
                form={automationForm}
                layout="vertical"
                key={JSON.stringify(automation).length}
                initialValues={{
                  auto_evaluate_enabled: automation.auto_evaluate_enabled,
                  auto_reply_enabled: automation.auto_reply_enabled,
                  deep_review_enabled: automation.deep_review_enabled,
                  progress_report_enabled: automation.progress_report_enabled,
                  progress_report_level: automation.progress_report_level,
                  onebot_api_base_url: automation.onebot_api_base_url,
                  topic_title: automation.topic_title,
                  topic_goal: automation.topic_goal,
                  agent_system_prompt: automation.agent_system_prompt
                }}
                onFinish={(values) =>
                  void run(async () => {
                    await saveAutomation(values);
                  }, '自动化设置已保存')
                }
              >
                <Row gutter={16}>
                  <Col xs={12} md={6}>
                    <Form.Item
                      name="auto_evaluate_enabled"
                      label="自动评价"
                      valuePropName="checked"
                    >
                      <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                    </Form.Item>
                  </Col>
                  <Col xs={12} md={6}>
                    <Form.Item
                      name="auto_reply_enabled"
                      label="自动回复"
                      valuePropName="checked"
                    >
                      <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                    </Form.Item>
                  </Col>
                  <Col xs={12} md={6}>
                    <Form.Item
                      name="deep_review_enabled"
                      label="深度评审"
                      valuePropName="checked"
                    >
                      <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                    </Form.Item>
                  </Col>
                  <Col xs={12} md={6}>
                    <Form.Item
                      name="progress_report_enabled"
                      label="AI 进度汇报"
                      valuePropName="checked"
                    >
                      <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item name="progress_report_level" label="进度频率">
                  <Select
                    options={[
                      { label: '精简', value: 'minimal' },
                      { label: '标准', value: 'normal' },
                      { label: '详细', value: 'verbose' }
                    ]}
                  />
                </Form.Item>
                <Form.Item name="onebot_api_base_url" label="OneBot HTTP API Base URL">
                  <Input placeholder="http://127.0.0.1:3001" />
                </Form.Item>
                <Form.Item name="access_token" label="OneBot Token">
                  <Input.Password
                    placeholder={
                      automation.access_token_configured ? '已配置，留空不修改' : '例如 1'
                    }
                  />
                </Form.Item>
                <Form.Item name="topic_title" label="默认课题标题">
                  <Input />
                </Form.Item>
                <Form.Item name="topic_goal" label="默认课题目标">
                  <Input />
                </Form.Item>
                <Form.Item name="agent_system_prompt" label="智能体主提示词">
                  <TextArea rows={10} className="mono" />
                </Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" loading={loading}>
                    保存自动化设置
                  </Button>
                  <Tag color={automation.access_token_configured ? 'green' : 'red'}>
                    {automation.access_token_configured ? '已配置 Token' : '未配置 Token'}
                  </Tag>
                </Space>
              </Form>
            ) : (
              <Button
                onClick={() =>
                  void run(async () => {
                    setAutomation(await api.getQqAutomationSettings());
                  })
                }
              >
                加载设置
              </Button>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card title="黑名单列表">
            <Alert
              className="section-help"
              type="warning"
              showIcon
              message="命中黑名单的消息不会自动评价或自动回复"
            />
            <Form
              form={blacklistForm}
              layout="inline"
              initialValues={{ entry_type: 'user' }}
              onFinish={(values: QqBlacklistEntry) =>
                void run(async () => {
                  await addBlacklist(values);
                }, '黑名单已更新')
              }
            >
              <Form.Item name="entry_type" rules={[{ required: true }]}>
                <Select
                  className="select-width"
                  options={[
                    { label: '用户', value: 'user' },
                    { label: '会话', value: 'conversation' }
                  ]}
                />
              </Form.Item>
              <Form.Item name="value" rules={[{ required: true }]}>
                <Input placeholder="QQ号 / group:群号" />
              </Form.Item>
              <Form.Item name="reason">
                <Input placeholder="原因" />
              </Form.Item>
              <Button htmlType="submit">加入黑名单</Button>
            </Form>
            <Table
              className="result-table"
              size="small"
              rowKey={(record) => `${record.entry_type}:${record.value}`}
              dataSource={automation?.blacklist ?? []}
              pagination={false}
              columns={[
                {
                  title: '类型',
                  dataIndex: 'entry_type',
                  render: (value) => (value === 'user' ? '用户' : '会话')
                },
                { title: '值', dataIndex: 'value' },
                { title: '原因', dataIndex: 'reason', render: (value) => value || '-' },
                {
                  title: '操作',
                  render: (_, __, index) => (
                    <Button
                      danger
                      size="small"
                      onClick={() =>
                        void run(async () => {
                          await removeBlacklist(index);
                        }, '黑名单已更新')
                      }
                    >
                      移除
                    </Button>
                  )
                }
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* Simulate Events */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card title="模拟 OneBot 事件">
            <Form
              layout="vertical"
              initialValues={{ payload: sampleEvent }}
              onFinish={(values: { payload: string }) =>
                void run(async () => {
                  setResult(await api.postOneBotEvent(parseJsonObject(values.payload)));
                  setEvents(await api.listQqEvents());
                }, '事件已接收')
              }
            >
              <Form.Item name="payload" label="OneBot Event JSON">
                <TextArea rows={16} className="mono" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={loading}>
                发送模拟事件
              </Button>
            </Form>
            {result && <JsonPreview value={result} />}
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card
            title="最近 QQ 事件"
            extra={
              <Button
                onClick={() =>
                  void run(async () => {
                    setEvents(await api.listQqEvents());
                  }, '事件列表已刷新')
                }
              >
                刷新
              </Button>
            }
          >
            <Table
              rowKey="message_id"
              dataSource={events}
              columns={[
                { title: '会话', dataIndex: 'conversation_id' },
                { title: '发送者', dataIndex: ['sender', 'display_name'] },
                { title: '文本', dataIndex: ['content', 'text'], ellipsis: true },
                { title: '附件数', render: (_, record) => record.content.attachments.length }
              ]}
              expandable={{ expandedRowRender: (record) => <JsonPreview value={record} /> }}
            />
          </Card>
        </Col>
      </Row>

      {/* Archive Evaluation */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="压缩包检查 / 自动评价">
            <Alert
              className="section-help"
              type="warning"
              showIcon
              message="只处理后端本机可访问路径"
            />
            <Form
              form={archiveForm}
              layout="vertical"
              initialValues={{
                topic_title: 'QQ 上传课题产物',
                topic_goal: '综合评价课题所有产物'
              }}
              onFinish={(values: { path: string; topic_title: string; topic_goal: string }) =>
                void run(async () => {
                  const analysis = await api.evaluateQqArchive(values);
                  setEvaluation(analysis);
                  setInspection(analysis.extraction.inspection as ArchiveInspectionResult);
                }, '压缩包评价完成')
              }
            >
              <Form.Item name="path" label="压缩包本地路径" rules={[{ required: true }]}>
                <Input placeholder="/tmp/project.zip" />
              </Form.Item>
              <Form.Item name="topic_title" label="课题标题" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="topic_goal" label="课题目标" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Space>
                <Button
                  onClick={() =>
                    void run(async () => {
                      const path = archiveForm.getFieldValue('path');
                      setInspection(await api.inspectQqArchive(path));
                    })
                  }
                >
                  仅检查
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  icon={<FileZipOutlined />}
                >
                  解压并评价
                </Button>
              </Space>
            </Form>
            {inspection && <JsonPreview value={inspection} />}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="评价结果与 QQ 回复">
            {evaluation?.evaluation ? (
              <Space direction="vertical" className="full-width">
                <Statistic
                  title="总评分"
                  value={evaluation.evaluation.overall_score}
                  suffix="/100"
                />
                <Alert type="success" showIcon message={evaluation.evaluation.summary} />
                <Form
                  layout="vertical"
                  initialValues={{
                    conversation_id: 'group:123456',
                    onebot_api_base_url: 'http://127.0.0.1:3001',
                    message: `课题评价完成：${evaluation.evaluation.summary}\n总分：${evaluation.evaluation.overall_score}/100`
                  }}
                  onFinish={(values: JsonObject) =>
                    void run(async () => {
                      setResult(await api.sendQqMessage(values));
                    }, 'QQ 消息已发送')
                  }
                >
                  <Form.Item name="conversation_id" label="会话 ID">
                    <Input placeholder="group:123456 或 private:10001" />
                  </Form.Item>
                  <Form.Item name="onebot_api_base_url" label="OneBot HTTP API Base URL">
                    <Input />
                  </Form.Item>
                  <Form.Item name="message" label="回复内容">
                    <TextArea rows={5} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit">
                    发送到 QQ
                  </Button>
                </Form>
                <JsonPreview value={evaluation} />
              </Space>
            ) : (
              <Alert message={'先在左侧对压缩包执行"解压并评价"。'} />
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
