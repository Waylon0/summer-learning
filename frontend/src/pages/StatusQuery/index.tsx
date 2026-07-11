import { useState, useCallback, useEffect } from 'react';
import {
  Card, Input, Button, Table, Tag, Space, Timeline, Segmented, DatePicker, Empty, Spin, Row, Col,
} from 'antd';
import { SearchOutlined, ReloadOutlined, ClockCircleOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { getReimbursements, getReimbursement } from '@/services/api';
import type { ReimbursementRecord, ApprovalRecord } from '@/types';

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
  { label: '已退回', value: 'returned' },
  { label: '已支付', value: 'paid' },
];

const actionIcons: Record<string, React.ReactNode> = {
  approve: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  reject: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  return: <ClockCircleOutlined style={{ color: '#faad14' }} />,
};

const actionLabels: Record<string, string> = {
  approve: '通过',
  reject: '驳回',
  return: '退回',
};

function ApprovalTimeline({ approvals }: { approvals: ApprovalRecord[] }) {
  return (
    <Timeline
      items={[
        { color: 'blue', children: <div style={{ fontWeight: 500 }}>提交报销申请</div> },
        ...approvals.map((a) => ({
          color: a.action === 'approve' ? 'green' : a.action === 'reject' ? 'red' : 'orange',
          dot: actionIcons[a.action],
          children: (
            <div>
              <Space>
                <strong>{a.approver}</strong>
                <Tag color={a.action === 'approve' ? 'success' : a.action === 'reject' ? 'error' : 'warning'}>
                  {actionLabels[a.action]}
                </Tag>
                <span style={{ fontSize: 12, color: '#999' }}>
                  {a.acted_at ? dayjs(a.acted_at).format('MM-DD HH:mm') : '-'}
                </span>
              </Space>
              {a.comment && (
                <div style={{ color: '#666', marginTop: 4, fontSize: 13, fontStyle: 'italic' }}>
                  "{a.comment}"
                </div>
              )}
            </div>
          ),
        })),
      ]}
    />
  );
}

export default function StatusQuery() {
  const [searchId, setSearchId] = useState('');
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<ReimbursementRecord[]>([]);
  const [allRecords, setAllRecords] = useState<ReimbursementRecord[]>([]);
  const [detail, setDetail] = useState<ReimbursementRecord | null>(null);
  const [filter, setFilter] = useState('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getReimbursements({ limit: 100 });
      setAllRecords(list);
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    let filtered = [...allRecords];
    if (filter) {
      filtered = filtered.filter((r) => r.status === filter);
    }
    if (dateRange && dateRange[0] && dateRange[1]) {
      const start = dateRange[0].startOf('day');
      const end = dateRange[1].endOf('day');
      filtered = filtered.filter((r) => {
        if (!r.created_at) return false;
        const d = dayjs(r.created_at);
        return d.isAfter(start) && d.isBefore(end);
      });
    }
    setRecords(filtered);
  }, [allRecords, filter, dateRange]);

  const handleSearch = async () => {
    if (!searchId.trim()) return;
    setLoading(true);
    try {
      const r = await getReimbursement(searchId.trim());
      setDetail(r);
    } catch {
      setDetail(null);
    }
    setLoading(false);
  };

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="none">
            <Segmented
              options={statusFilters}
              value={filter}
              onChange={(v) => setFilter(v as string)}
            />
          </Col>
          <Col flex="auto" />
        </Row>
        <Row gutter={[16, 12]} align="middle">
          <Col>
            <Space>
              <Input
                placeholder="输入报销单号"
                value={searchId}
                onChange={(e) => setSearchId(e.target.value)}
                onPressEnter={handleSearch}
                style={{ width: 300 }}
                allowClear
              />
              <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
                精确查询
              </Button>
            </Space>
          </Col>
          <Col flex="auto" />
          <Col>
            <DatePicker.RangePicker
              value={dateRange as [dayjs.Dayjs | null, dayjs.Dayjs | null]}
              onChange={(v) => setDateRange(v ? [v[0], v[1]] : null)}
              allowClear
              placeholder={['开始日期', '结束日期']}
              style={{ width: 240 }}
            />
          </Col>
          <Col>
            <Button icon={<ReloadOutlined />} onClick={fetchAll} loading={loading}>
              刷新
            </Button>
          </Col>
        </Row>
      </Card>

      {detail && (
        <Card
          title={`报销单详情 — ${detail.id.slice(0, 12)}...`}
          extra={<Button onClick={() => setDetail(null)}>返回列表</Button>}
          style={{ marginBottom: 16 }}
        >
          <Row gutter={[16, 0]}>
            <Col span={12}>
              <Card size="small" title="基本信息" style={{ marginBottom: 16 }}>
                <table style={{ width: '100%', lineHeight: 2.4, fontSize: 14 }}>
                  <tbody>
                    <tr><td style={{ color: '#999' }}>申请人</td><td>{detail.user_name}</td></tr>
                    <tr><td style={{ color: '#999' }}>部门</td><td>{detail.department}</td></tr>
                    <tr><td style={{ color: '#999' }}>费用类型</td><td>{detail.expense_type}</td></tr>
                    <tr><td style={{ color: '#999' }}>金额</td><td style={{ fontWeight: 600, color: '#1677ff', fontSize: 16 }}>¥{detail.total_amount.toLocaleString()}</td></tr>
                    <tr><td style={{ color: '#999' }}>状态</td><td><Tag color={statusMap[detail.status]?.color}>{statusMap[detail.status]?.label}</Tag></td></tr>
                    <tr><td style={{ color: '#999' }}>创建时间</td><td>{detail.created_at ? dayjs(detail.created_at).format('YYYY-MM-DD HH:mm') : '-'}</td></tr>
                  </tbody>
                </table>
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title="发票明细" style={{ marginBottom: 16 }}>
                {detail.invoices.length === 0 ? (
                  <Empty description="无发票记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                  detail.invoices.map((inv, i) => (
                    <div key={inv.id || i} style={{ marginBottom: 10, padding: '8px 12px', background: '#fafafa', borderRadius: 6 }}>
                      <Space>
                        <Tag>发票 {i + 1}</Tag>
                        <span>{inv.invoice_code || '-'}</span>
                        <span style={{ fontWeight: 500, color: '#1677ff' }}>¥{inv.amount?.toLocaleString() || '-'}</span>
                      </Space>
                      {inv.seller_name && <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>销售方: {inv.seller_name}</div>}
                    </div>
                  ))
                )}
              </Card>
            </Col>
          </Row>
          <Card size="small" title="审批流程">
            {detail.approvals.length === 0 ? (
              <Empty description="暂无审批记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <ApprovalTimeline approvals={detail.approvals} />
            )}
          </Card>
        </Card>
      )}

      <Card title="报销记录列表">
        <Spin spinning={loading}>
          {records.length === 0 ? (
            <Empty
              description={allRecords.length === 0 ? '暂无报销记录' : '没有匹配的记录'}
              style={{ padding: 60 }}
            />
          ) : (
            <Table
              dataSource={records}
              style={{ width: '100%' }}
              columns={[
                { title: '报销单号', dataIndex: 'id', key: 'id', width: 140, render: (v: string) => v.slice(0, 8) + '...' },
                { title: '申请人', dataIndex: 'user_name', key: 'user_name', width: 100 },
                { title: '部门', dataIndex: 'department', key: 'department', width: 100 },
                { title: '费用类型', dataIndex: 'expense_type', key: 'expense_type', width: 100 },
                {
                  title: '金额', dataIndex: 'total_amount', key: 'total_amount', width: 130,
                  render: (v: number) => <span style={{ fontWeight: 600 }}>¥{v.toLocaleString()}</span>,
                },
                {
                  title: '状态', dataIndex: 'status', key: 'status', width: 90,
                  render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label}</Tag>,
                },
                {
                  title: '创建时间', dataIndex: 'created_at', key: 'created_at', flex: 1,
                  render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
                },
              ]}
              rowKey="id"
              size="middle"
              pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }}
              onRow={(r) => ({
                onClick: () => { setDetail(r); },
                style: { cursor: 'pointer' },
              })}
            />
          )}
        </Spin>
      </Card>
    </div>
  );
}
