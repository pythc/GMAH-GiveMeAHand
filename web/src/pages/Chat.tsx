import { MessageOutlined } from '@ant-design/icons';
import { Button, Card, Divider, Form, Input, Tag, Typography } from 'antd';
import { useState } from 'react';

import { api } from '../api';
import { JsonPreview } from '../components/JsonPreview';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { ChatCompletionResult } from '../types';

const { Paragraph } = Typography;
const { TextArea } = Input;

export default function Chat() {
  const [form] = Form.useForm<{ prompt: string }>();
  const [result, setResult] = useState<ChatCompletionResult | null>(null);
  const { loading, run } = useAsyncAction();

  return (
    <Card title="模型调用" extra={<Tag color="blue">doubao-seed-2-0-code-preview-260215</Tag>}>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ prompt: '用一句话介绍这个系统' }}
        onFinish={(values) =>
          void run(async () => {
            const response = await api.chat(values.prompt);
            setResult(response);
          }, '模型调用完成')
        }
      >
        <Form.Item name="prompt" label="用户消息" rules={[{ required: true }]}>
          <TextArea rows={5} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={loading} icon={<MessageOutlined />}>
          调用模型
        </Button>
      </Form>
      {result && (
        <>
          <Divider />
          <Paragraph copyable>{result.content}</Paragraph>
          <JsonPreview value={result} />
        </>
      )}
    </Card>
  );
}
