import { CloudSyncOutlined, ExperimentOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Form, Input, Row, Select, Table, Tag } from 'antd';
import { useState } from 'react';

import { api, parseJsonObject } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { JsonObject, RetrievalEvidence } from '../types';

const { TextArea } = Input;

export default function Rag() {
  const [evidence, setEvidence] = useState<RetrievalEvidence[]>([]);
  const [ingestResult, setIngestResult] = useState<JsonObject | null>(null);
  const { loading, run } = useAsyncAction();
  const sampleDocument = JSON.stringify(
    {
      documents: [
        {
          source_id: 'ui-doc-1',
          text: 'LangGraph coordinates tool calls with Redis checkpoints and Qdrant RAG.',
          pages: [
            {
              page_number: 1,
              artifact_uri: 'oss://bucket/ui-doc-1-page-1.png',
              text: 'visual architecture page with LangGraph Redis Qdrant'
            }
          ]
        }
      ]
    },
    null,
    2
  );

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <Card title="RAG 摄取">
          <Form
            layout="vertical"
            initialValues={{ payload: sampleDocument }}
            onFinish={(values: { payload: string }) =>
              void run(async () => {
                setIngestResult(await api.ingestRag(parseJsonObject(values.payload)));
              }, '摄取完成')
            }
          >
            <Form.Item name="payload" label="Ingest JSON">
              <TextArea rows={14} className="mono" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} icon={<CloudSyncOutlined />}>
              摄取文档
            </Button>
          </Form>
          {ingestResult && <JsonPreview value={ingestResult} />}
        </Card>
      </Col>
      <Col xs={24} lg={14}>
        <Card title="RAG 检索">
          <Alert
            className="section-help"
            type="info"
            showIcon
            message="检索模式说明"
            description="文本检索只查文本 chunk；视觉检索只查页面/图片证据；融合检索会合并两路结果并按分数排序。"
          />
          <Form
            layout="inline"
            initialValues={{ query: 'LangGraph Redis Qdrant', mode: 'fused' }}
            onFinish={(values: { query: string; mode: 'text' | 'visual' | 'fused' }) =>
              void run(async () => {
                const result = await api.retrieveRag(values.mode, values.query);
                setEvidence(result.evidence);
              }, '检索完成')
            }
          >
            <Form.Item name="mode">
              <Select
                className="select-width"
                options={[
                  { label: '融合', value: 'fused' },
                  { label: '文本', value: 'text' },
                  { label: '视觉', value: 'visual' }
                ]}
              />
            </Form.Item>
            <Form.Item name="query" className="flex-form-item">
              <Input placeholder="输入检索问题" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} icon={<ExperimentOutlined />}>
              检索
            </Button>
          </Form>
          <Table
            className="result-table"
            rowKey={(record) =>
              `${record.source_id}-${record.metadata?.chunk_id ?? record.score}`
            }
            dataSource={evidence}
            columns={[
              { title: '来源', dataIndex: 'source_id' },
              { title: '模态', dataIndex: 'modality', render: (value) => <Tag>{value}</Tag> },
              {
                title: '分数',
                dataIndex: 'score',
                render: (value: number) => value.toFixed(3)
              },
              { title: '内容', dataIndex: 'content', ellipsis: true }
            ]}
            expandable={{
              expandedRowRender: (record) => <JsonPreview value={record} />
            }}
          />
        </Card>
      </Col>
    </Row>
  );
}
