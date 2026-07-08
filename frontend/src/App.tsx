import { useState, useEffect } from 'react';
import { Layout, Menu, Typography, Tag, Button, Dropdown, Spin } from 'antd';
import {
  MessageOutlined,
  DashboardOutlined,
  SearchOutlined,
  AuditOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons';
import ChatReimbursement from './pages/ChatReimbursement';
import Dashboard from './pages/Dashboard';
import StatusQuery from './pages/StatusQuery';
import Approval from './pages/Approval';
import AuthPage from './pages/Auth';
import { healthCheck } from './services/api';
import { useAuthStore } from './stores';

const { Sider, Content, Header } = Layout;
const { Title, Text } = Typography;

const menuItems = [
  { key: 'chat', icon: <MessageOutlined />, label: '对话报销' },
  { key: 'dashboard', icon: <DashboardOutlined />, label: '报销看板' },
  { key: 'approval', icon: <AuditOutlined />, label: '报销审批' },
  { key: 'status', icon: <SearchOutlined />, label: '进度查询' },
];

const pageMap: Record<string, React.ReactNode> = {
  chat: <ChatReimbursement />,
  dashboard: <Dashboard />,
  approval: <Approval />,
  status: <StatusQuery />,
};

const roleDefaults: Record<string, string> = {
  employee: 'chat',
  manager: 'dashboard',
  admin: 'dashboard',
  finance: 'dashboard',
};

const roleTitles: Record<string, string> = {
  employee: '我的工作台',
  manager: '团队报销管理',
  admin: '企业财务总览',
  finance: '财务审核中心',
};

export default function App() {
  const { user, token, loading, initialize, logout } = useAuthStore();
  const [active, setActive] = useState(roleDefaults[user?.role || 'employee'] || 'chat');
  const [dbStatus, setDbStatus] = useState<'connected' | 'disconnected' | 'loading'>('loading');

  useEffect(() => { initialize(); }, [initialize]);

  // 监听 401 事件自动登出
  useEffect(() => {
    const handleLogout = () => { logout(); };
    window.addEventListener('auth:logout', handleLogout);
    return () => window.removeEventListener('auth:logout', handleLogout);
  }, [logout]);

  useEffect(() => {
    healthCheck()
      .then((h) => setDbStatus(h.database === 'connected' ? 'connected' : 'disconnected'))
      .catch(() => setDbStatus('disconnected'));
  }, []);

  // 认证加载中
  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  // 未登录 → 显示登录/注册页
  if (!token || !user) {
    return <AuthPage />;
  }

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
            flexDirection: 'column',
          }}
        >
          <Title level={5} style={{ color: '#fff', margin: 0, fontWeight: 600, letterSpacing: 1 }}>
            ReimburseAgent
          </Title>
          <Text style={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }}>
            {user.department} · {({ employee: '员工', manager: '经理', admin: '管理员', finance: '财务' })[user.role] || user.role}
          </Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[active]}
          onClick={({ key }) => setActive(key)}
          items={menuItems}
          style={{ background: 'transparent', borderRight: 0, marginTop: 8 }}
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
            {roleTitles[user.role] || '企业财务报销助手'}
          </Title>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
            <Tag color={dbStatus === 'connected' ? 'success' : dbStatus === 'disconnected' ? 'error' : 'default'}>
              DB: {dbStatus === 'connected' ? '在线' : dbStatus === 'disconnected' ? '离线' : '...'}
            </Tag>
            <Dropdown
              menu={{
                items: [
                  { key: 'user', label: user.name, disabled: true },
                  { type: 'divider' },
                  {
                    key: 'logout',
                    icon: <LogoutOutlined />,
                    label: '退出登录',
                    onClick: logout,
                  },
                ],
              }}
            >
              <Button type="text" icon={<UserOutlined />} style={{ color: '#333' }}>
                {user.name}
              </Button>
            </Dropdown>
          </div>
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
          <div key={active} style={{ animation: 'fadeIn 0.25s ease-in' }}>
            <style>{'@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }'}</style>
            {pageMap[active]}
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
