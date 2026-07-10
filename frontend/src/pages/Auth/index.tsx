import { useState } from 'react';
import { Card, Form, Input, Button, Select, Tabs, message, Typography, ConfigProvider } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined, IdcardOutlined, TeamOutlined } from '@ant-design/icons';
import { login, register } from '@/services/api';
import { useAuthStore } from '@/stores';
import type { LoginRequest, RegisterRequest } from '@/types';

const { Title, Text } = Typography;

const DEPARTMENTS = ['技术部', '研发部', '市场部', '销售部', '财务部', '人力资源部', '行政部', '运维部'];

export default function AuthPage() {
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('login');
  const { setAuth } = useAuthStore();

  const handleLogin = async (values: LoginRequest) => {
    setLoading(true);
    try {
      const res = await login(values);
      setAuth(res.access_token, res.user);
      message.success(`欢迎回来，${res.user.name}`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '登录失败');
    }
    setLoading(false);
  };

  const handleRegister = async (values: RegisterRequest) => {
    setLoading(true);
    try {
      const res = await register({ ...values, role: 'employee' });
      setAuth(res.access_token, res.user);
      message.success(`注册成功，欢迎 ${res.user.name}`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '注册失败');
    }
    setLoading(false);
  };

  const tabItems = [
    {
      key: 'login',
      label: '登录',
      children: (
        <Form
          name="login"
          onFinish={handleLogin}
          layout="vertical"
          size="large"
          autoComplete="off"
        >
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block className="auth-btn">
              登 录
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'register',
      label: '注册',
      children: (
        <Form
          name="register"
          onFinish={handleRegister}
          layout="vertical"
          size="large"
          autoComplete="off"
        >
          <Form.Item name="username" rules={[{ required: true, min: 3, message: '至少3位字符' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 6, message: '至少6位字符' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item name="name" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input prefix={<IdcardOutlined />} placeholder="姓名" />
          </Form.Item>
          <Form.Item name="department" rules={[{ required: true, message: '请选择部门' }]}>
            <Select
              placeholder="选择部门"
              prefix={<TeamOutlined />}
              options={DEPARTMENTS.map((d) => ({ label: d, value: d }))}
              showSearch
            />
          </Form.Item>
          <Form.Item name="email" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input prefix={<MailOutlined />} placeholder="邮箱（可选）" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block className="auth-btn">
              注 册
            </Button>
          </Form.Item>
        </Form>
      ),
    },
  ];

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#667eea' } }}>
      <style>{`
        .auth-btn:hover {
          transform: scale(1.03) !important;
          box-shadow: 0 4px 20px rgba(102, 126, 234, 0.5) !important;
          transition: all 0.25s ease !important;
        }
        .auth-btn {
          transition: all 0.25s ease !important;
        }

      `}</style>
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}>
        <Card
          style={{ width: 480, borderRadius: 12, boxShadow: '0 8px 40px rgba(0,0,0,0.12)' }}
          styles={{ body: { padding: '32px 32px 24px' } }}
        >
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <Title level={3} style={{ margin: 0, letterSpacing: 4, background: 'linear-gradient(135deg, #667eea, #764ba2)', backgroundClip: 'text', WebkitBackgroundClip: 'text', color: 'transparent' }}>REIMBURSE AGENT</Title>
            <Text style={{ color: '#667eea' }}>企业财务报销助手</Text>
          </div>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            centered
            items={tabItems}
            style={{ marginBottom: -16 }}
          />
        </Card>
      </div>
    </ConfigProvider>
  );
}
