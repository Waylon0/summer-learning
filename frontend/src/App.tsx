import { Tabs, Typography } from 'antd';
import {
  MessageOutlined,
  DashboardOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import ChatReimbursement from './pages/ChatReimbursement';
import Dashboard from './pages/Dashboard';
import StatusQuery from './pages/StatusQuery';

const { Title } = Typography;

const tabItems = [
  {
    key: 'chat',
    label: (
      <span>
        <MessageOutlined /> 对话报销
      </span>
    ),
    children: <ChatReimbursement />,
  },
  {
    key: 'dashboard',
    label: (
      <span>
        <DashboardOutlined /> 报销看板
      </span>
    ),
    children: <Dashboard />,
  },
  {
    key: 'status',
    label: (
      <span>
        <SearchOutlined /> 进度查询
      </span>
    ),
    children: <StatusQuery />,
  },
];

export default function App() {
  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={3} style={{ marginBottom: 24 }}>
        💰 ReimburseAgent — 企业财务报销助手
      </Title>
      <Tabs defaultActiveKey="chat" items={tabItems} size="large" />
    </div>
  );
}
