import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Button, Table, Tag, Space, Input, message, Spin, Empty, Row, Col, Descriptions, Popconfirm, Tabs, Steps,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, RollbackOutlined,
  ReloadOutlined, AuditOutlined, DollarOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getReimbursements, submitApproval, payReimbursement } from '@/services/api';
import { useAuthStore } from '@/stores';
import type { ReimbursementRecord, ApprovalRecord } from '@/types';

const statusMap: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  pending: { color: 'processing', label: '待审批' },
  approved: { color: 'success', label: '已通过' },
  rejected: { color: 'error', label: '已驳回' },
  returned: { color: 'warning', label: '已退回' },
  paid: { color: 'success', label: '已付款' },
  cancelled: { color: 'default', label: '已撤销' },
};

const actionLabels: Record<string, string> = {
  pending: '待审批', approve: '通过', reject: '驳回', return: '退回', pay: '付款', cancelled: '已取消',
};

function getCurrentStage(approvals: ApprovalRecord[]): string | null {
  const p = approvals.find((a) => a.action === 'pending');
  return p ? (p.approver || '') : null;
}

function canAct(role: string, currentStage: string | null, status: string): boolean {
  if (status !== 'pending' || !currentStage) return false;
  if (role === 'admin') return true;
  if (currentStage === '部门经理' && role === 'manager') return true;
  if (currentStage === '财务审批' && (role === 'finance')) return true;
  return false;
}

export default function Approval() {
  const { user } = useAuthStore();
  const userRole = user?.role || 'employee';

  const [activeTab, setActiveTab] = useState<string>('pending');
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<ReimbursementRecord[]>([]);
  const [selected, setSelected] = useState<ReimbursementRecord | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [comment, setComment] = useState('');
  const selectedIdRef = useRef<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { limit: 100 };
      if (activeTab === 'pending') params.status = 'pending';
      else if (activeTab === 'approved') params.status = 'approved';
      const list = await getReimbursements(params);
      setRecords(list);
      // 刷新后同步当前选中记录（用 ref 避免循环依赖）
      const sid = selectedIdRef.current;
      if (sid) {
        const u = list.find((r) => r.id === sid);
        setSelected(u || null);
        if (!u) selectedIdRef.current = null;
      }
    } catch {
      message.error('加载报销列表失败');
    }
    setLoading(false);
  }, [activeTab]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSelect = (r: ReimbursementRecord) => {
    setSelected(r);
    selectedIdRef.current = r.id;
  };

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    setSelected(null);
    selectedIdRef.current = null;
  };

  const handleApprove = async (action: 'approve' | 'reject' | 'return') => {
    if (!selected || !user) return;
    setActionLoading(true);
    try {
      await submitApproval({
        reimbursement_id: selected.id,
        approver: user.name,
        action,
        comment: comment || undefined,
      });
      message.success(action === 'approve' ? '已通过' : action === 'reject' ? '已驳回' : '已退回');
      setComment('');
      fetchData();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败');
    }
    setActionLoading(false);
  };

  const handlePay = async () => {
    if (!selected) return;
    setActionLoading(true);
    try {
      await payReimbursement({ reimbursement_id: selected.id, comment: comment || undefined });
      message.success('付款成功');
      setComment('');
      fetchData();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '付款失败');
    }
    setActionLoading(false);
  };

  const currentStage = selected ? getCurrentStage(selected.approvals) : null;
  const iCanAct = selected ? canAct(userRole, currentStage, selected.status) : false;
  const iCanPay = selected?.status === 'approved' && (userRole === 'finance' || userRole === 'admin');

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
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label || s}</Tag>,
    },
    {
      title: '当前阶段', dataIndex: 'approvals', key: 'stage', width: 110,
      render: (approvals: ApprovalRecord[]) => {
        if (!approvals?.length) return '-';
        const stage = getCurrentStage(approvals);
        return stage ? <Tag color="processing">{stage}</Tag> : <span style={{ color: '#999' }}>-</span>;
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
  ];

  return (
    <div>
      <Card
        title={<Space><AuditOutlined /> 报销审批</Space>}
        extra={<Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>}
        style={{ marginBottom: 16 }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={[
            { key: 'pending', label: '待审批' },
            { key: 'approved', label: '待付款' },
            { key: 'all', label: '全部' },
          ]}
          style={{ marginTop: -8 }}
        />
        <Spin spinning={loading}>
          {records.length === 0 ? (
            <Empty description="暂无报销记录" style={{ padding: 40 }} />
          ) : (
            <Table
              dataSource={records}
              columns={columns}
              rowKey="id"
              size="middle"
              pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }}
              onRow={(r) => ({
                onClick: () => handleSelect(r),
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
                  <Tag color={statusMap[selected.status]?.color}>{statusMap[selected.status]?.label || selected.status}</Tag>
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
              {/* ===== 审批进度 ===== */}
              <Card title="审批进度" size="small" style={{ marginBottom: 16 }}>
                {selected.approvals.length === 0 ? (
                  <Empty description="暂无审批记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                  <Steps
                    direction="vertical"
                    size="small"
                    current={(() => {
                      const idx = selected.approvals.findIndex((a) => a.action === 'pending');
                      return idx >= 0 ? idx : selected.approvals.length;
                    })()}
                    items={selected.approvals.filter((a) => a.action !== 'cancelled').map((a) => {
                      const isPending = a.action === 'pending';
                      const isApprove = a.action === 'approve';
                      const isReject = a.action === 'reject' || a.action === 'return';
                      const isPay = a.action === 'pay';
                      return {
                        title: a.approver || `步骤 ${a.step}`,
                        description: (
                          <div>
                            <Tag color={isPending ? 'processing' : isApprove ? 'success' : isReject ? 'error' : isPay ? 'blue' : 'default'}>
                              {actionLabels[a.action] || a.action}
                            </Tag>
                            {a.comment && <div style={{ color: '#666', fontSize: 12, marginTop: 4 }}>{a.comment}</div>}
                            {a.acted_at && <div style={{ fontSize: 11, color: '#bbb', marginTop: 2 }}>{dayjs(a.acted_at).format('MM-DD HH:mm')}</div>}
                          </div>
                        ),
                        status: isPending ? 'process' : isReject ? 'error' : 'finish',
                      } as never;
                    })}
                  />
                )}
              </Card>

              {/* ===== 审批操作 / 付款操作 ===== */}
              <Card title="操作" size="small">
                {selected.status === 'paid' ? (
                  <Tag icon={<CheckCircleOutlined />} color="success" style={{ padding: '4px 16px', fontSize: 14 }}>已完成付款</Tag>
                ) : selected.status === 'rejected' ? (
                  <Tag color="error" style={{ padding: '4px 16px', fontSize: 14 }}>已驳回</Tag>
                ) : selected.status === 'returned' ? (
                  <Tag color="warning" style={{ padding: '4px 16px', fontSize: 14 }}>已退回，等待申请人修改后重新提交</Tag>
                ) : selected.status === 'cancelled' ? (
                  <Tag color="default" style={{ padding: '4px 16px', fontSize: 14 }}>已撤销</Tag>
                ) : iCanAct ? (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <div style={{ marginBottom: 8 }}>
                      <Tag color="processing">当前阶段：{currentStage}</Tag>
                    </div>
                    <Input.TextArea
                      placeholder="审批意见（可选）"
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      rows={3}
                    />
                    <Space style={{ marginTop: 8 }}>
                      <Popconfirm title="确认通过？" onConfirm={() => handleApprove('approve')} okText="确认" cancelText="取消">
                        <Button type="primary" icon={<CheckCircleOutlined />} loading={actionLoading}>通过</Button>
                      </Popconfirm>
                      <Popconfirm title="确认退回？" onConfirm={() => handleApprove('return')} okText="确认" cancelText="取消">
                        <Button icon={<RollbackOutlined />} loading={actionLoading}>退回</Button>
                      </Popconfirm>
                      <Popconfirm title="确认驳回？" onConfirm={() => handleApprove('reject')} okText="确认" cancelText="取消">
                        <Button danger icon={<CloseCircleOutlined />} loading={actionLoading}>驳回</Button>
                      </Popconfirm>
                    </Space>
                  </Space>
                ) : iCanPay ? (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Tag color="success">两阶段审批已通过，待付款</Tag>
                    <Input.TextArea
                      placeholder="付款备注（可选）"
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      rows={3}
                    />
                    <Popconfirm title="确认付款？" onConfirm={handlePay} okText="确认" cancelText="取消">
                      <Button type="primary" icon={<DollarOutlined />} loading={actionLoading}>出纳付款</Button>
                    </Popconfirm>
                  </Space>
                ) : selected.status === 'pending' ? (
                  <span style={{ color: '#999' }}>等待 {currentStage || '-'} 审批</span>
                ) : (
                  <span style={{ color: '#999' }}>-</span>
                )}
              </Card>
            </Col>
          </Row>
        </Card>
      )}
    </div>
  );
}
