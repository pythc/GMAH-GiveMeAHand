import {
  ApiOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  FileZipOutlined,
  LockOutlined,
  MessageOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ToolOutlined
} from '@ant-design/icons';
import { Layout, Menu, Tag, Typography } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

const { Header, Sider, Content } = Layout;
const { Title, Text } = Typography;

const menuItems = [
  { key: '/', icon: <CheckCircleOutlined />, label: '总览' },
  { key: '/settings', icon: <SettingOutlined />, label: '模型设置' },
  { key: '/chat', icon: <MessageOutlined />, label: '模型调用' },
  { key: '/review', icon: <BarChartOutlined />, label: '课题评测' },
  { key: '/logs', icon: <FileTextOutlined />, label: 'AI 日志' },
  { key: '/sessions', icon: <ToolOutlined />, label: '会话/工具' },
  { key: '/approvals', icon: <SafetyCertificateOutlined />, label: '审批' },
  { key: '/rag', icon: <ExperimentOutlined />, label: 'RAG' },
  { key: '/qq', icon: <FileZipOutlined />, label: 'QQ 接入' },
  { key: '/mcp', icon: <ApiOutlined />, label: 'MCP' },
  { key: '/login', icon: <LockOutlined />, label: '认证' }
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Layout className="app-layout">
      <Sider width={260} breakpoint="lg" collapsedWidth="0" className="sidebar">
        <div className="brand">
          <div className="brand-mark">AW</div>
          <div>
            <Text strong style={{ color: '#fff' }}>Agent Workflow</Text>
            <div className="brand-subtitle">Console</div>
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          onClick={({ key }) => navigate(key)}
          items={menuItems}
        />
      </Sider>
      <Layout>
        <Header className="topbar">
          <Title level={4}>智能体系统运维控制台</Title>
          <Tag color="geekblue">React</Tag>
          <Tag color="blue">Vite</Tag>
          <Tag color="purple">Ant Design</Tag>
        </Header>
        <Content className="content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
