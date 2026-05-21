import {
  BarChartOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  HistoryOutlined,
  InboxOutlined,
  PlayCircleOutlined,
  ReloadOutlined
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload
} from 'antd';
import type { UploadFile } from 'antd';
import { useEffect, useState } from 'react';

import { api } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type {
  ReferenceDocument,
  ReviewHistoryRecord,
  ReviewResponse
} from '../types';

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

// ─── Tab 1: Review Task ──────────────────────────────────────────────────────

function ReviewTab() {
  const [result, setResult] = useState<ReviewResponse | null>(null);
  const { loading, run } = useAsyncAction();

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <Card title="发起评测">
          <Alert
            className="section-help"
            type="info"
            showIcon
            message="AI 自主评测课题产物"
            description="输入 GitHub 仓库 URL 或本地压缩包路径，AI 会自主克隆仓库、逐个查看文件、检索参考资料、对比历史记录，并给出结构化评价。重复提交同一链接时会参考上次评价。"
          />
          <Form
            layout="vertical"
            initialValues={{
              topic_title: '课题产物',
              topic_goal: '综合评价课题完成度、代码质量、可复现性和工程规范'
            }}
            onFinish={(values: {
              source_url?: string;
              archive_path?: string;
              topic_title: string;
              topic_goal: string;
            }) =>
              void run(async () => {
                const payload = {
                  source_url: values.source_url || undefined,
                  archive_path: values.archive_path || undefined,
                  topic_title: values.topic_title,
                  topic_goal: values.topic_goal
                };
                setResult(await api.reviewProject(payload));
              }, '评测完成')
            }
          >
            <Form.Item
              name="source_url"
              label="GitHub 仓库 URL"
              tooltip="如 https://github.com/user/repo"
            >
              <Input placeholder="https://github.com/..." />
            </Form.Item>
            <Form.Item
              name="archive_path"
              label="或：压缩包本地路径"
              tooltip="后端本机可访问的 zip/tar.gz 路径"
            >
              <Input placeholder="/path/to/project.zip" />
            </Form.Item>
            <Form.Item name="topic_title" label="课题名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="topic_goal" label="评测目标" rules={[{ required: true }]}>
              <TextArea rows={3} />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<PlayCircleOutlined />}
              size="large"
            >
              开始 AI 评测
            </Button>
          </Form>
        </Card>
      </Col>
      <Col xs={24} lg={14}>
        <Card title="评测结果">
          {result ? (
            <Space direction="vertical" className="full-width" size="large">
              {result.history_comparison && (
                <Alert
                  type={result.history_comparison === '首次评测' ? 'info' : 'warning'}
                  showIcon
                  message={result.history_comparison}
                />
              )}
              {result.evaluation && (
                <>
                  <Row gutter={16}>
                    <Col span={8}>
                      <Statistic
                        title="总评分"
                        value={result.evaluation.overall_score}
                        suffix="/100"
                      />
                    </Col>
                    <Col span={16}>
                      <Alert type="success" showIcon message={result.evaluation.summary} />
                    </Col>
                  </Row>
                  <Table
                    size="small"
                    rowKey="criterion_id"
                    dataSource={result.evaluation.criterion_assessments}
                    pagination={false}
                    columns={[
                      { title: '维度', dataIndex: 'name', width: 160 },
                      {
                        title: '分数',
                        dataIndex: 'score',
                        width: 80,
                        render: (v: number) => (
                          <Tag color={v >= 80 ? 'green' : v >= 60 ? 'orange' : 'red'}>
                            {v.toFixed(1)}
                          </Tag>
                        )
                      },
                      {
                        title: '建议',
                        dataIndex: 'suggestions',
                        render: (items: string[]) => items.join('；') || '-'
                      }
                    ]}
                  />
                </>
              )}
              {result.llm_review && (
                <Card size="small" title="AI 深度评价">
                  <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{result.llm_review}</Paragraph>
                </Card>
              )}
              <JsonPreview value={result} />
            </Space>
          ) : (
            <Alert message="在左侧输入 GitHub URL 或压缩包路径，点击「开始 AI 评测」。" />
          )}
        </Card>
      </Col>
    </Row>
  );
}

// ─── Tab 2: History ──────────────────────────────────────────────────────────

function HistoryTab() {
  const [records, setRecords] = useState<ReviewHistoryRecord[]>([]);
  const { loading, run } = useAsyncAction();

  const refresh = async () => setRecords(await api.getEvaluationHistory());

  useEffect(() => {
    void run(refresh);
  }, []);

  return (
    <Card
      title="评测历史（Excel 记录）"
      extra={
        <Space>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => window.open('/evaluation/history/download', '_blank')}
          >
            下载 Excel
          </Button>
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
        message="AI 维护的评测记录"
        description="每次评测 GitHub 仓库时，AI 会先查询历史记录。如果发现与上次相比没有明显优化，则不会更新 Excel。"
      />
      <Table
        rowKey="repo_url"
        dataSource={records}
        columns={[
          {
            title: '仓库链接',
            dataIndex: 'repo_url',
            ellipsis: true,
            render: (url: string) => (
              <a href={url} target="_blank" rel="noopener noreferrer">
                {url.replace('https://github.com/', '')}
              </a>
            )
          },
          { title: '课题名称', dataIndex: 'topic_name', width: 140 },
          {
            title: '评分',
            dataIndex: 'score',
            width: 80,
            render: (v: number | null) =>
              v !== null ? <Tag color={v >= 80 ? 'green' : v >= 60 ? 'orange' : 'red'}>{v}</Tag> : '-'
          },
          { title: '更新时间', dataIndex: 'updated_at', width: 180 },
          { title: '次数', dataIndex: 'review_count', width: 60 },
          {
            title: '操作',
            width: 80,
            render: (_: unknown, record: ReviewHistoryRecord) => (
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                onClick={() =>
                  void run(async () => {
                    await api.deleteEvaluationHistory(record.repo_url);
                    await refresh();
                  }, '已删除')
                }
              />
            )
          }
        ]}
        expandable={{
          expandedRowRender: (record) => (
            <Space direction="vertical" className="full-width">
              <Paragraph>
                <Text strong>评价内容：</Text>
              </Paragraph>
              <Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                {record.review || '暂无评价内容'}
              </Paragraph>
              {record.tool_summary && (
                <Paragraph>
                  <Text strong>工具摘要：</Text> {record.tool_summary}
                </Paragraph>
              )}
            </Space>
          )
        }}
      />
    </Card>
  );
}

// ─── Tab 3: References ───────────────────────────────────────────────────────

function ReferencesTab() {
  const [references, setReferences] = useState<ReferenceDocument[]>([]);
  const [description, setDescription] = useState('');
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const { loading, run } = useAsyncAction();

  const refresh = async () => {
    const result = await api.listReferences();
    setReferences(result.references);
  };

  useEffect(() => {
    void run(refresh);
  }, []);

  const handleUpload = async () => {
    if (!fileList.length) return;
    const file = fileList[0].originFileObj;
    if (!file) return;
    await api.uploadReference(file, description);
    setFileList([]);
    setDescription('');
    await refresh();
  };

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <Card title="上传参考资料">
          <Alert
            className="section-help"
            type="info"
            showIcon
            message="供 AI 评测时参考的标杆文档"
            description="上传优秀的学术 PPT、结题报告模板、代码规范文档等。AI 评测时会通过 RAG 检索这些参考资料，作为评价标准的补充依据。"
          />
          <Space direction="vertical" className="full-width">
            <Upload.Dragger
              fileList={fileList}
              onChange={({ fileList: fl }) => setFileList(fl.slice(-1))}
              beforeUpload={() => false}
              maxCount={1}
              accept=".pdf,.pptx,.docx,.xlsx,.txt,.md,.html,.htm,.png,.jpg,.jpeg,.csv,.json,.yaml,.yml"
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽文件到此区域</p>
              <p className="ant-upload-hint">
                支持 PDF、PPTX、DOCX、XLSX、TXT、MD、HTML、图片等
              </p>
            </Upload.Dragger>
            <Input
              placeholder="描述这份资料的用途（如：优秀学术PPT范例）"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              loading={loading}
              disabled={!fileList.length}
              onClick={() => void run(handleUpload, '参考资料已上传并摄取到 RAG')}
            >
              上传并摄取
            </Button>
          </Space>
        </Card>
      </Col>
      <Col xs={24} lg={14}>
        <Card
          title="已上传参考资料"
          extra={
            <Button icon={<ReloadOutlined />} onClick={() => void run(refresh)}>
              刷新
            </Button>
          }
        >
          <Table
            rowKey="ref_id"
            dataSource={references}
            columns={[
              { title: '文件名', dataIndex: 'filename' },
              { title: '描述', dataIndex: 'description', ellipsis: true },
              { title: 'Chunks', dataIndex: 'text_chunks', width: 80 },
              { title: '上传时间', dataIndex: 'uploaded_at', width: 180 },
              {
                title: '操作',
                width: 80,
                render: (_: unknown, record: ReferenceDocument) => (
                  <Button
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    onClick={() =>
                      void run(async () => {
                        await api.deleteReference(record.ref_id);
                        await refresh();
                      }, '已删除')
                    }
                  />
                )
              }
            ]}
          />
        </Card>
      </Col>
    </Row>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function Evaluation() {
  return (
    <Tabs
      defaultActiveKey="review"
      items={[
        {
          key: 'review',
          label: (
            <span>
              <BarChartOutlined /> 发起评测
            </span>
          ),
          children: <ReviewTab />
        },
        {
          key: 'history',
          label: (
            <span>
              <HistoryOutlined /> 评测历史
            </span>
          ),
          children: <HistoryTab />
        },
        {
          key: 'references',
          label: (
            <span>
              <CloudUploadOutlined /> 参考资料库
            </span>
          ),
          children: <ReferencesTab />
        }
      ]}
    />
  );
}
