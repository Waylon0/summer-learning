import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Tag, Button, Modal, Select, message, Space, Spin } from 'antd';
import { TeamOutlined, ReloadOutlined, CrownOutlined } from '@ant-design/icons';
import { listUsers, updateUserRole } from '@/services/api';
import type { UserInfo } from '@/types';

const roleMap: Record<string, { color: string; label: string }> = {
  employee: { color: 'default', label: '员工' },
  manager: { color: 'blue', label: '部门经理' },
  finance: { color: 'green', label: '财务' },
  admin: { color: 'red', label: '超级管理员' },
};

const roleOptions = [
  { value: 'employee', label: '员工' },
  { value: 'manager', label: '部门经理' },
  { value: 'finance', label: '财务' },
  { value: 'admin', label: '超级管理员' },
];

export default function UserManagement() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserInfo | null>(null);
  const [newRole, setNewRole] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listUsers();
      setUsers(list);
    } catch {
      message.error('获取用户列表失败，请联系后端确认 /admin/users 接口已实现');
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handlePromote = (user: UserInfo) => {
    setSelectedUser(user);
    setNewRole(user.role);
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    if (!selectedUser || newRole === selectedUser.role) {
      setModalOpen(false);
      return;
    }
    setSubmitting(true);
    try {
      await updateUserRole(selectedUser.id, newRole);
      message.success(`${selectedUser.name} 角色已更新为 ${roleMap[newRole]?.label}`);
      setModalOpen(false);
      fetchUsers();
    } catch {
      message.error('操作失败，请确认 /admin/users/{id}/role 接口已实现');
    }
    setSubmitting(false);
  };

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username', width: 120 },
    { title: '姓名', dataIndex: 'name', key: 'name', width: 100 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 110 },
    { title: '邮箱', dataIndex: 'email', key: 'email', width: 180, render: (v: string) => v || '-' },
    {
      title: '角色', dataIndex: 'role', key: 'role', width: 110,
      render: (r: string) => <Tag color={roleMap[r]?.color}>{roleMap[r]?.label || r}</Tag>,
    },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 80,
      render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '正常' : '禁用'}</Tag>,
    },
    {
      title: '注册时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: unknown, record: UserInfo) => (
        <Button
          type="link"
          icon={<CrownOutlined />}
          onClick={() => handlePromote(record)}
          disabled={record.role === 'admin'}
        >
          {record.role === 'admin' ? '已是最高' : '变更角色'}
        </Button>
      ),
    },
  ];

  return (
    <Card
      title={<Space><TeamOutlined /> 用户管理</Space>}
      extra={<Button icon={<ReloadOutlined />} onClick={fetchUsers} loading={loading}>刷新</Button>}
    >
      <Spin spinning={loading}>
        <Table
          dataSource={users}
          columns={columns}
          rowKey="id"
          size="middle"
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 人` }}
        />
      </Spin>

      <Modal
        title="变更用户角色"
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        okText="确认变更"
        okButtonProps={{ danger: newRole === 'admin' }}
      >
        {selectedUser && (
          <div style={{ marginBottom: 16 }}>
            <p><strong>用户：</strong>{selectedUser.name}（{selectedUser.username}）</p>
            <p><strong>部门：</strong>{selectedUser.department}</p>
            <p><strong>当前角色：</strong><Tag color={roleMap[selectedUser.role]?.color}>{roleMap[selectedUser.role]?.label}</Tag></p>
          </div>
        )}
        <Select
          style={{ width: '100%' }}
          value={newRole}
          onChange={setNewRole}
          options={roleOptions}
        />
      </Modal>
    </Card>
  );
}
