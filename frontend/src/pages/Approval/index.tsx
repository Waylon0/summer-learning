import { useState, useEffect, useCallback } from 'react';
import {
  Card, Button, Table, Tag, Space, Input, message, Spin, Empty, Row, Col, Descriptions, Popconfirm,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, RollbackOutlined,
  ReloadOutlined, AuditOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getReimbursements, submitApproval } from '@/services/api';
import type { ReimbursementRecord } from '@/types';

const statusMap: Record<string, { color: string; label: string }> = {
  pending: { color: 'processing', label: '待审批' },
  approved: { color: 'success', label: '已通过' },
  rejected: { color: 'error', label: '已驳回' },
  returned: { color: 'warning', label: '已退回' },
  paid: { color: 'success', label: '已支付' },
};

export default function Approval() {
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<ReimbursementRecord[]>([]);
  const [selected, setSelected] = useState<ReimbursementRecord | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [comment, setComment] = useState('');

  const fetchPending = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getReimbursements({ status: 'pending', limit: 100 });
      setRecords(list);
      if (selected) {
        const updated = list.find((r) => r.id === selected.id);
        if (updated) setSelected(updated);
      }
    } catch {
      message.error('加载报销列表失败');
    }
    setLoading(false);
  }, [selected]);

  useEffect(() => { fetchPending(); }, [fetchPending]);

  const handleAction = async (action: 'approve' | 'reject' | 'return') => {
    if (!selected) return;
    setActionLoading(true);
    try {
      await submitApproval({
        reimbursement_id: selected.id,
        approver: '当前审批人',
        action,
        comment: comment || undefined,
      });
      message.success(action === 'approve' ? '已通过' : action === 'reject' ? '已驳回' : '已退回');
      setComment('');
      fetchPending();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败');
    }
    setActionLoading(false);
  };

  const columns = [
    { title: '单号', dataIndex: 'id', key: 'id', width: 100, render: (v: string) => v.slice(0, 8) + '...' },
    { title: '申请人', dataIndex: 'user_name', key: 'user_name', width: 80 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 90 },
    { title: '类型', dataIndex: 'expense_type', key: 'expense_type', width: 70, render: (v: string) => ({ travel: '差旅', entertainment: '招待', office: '办公', other: '其他' }[v] || v) },
    {
      title: '金额', dataIndex: 'total_amount', key: 'total_amount', width: 120,
      render: (v: number) => <span style={{ fontWeight: 600, color: '#1677ff' }}>¥{v.toLocaleString()}</span>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label}</Tag>,
    },
    {
      title: '等待', dataIndex: 'created_at', key: 'wait_time', width: 90,
      render: (v: string) => {
        if (!v) return '-';
        const hours = dayjs().diff(dayjs(v), 'hour');
        if (hours < 1) return <span style={{ color: '#52c41a' }}>刚刚</span>;
        if (hours < 24) return <span>{hours} 小时</span>;
        const days = Math.floor(hours / 24);
        return <span style={{ color: hours > 48 ? '#ff4d4f' : undefined, fontWeight: hours > 48 ? 600 : undefined }}>{days} 天</span>;
      },
      sorter: (a: ReimbursementRecord, b: ReimbursementRecord) =>
        (a.created_at ? dayjs(a.created_at).valueOf() : 0) - (b.created_at ? dayjs(b.created_at).valueOf() : 0),
      defaultSortOrder: 'ascend' as const,
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
  ];

  const sortedRecords = [...records].sort((a, b) => {
    if (a.status === 'pending' && b.status !== 'pending') return -1;
    if (a.status !== 'pending' && b.status === 'pending') return 1;
    return (a.created_at ? dayjs(a.created_at).valueOf() : 0) - (b.created_at ? dayjs(b.created_at).valueOf() : 0);
  });

  return (
    <div>
      <Card
        title={
          <Space>
            <AuditOutlined /> 报销审批
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => fetchPending()} loading={loading}>刷新</Button>
        }
        style={{ marginBottom: 16 }}
      >
        <Spin spinning={loading}>
          {records.length === 0 ? (
            <Empty description="暂无报销记录" style={{ padding: 40 }} />
          ) : (
            <Table
              dataSource={sortedRecords}
              columns={columns}
              rowKey="id"
              size="middle"
              pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }}
              rowClassName={(r) => r.status === 'pending' ? 'ant-table-row-selected' : ''}
              onRow={(r) => ({
                onClick: () => setSelected(r),
                style: { cursor: 'pointer' },
              })}
            />
          )}
        </Spin>
      </Card>

      {selected && (
        <Card
          title={`报销单详情 — ${selected.id.slice(0, 12)}...`}
          extra={<Button onClick={() => setSelected(null)}>收起</Button>}
        >
          <Row gutter={[16, 16]}>
            <Col span={14}>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="申请人">{selected.user_name}</Descriptions.Item>
                <Descriptions.Item label="部门">{selected.department}</Descriptions.Item>
                <Descriptions.Item label="费用类型">
                  <Tag>{({ travel: '差旅', entertainment: '招待', office: '办公', other: '其他' })[selected.expense_type] || selected.expense_type}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="金额">
                  <span style={{ fontWeight: 600, color: '#1677ff', fontSize: 16 }}>¥{selected.total_amount.toLocaleString()}</span>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={statusMap[selected.status]?.color}>{statusMap[selected.status]?.label}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="发票数">{selected.invoice_count}</Descriptions.Item>
                <Descriptions.Item label="说明" span={2}>{selected.description || '-'}</Descriptions.Item>
                {selected.budget_remaining_after != null && (
                  <Descriptions.Item label="报销后剩余预算" span={2}>
                    ¥{selected.budget_remaining_after.toLocaleString()}
                  </Descriptions.Item>
                )}
                {selected.need_special_approval && (
                  <Descriptions.Item label="特殊审批" span={2}>
                    <Tag color="red">⚠ 预算超标，需特殊审批</Tag>
                  </Descriptions.Item>
                )}
              </Descriptions>

              {selected.invoices.length > 0 && (
                <Card title="发票明细" size="small" style={{ marginTop: 16 }}>
                  {selected.invoices.map((inv, i) => (
                    <div key={inv.id || i} style={{ padding: '8px 12px', marginBottom: 8, background: '#fafafa', borderRadius: 6 }}>
                      <Space wrap>
                        <Tag color="blue">#{i + 1}</Tag>
                        <span>代码: {inv.invoice_code || '-'}</span>
                        <span>号码: {inv.invoice_number || '-'}</span>
                        <span style={{ fontWeight: 600 }}>¥{inv.amount?.toLocaleString() || '-'}</span>
                        <span style={{ color: '#999' }}>{inv.invoice_date}</span>
                      </Space>
                      {inv.seller_name && <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>销售方: {inv.seller_name}</div>}
                    </div>
                  ))}
                </Card>
              )}
            </Col>

            <Col span={10}>
              <Card title="审批历史" size="small" style={{ marginBottom: 16 }}>
                {selected.approvals.length === 0 ? (
                  <Empty description="暂无审批记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                  selected.approvals.map((a, idx) => (
                    <div key={a.id || idx} style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 6, border: '1px solid #f0f0f0' }}>
                      <Space>
                        <strong>{a.approver}</strong>
                        <Tag color={a.action === 'approve' ? 'success' : a.action === 'reject' ? 'error' : 'warning'}>
                          {{ approve: '通过', reject: '驳回', return: '退回', pending: '待审批' }[a.action] || a.action}
                        </Tag>
                        <span style={{ fontSize: 12, color: '#999' }}>Step {a.step}</span>
                      </Space>
                      {a.comment && <div style={{ color: '#666', marginTop: 4, fontSize: 13 }}>{a.comment}</div>}
                      <div style={{ fontSize: 11, color: '#bbb', marginTop: 2 }}>
                        {a.acted_at ? dayjs(a.acted_at).format('MM-DD HH:mm') : '-'}
                      </div>
                    </div>
                  ))
                )}
              </Card>

              <Card title="审批操作" size="small">
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Input.TextArea
                    placeholder="审批意见（可选）"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    rows={3}
                  />
                  <Space style={{ marginTop: 8 }}>
                    <Popconfirm
                      title="确认通过此报销申请？"
                      onConfirm={() => handleAction('approve')}
                      okText="确认通过"
                      cancelText="取消"
                    >
                      <Button
                        type="primary"
                        icon={<CheckCircleOutlined />}
                        loading={actionLoading}
                        disabled={selected.status !== 'pending'}
                      >
                        通过
                      </Button>
                    </Popconfirm>
                    <Popconfirm
                      title="确认退回此报销申请？"
                      onConfirm={() => handleAction('return')}
                      okText="确认退回"
                      cancelText="取消"
                    >
                      <Button
                        icon={<RollbackOutlined />}
                        loading={actionLoading}
                        disabled={selected.status !== 'pending'}
                      >
                        退回
                      </Button>
                    </Popconfirm>
                    <Popconfirm
                      title="确认驳回此报销申请？"
                      onConfirm={() => handleAction('reject')}
                      okText="确认驳回"
                      cancelText="取消"
                    >
                      <Button
                        danger
                        icon={<CloseCircleOutlined />}
                        loading={actionLoading}
                        disabled={selected.status !== 'pending'}
                      >
                        驳回
                      </Button>
                    </Popconfirm>
                  </Space>
                </Space>
              </Card>
            </Col>
          </Row>
        </Card>
      )}
    </div>
  );
}
