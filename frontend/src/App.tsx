import { useState } from 'react';
import { Layout, Menu, Typography } from 'antd';
import {
  MessageOutlined,
  DashboardOutlined,
  SearchOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import ChatReimbursement from './pages/ChatReimbursement';
import Dashboard from './pages/Dashboard';
import StatusQuery from './pages/StatusQuery';
import ApprovalSimulator from './pages/ApprovalSimulator';

const { Sider, Content, Header } = Layout;
const { Title } = Typography;

const menuItems = [
  { key: 'chat', icon: <MessageOutlined />, label: '对话报销' },
  { key: 'dashboard', icon: <DashboardOutlined />, label: '报销看板' },
  { key: 'approval', icon: <AuditOutlined />, label: '模拟审批' },
  { key: 'status', icon: <SearchOutlined />, label: '进度查询' },
];

const pageMap: Record<string, React.ReactNode> = {
  chat: <ChatReimbursement />,
  dashboard: <Dashboard />,
  approval: <ApprovalSimulator />,
  status: <StatusQuery />,
};

export default function App() {
  const [active, setActive] = useState('chat');

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={220}
        style={{
          background: 'linear-gradient(180deg, #001529 0%, #002140 100%)',
          borderRight: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          <Title
            level={5}
            style={{
              color: '#fff',
              margin: 0,
              fontWeight: 600,
              letterSpacing: 1,
            }}
          >
            ReimburseAgent
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[active]}
          onClick={({ key }) => setActive(key)}
          items={menuItems}
          style={{
            background: 'transparent',
            borderRight: 0,
            marginTop: 8,
          }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 32px',
            display: 'flex',
            alignItems: 'center',
            borderBottom: '1px solid #f0f0f0',
            height: 56,
          }}
        >
          <Title level={4} style={{ margin: 0, fontWeight: 500 }}>
            企业财务报销助手
          </Title>
        </Header>
        <Content
          style={{
            margin: 24,
            padding: 24,
            background: '#fff',
            borderRadius: 8,
            minHeight: 280,
            overflow: 'auto',
          }}
        >
          {pageMap[active]}
        </Content>
      </Layout>
    </Layout>
  );
}
