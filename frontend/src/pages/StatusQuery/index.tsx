import { useState } from 'react';
import { Card, Input, Button, Table, Tag, Space, Timeline, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { getReimbursements, getReimbursement } from '@/services/api';
import type { ReimbursementRecord } from '@/types';

const statusMap: Record<string, { color: string; label: string }> = {
  pending: { color: 'processing', label: '待审批' },
  approved: { color: 'success', label: '已通过' },
  rejected: { color: 'error', label: '已驳回' },
  returned: { color: 'warning', label: '已退回' },
  paid: { color: 'success', label: '已支付' },
};

export default function StatusQuery() {
  const [searchId, setSearchId] = useState('');
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<ReimbursementRecord[]>([]);
  const [detail, setDetail] = useState<ReimbursementRecord | null>(null);

  const handleSearch = async () => {
    if (!searchId.trim()) {
      message.warning('请输入报销单号');
      return;
    }
    setLoading(true);
    try {
      const r = await getReimbursement(searchId.trim());
      setDetail(r);
      setRecords([]);
    } catch {
      setDetail(null);
    }
    setLoading(false);
  };

  const handleListAll = async () => {
    setLoading(true);
    try {
      const list = await getReimbursements({ limit: 20 });
      setRecords(list);
      setDetail(null);
    } catch {
      message.error('查询失败');
    }
    setLoading(false);
  };

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Input
            placeholder="输入报销单号"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 320 }}
            allowClear
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
            精确查询
          </Button>
          <Button onClick={handleListAll}>查看全部</Button>
        </Space>
      </Card>

      {detail && (
        <Card title={`报销单 ${detail.id}`}>
          <Table
            dataSource={[
              { key: '用户', value: detail.user_name },
              { key: '部门', value: detail.department },
              { key: '费用类型', value: detail.expense_type },
              { key: '金额', value: `¥${detail.total_amount.toLocaleString()}` },
              { key: '票据数', value: detail.invoice_count },
              { key: '状态', value: <Tag color={statusMap[detail.status]?.color}>{statusMap[detail.status]?.label}</Tag> },
              { key: '创建时间', value: detail.created_at },
            ]}
            columns={[
              { title: '字段', dataIndex: 'key', width: 120 },
              { title: '值', dataIndex: 'value' },
            ]}
            pagination={false}
            size="small"
          />
          {detail.approvals.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <strong>审批流程</strong>
              <Timeline
                items={detail.approvals.map((a) => ({
                  color: a.action === 'approve' ? 'green' : a.action === 'reject' ? 'red' : 'blue',
                  children: (
                    <div>
                      <strong>{a.approver}</strong> — {a.action}
                      {a.comment && <div style={{ color: '#666' }}>{a.comment}</div>}
                      <div style={{ fontSize: 12, color: '#999' }}>{a.acted_at}</div>
                    </div>
                  ),
                }))}
              />
            </div>
          )}
        </Card>
      )}

      {records.length > 0 && (
        <Card title="报销记录列表">
          <Table
            dataSource={records}
            columns={[
              { title: '报销单号', dataIndex: 'id', key: 'id', width: 100, render: (v: string) => v.slice(0, 8) + '...' },
              { title: '用户', dataIndex: 'user_name', key: 'user_name' },
              { title: '部门', dataIndex: 'department', key: 'department' },
              { title: '类型', dataIndex: 'expense_type', key: 'expense_type' },
              { title: '金额', dataIndex: 'total_amount', key: 'total_amount', render: (v: number) => `¥${v.toLocaleString()}` },
              {
                title: '状态', dataIndex: 'status', key: 'status',
                render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label}</Tag>,
              },
            ]}
            rowKey="id"
            size="middle"
            onRow={(r) => ({
              onClick: () => { setDetail(r); setRecords([]); },
              style: { cursor: 'pointer' },
            })}
          />
        </Card>
      )}
    </div>
  );
}
