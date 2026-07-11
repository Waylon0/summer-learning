import { useState, useEffect } from 'react';
import { Layout, Menu, Typography, Tag, Button, Dropdown, Spin } from 'antd';
import {
  MessageOutlined,
  DashboardOutlined,
  SearchOutlined,
  AuditOutlined,
  TeamOutlined,
  FileTextOutlined,
  LogoutOutlined,
  UserOutlined,
  ContainerOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  FundOutlined,
  BookOutlined,
} from '@ant-design/icons';
import ChatReimbursement from './pages/ChatReimbursement';
import Dashboard from './pages/Dashboard';
import StatusQuery from './pages/StatusQuery';
import Approval from './pages/Approval';
import UserManagement from './pages/UserManagement';
import DocumentCenter from './pages/DocumentCenter';
import BudgetAdmin from './pages/BudgetAdmin';
import KnowledgeAdmin from './pages/KnowledgeAdmin';
import AuthPage from './pages/Auth';
import { healthCheck } from './services/api';
import { useAuthStore } from './stores';

const { Sider, Content, Header } = Layout;
const { Title, Text } = Typography;

const baseMenuItems = [
  { key: 'chat', icon: <MessageOutlined />, label: '对话报销' },
  { key: 'dashboard', icon: <DashboardOutlined />, label: '报销看板' },
  { key: 'approval', icon: <AuditOutlined />, label: '报销审批' },
  { key: 'status', icon: <SearchOutlined />, label: '进度查询' },
  { key: 'documents', icon: <ContainerOutlined />, label: '单据中心' },
  { key: 'budget', icon: <FundOutlined />, label: '预算管理' },
  { key: 'knowledge', icon: <BookOutlined />, label: '知识库管理' },
];

const adminMenuItem = { key: 'users', icon: <TeamOutlined />, label: '用户管理' };

const roleDefaults: Record<string, string> = {
  employee: 'dashboard',
  manager: 'dashboard',
  finance: 'dashboard',
  admin: 'dashboard',
};

const roleTitles: Record<string, string> = {
  employee: '我的工作台',
  manager: '团队报销管理',
  finance: '财务管理',
  admin: '管理员控制台',
};

export default function App() {
  const { user, token, loading, initialize, logout } = useAuthStore();
  const [active, setActive] = useState(roleDefaults[user?.role || 'employee'] || 'chat');
  const [collapsed, setCollapsed] = useState(false);
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

  // 角色权限：员工不可访问审批页
  if (user && user.role === 'employee' && active === 'approval') {
    setActive('chat');
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <style>{`
        .ant-menu-item {
          transition: all 0.25s ease !important;
        }
        .ant-menu-item:hover {
          transform: scale(1.04) !important;
        }
        .ant-layout-sider-trigger:hover .anticon {
          transform: scale(1.3) !important;
          transition: transform 0.25s ease !important;
        }
        .ant-layout-sider-trigger .anticon {
          transition: transform 0.25s ease !important;
        }
        .ant-layout-sider-trigger {
          background: linear-gradient(90deg, #1e3a5f 0%, #2c5a7a 100%) !important;
        }
        .ant-layout-sider {
          border-radius: 0 12px 12px 0 !important;
        }
      `}</style>
      <Sider
        width={200}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        trigger={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        style={{
          background: 'linear-gradient(90deg, #1e3a5f 0%, #2c5a7a 100%)',
          borderRight: '1px solid rgba(255,255,255,0.08)',
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
          <Title level={5} style={{ color: '#fff', margin: 0, fontWeight: 600, fontSize: collapsed ? 16 : undefined, overflow: 'hidden', whiteSpace: 'nowrap' }}>
            <span style={{ letterSpacing: collapsed ? 6 : 3, transition: 'letter-spacing 0.3s ease' }}>
              R
              <span style={{
                display: 'inline-block',
                maxWidth: collapsed ? 0 : 300,
                opacity: collapsed ? 0 : 1,
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                verticalAlign: 'bottom',
                transition: 'max-width 0.3s ease, opacity 0.2s ease',
              }}>EIMBURSE</span>
            </span>{' '}
            <span style={{ letterSpacing: collapsed ? 6 : 3, transition: 'letter-spacing 0.3s ease' }}>
              A
              <span style={{
                display: 'inline-block',
                maxWidth: collapsed ? 0 : 300,
                opacity: collapsed ? 0 : 1,
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                verticalAlign: 'bottom',
                transition: 'max-width 0.3s ease, opacity 0.2s ease',
              }}>GENT</span>
            </span>
          </Title>
          <Text style={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }}>
            {user.department} · {({ employee: '员工', manager: '经理', finance: '财务', admin: '管理员' })[user.role] || user.role}
          </Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[active]}
          onClick={({ key }) => setActive(key)}
          items={user.role === 'admin' ? [...baseMenuItems, adminMenuItem] : user.role === 'employee' ? baseMenuItems.filter((item) => !['approval', 'budget', 'knowledge'].includes(item.key)) : user.role === 'manager' ? baseMenuItems.filter((item) => !['budget', 'knowledge'].includes(item.key)) : baseMenuItems}
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
            {active === 'chat' ? <ChatReimbursement /> :
             active === 'dashboard' ? <Dashboard /> :
             active === 'approval' ? <Approval /> :
             active === 'status' ? <StatusQuery /> :
             active === 'documents' ? <DocumentCenter /> :
             active === 'budget' ? <BudgetAdmin /> :
             active === 'knowledge' ? <KnowledgeAdmin /> :
             active === 'users' ? <UserManagement /> :
             <Dashboard />}
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
