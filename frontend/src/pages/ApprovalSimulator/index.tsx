import { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Modal, Input, Space, Segmented, message, Empty, Spin,
} from 'antd';
import { CheckOutlined, CloseOutlined, ReloadOutlined, UndoOutlined } from '@ant-design/icons';
import { getReimbursements, submitApproval } from '@/services/api';
import type { ReimbursementRecord } from '@/types';

const statusMap: Record<string, { color: string; label: string }> = {
  pending: { color: 'processing', label: '待审批' },
  approved: { color: 'success', label: '已通过' },
  rejected: { color: 'error', label: '已驳回' },
  returned: { color: 'warning', label: '已退回' },
  paid: { color: 'success', label: '已支付' },
};

const statusFilters = [
  { label: '全部', value: '' },
  { label: '待审批', value: 'pending' },
  { label: '已通过', value: 'approved' },
  { label: '已驳回', value: 'rejected' },
];

export default function ApprovalSimulator() {
  const [records, setRecords] = useState<ReimbursementRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('pending');
  const [modalOpen, setModalOpen] = useState(false);
  const [current, setCurrent] = useState<ReimbursementRecord | null>(null);
  const [action, setAction] = useState<'approve' | 'reject' | 'return'>('approve');
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: { status?: string; limit: number } = { limit: 50 };
      if (filter) params.status = filter;
      const list = await getReimbursements(params);
      setRecords(list);
    } catch {
      message.error('获取报销单列表失败');
    }
    setLoading(false);
  }, [filter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openModal = (r: ReimbursementRecord, act: 'approve' | 'reject' | 'return') => {
    setCurrent(r);
    setAction(act);
    setComment('');
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    if (!current) return;
    setSubmitting(true);
    try {
      await submitApproval({
        reimbursement_id: current.id,
        approver: '财务部-张总监',
        action,
        comment: comment || undefined,
      });
      message.success(`${action === 'approve' ? '已通过' : action === 'reject' ? '已驳回' : '已退回'}报销单 ${current.id.slice(0, 8)}...`);
      setModalOpen(false);
      fetchData();
    } catch {
      message.error('审批操作失败，请检查后端服务');
    }
    setSubmitting(false);
  };

  const columns = [
    { title: '报销单号', dataIndex: 'id', key: 'id', width: 120, render: (v: string) => v.slice(0, 8) + '...' },
    { title: '申请人', dataIndex: 'user_name', key: 'user_name', width: 100 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100 },
    { title: '费用类型', dataIndex: 'expense_type', key: 'expense_type', width: 100 },
    {
      title: '金额', dataIndex: 'total_amount', key: 'total_amount', width: 120,
      render: (v: number) => <span style={{ fontWeight: 600 }}>¥{v.toLocaleString()}</span>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label}</Tag>,
    },
    {
      title: '超标', dataIndex: 'need_special_approval', key: 'need_special_approval', width: 70,
      render: (v: boolean) => v ? <Tag color="red">是</Tag> : <Tag>否</Tag>,
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_: unknown, r: ReimbursementRecord) => (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<CheckOutlined />}
            disabled={r.status !== 'pending'}
            onClick={() => openModal(r, 'approve')}
          >
            通过
          </Button>
          <Button
            danger
            size="small"
            icon={<CloseOutlined />}
            disabled={r.status !== 'pending'}
            onClick={() => openModal(r, 'reject')}
          >
            驳回
          </Button>
          <Button
            size="small"
            icon={<UndoOutlined />}
            disabled={r.status !== 'pending'}
            onClick={() => openModal(r, 'return')}
          >
            退回
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Segmented
          options={statusFilters}
          value={filter}
          onChange={(v) => setFilter(v as string)}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          刷新
        </Button>
      </div>

      <Spin spinning={loading}>
        {records.length === 0 ? (
          <Empty description="暂无报销记录" style={{ padding: 80 }} />
        ) : (
          <Table
            dataSource={records}
            columns={columns}
            rowKey="id"
            size="middle"
            pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }}
            scroll={{ x: 1100 }}
          />
        )}
      </Spin>

      <Modal
        title={`${action === 'approve' ? '通过' : action === 'reject' ? '驳回' : '退回'}报销单`}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        okText={action === 'approve' ? '确认通过' : action === 'reject' ? '确认驳回' : '确认退回'}
        okButtonProps={{ danger: action === 'reject' }}
      >
        {current && (
          <div style={{ marginBottom: 16 }}>
            <p><strong>报销单号：</strong>{current.id}</p>
            <p><strong>申请人：</strong>{current.user_name}（{current.department}）</p>
            <p><strong>费用类型：</strong>{current.expense_type}</p>
            <p><strong>金额：</strong>¥{current.total_amount.toLocaleString()}</p>
            {current.need_special_approval && (
              <Tag color="red" style={{ marginTop: 4 }}>注意：此单已超标，需要特殊审批</Tag>
            )}
          </div>
        )}
        <Input.TextArea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="审批意见（可选）"
          rows={3}
        />
      </Modal>
    </div>
  );
}
