import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Input, Button, Space, Descriptions, Empty, Spin, message, Row, Col,
} from 'antd';
import {
  SearchOutlined, ReloadOutlined, FileTextOutlined, EyeOutlined,
  DownloadOutlined, MailOutlined, CheckCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import { getReimbursements, getReimbursement, generateReimbPdf, sendReimbEmail } from '@/services/api';
import type { ReimbursementRecord } from '@/types';
import { STATUS, ACTION, EXPENSE_TYPE } from '@/constants';

function resolveUrl(url: string): string {
  if (!url) return '';
  if (url.startsWith('http')) return url;
  const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/api\/v1\/?$/, '');
  return base + url;
}

export default function DocumentCenter() {
  const [list, setList] = useState<ReimbursementRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<ReimbursementRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfGenerating, setPdfGenerating] = useState(false);
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getReimbursements({ limit: 100 });
      setList(res);
    } catch { message.error('获取报销单列表失败'); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  const handleSelect = async (r: ReimbursementRecord) => {
    setSelected(r);
    setPdfUrl(null);
    setEmailSent(false);
    setDetailLoading(true);
    try {
      const detail = await getReimbursement(r.id);
      setSelected(detail);
    } catch { /* use list data */ }
    setDetailLoading(false);
  };

  const handleGeneratePdf = async () => {
    if (!selected) return;
    setPdfGenerating(true);
    try {
      const res = await generateReimbPdf(selected.id);
      setPdfUrl(res.download_url);
      message.success('报销单 PDF 已生成');
    } catch {
      message.info('PDF 生成接口暂未就绪，请联系后端开发');
    }
    setPdfGenerating(false);
  };

  const handleSendEmail = async () => {
    if (!selected) return;
    setEmailSending(true);
    try {
      const res = await sendReimbEmail(selected.id);
      if (res.sent) {
        setEmailSent(true);
        message.success(res.message || '邮件已发送');
      } else {
        message.warning(res.message || '邮件发送失败，请检查 SMTP 配置');
      }
    } catch {
      message.error('邮件发送失败，请稍后重试');
    }
    setEmailSending(false);
  };

  const filtered = list.filter((r) => {
    if (!search) return true;
    const kw = search.toLowerCase();
    return r.id.includes(kw) || r.department.includes(kw) || r.user_name.includes(kw)
      || (EXPENSE_TYPE[r.expense_type] || '').includes(kw);
  });

  const invoiceColumns = [
    { title: '发票代码', dataIndex: 'invoice_code', width: 110, render: (v: string) => v || '-' },
    { title: '发票号码', dataIndex: 'invoice_number', width: 100, render: (v: string) => v || '-' },
    { title: '金额', dataIndex: 'amount', width: 90, render: (v: number) => v ? `¥${v.toLocaleString()}` : '-' },
    { title: '开票日期', dataIndex: 'invoice_date', width: 100, render: (v: string) => v || '-' },
    { title: '销售方', dataIndex: 'seller_name', ellipsis: true, render: (v: string) => v || '-' },
  ];

  return (
    <Row gutter={16} style={{ height: 'calc(100vh - 200px)', minHeight: 560 }}>
      {/* ===== 左：报销单列表 ===== */}
      <Col span={8} style={{ height: '100%' }}>
        <Card
          title={<Space><FileTextOutlined />报销单列表</Space>}
          size="small"
          style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
          styles={{ body: { flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 0 } }}
          extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchList} loading={loading} />}
        >
          <div style={{ padding: '8px 12px' }}>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索单号/部门/姓名"
              allowClear
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '0 12px 12px' }}>
            <Spin spinning={loading}>
              {filtered.length === 0 ? (
                <Empty description="暂无报销单" style={{ marginTop: 48 }} />
              ) : (
                filtered.map((r) => (
                  <Card
                    key={r.id}
                    size="small"
                    hoverable
                    style={{
                      marginBottom: 8,
                      borderColor: selected?.id === r.id ? '#1677ff' : undefined,
                      background: selected?.id === r.id ? '#f0f5ff' : undefined,
                    }}
                    onClick={() => handleSelect(r)}
                  >
                    <Row justify="space-between" align="middle">
                      <Col>
                        <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>
                          #{r.id.slice(0, 10)}...
                        </div>
                        <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
                          {r.user_name} · {r.department}
                        </div>
                      </Col>
                      <Col style={{ textAlign: 'right' }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: '#1677ff' }}>
                          ¥{r.total_amount.toLocaleString()}
                        </div>
                        <Tag color={STATUS[r.status]?.color} style={{ marginTop: 2 }}>
                          {STATUS[r.status]?.label || r.status}
                        </Tag>
                      </Col>
                    </Row>
                    <div style={{ marginTop: 6 }}>
                      <Tag>{EXPENSE_TYPE[r.expense_type] || r.expense_type}</Tag>
                      <span style={{ fontSize: 12, color: '#999' }}>{r.invoice_count} 张发票</span>
                      {r.need_special_approval && (
                        <Tag color="red" style={{ marginLeft: 4 }}>特殊审批</Tag>
                      )}
                    </div>
                  </Card>
                ))
              )}
            </Spin>
          </div>
        </Card>
      </Col>

      {/* ===== 右：详情 + 操作 ===== */}
      <Col span={16} style={{ height: '100%' }}>
        <Card
          title="报销单详情"
          size="small"
          style={{ height: '100%', overflow: 'auto' }}
          extra={selected ? <Tag color={STATUS[selected.status]?.color}>{STATUS[selected.status]?.label || selected.status}</Tag> : null}
        >
          <Spin spinning={detailLoading}>
            {!selected ? (
              <Empty description="请在左侧选择一条报销单" style={{ marginTop: 80 }} />
            ) : (
              <>
                {/* 基本信息 */}
                <Descriptions column={3} bordered size="small" style={{ marginBottom: 16 }}>
                  <Descriptions.Item label="报销单号">
                    <span style={{ fontFamily: 'monospace' }}>{selected.id}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="部门">{selected.department}</Descriptions.Item>
                  <Descriptions.Item label="申请人">{selected.user_name}</Descriptions.Item>
                  <Descriptions.Item label="费用类型">
                    <Tag>{EXPENSE_TYPE[selected.expense_type] || selected.expense_type}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="报销金额">
                    <span style={{ fontWeight: 600, color: '#1677ff' }}>¥{selected.total_amount.toLocaleString()}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="发票张数">{selected.invoice_count}</Descriptions.Item>
                  <Descriptions.Item label="提交时间" span={2}>{selected.created_at || '-'}</Descriptions.Item>
                  <Descriptions.Item label="特殊审批">
                    {selected.need_special_approval
                      ? <Tag color="red">是</Tag>
                      : <span style={{ color: '#999' }}>否</span>}
                  </Descriptions.Item>
                  {selected.description && (
                    <Descriptions.Item label="描述" span={3}>{selected.description}</Descriptions.Item>
                  )}
                </Descriptions>

                {/* 发票明细 */}
                {selected.invoices && selected.invoices.length > 0 && (
                  <>
                    <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>
                      <FileTextOutlined style={{ marginRight: 6 }} />发票明细
                    </div>
                    <Table
                      dataSource={selected.invoices as never}
                      columns={invoiceColumns}
                      rowKey={(r: Record<string, unknown>, i?: number) => (r.invoice_code as string) || String(i)}
                      pagination={false}
                      size="small"
                      style={{ marginBottom: 16 }}
                    />
                  </>
                )}

                {/* 审批记录 */}
                {selected.approvals && selected.approvals.length > 0 && (
                  <>
                    <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>
                      <CheckCircleOutlined style={{ marginRight: 6 }} />审批记录
                    </div>
                    {selected.approvals.map((a, i) => (
                      <div key={a.id || i} style={{ marginBottom: 8, padding: '8px 12px', background: '#fafafa', borderRadius: 6 }}>
                        <Space>
                          <Tag color={ACTION[a.action]?.color}>
                            {ACTION[a.action]?.label || a.action}
                          </Tag>
                          <span style={{ fontWeight: 500 }}>{a.approver}</span>
                          <span style={{ color: '#999', fontSize: 12 }}>{a.acted_at || '-'}</span>
                        </Space>
                        {a.comment && <div style={{ marginTop: 4, fontSize: 13, color: '#666' }}>{a.comment}</div>}
                      </div>
                    ))}
                  </>
                )}

                {/* 操作区 */}
                <Card
                  size="small"
                  title={<Space><FileTextOutlined />单据操作</Space>}
                  style={{ marginTop: 16, background: '#fafbfc' }}
                >
                  <Row gutter={[12, 12]}>
                    <Col span={24}>
                      <Space>
                        <Button
                          type="primary"
                          icon={<FileTextOutlined />}
                          onClick={handleGeneratePdf}
                          loading={pdfGenerating}
                        >
                          生成报销单 PDF
                        </Button>
                        {pdfUrl && (
                          <>
                            <Button icon={<EyeOutlined />} onClick={() => window.open(resolveUrl(pdfUrl), '_blank')}>
                              预览
                            </Button>
                            <Button icon={<DownloadOutlined />} href={resolveUrl(pdfUrl)} target="_blank" rel="noreferrer">
                              下载
                            </Button>
                          </>
                        )}
                      </Space>
                    </Col>
                    <Col span={24} style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12 }}>
                      <Space>
                        <Button
                          icon={<MailOutlined />}
                          onClick={handleSendEmail}
                          loading={emailSending}
                        >
                          发送审批邮件
                        </Button>
                        {emailSent ? (
                          <Tag icon={<CheckCircleOutlined />} color="success">已发送</Tag>
                        ) : (
                          <Tag icon={<ExclamationCircleOutlined />} color="default">未发送</Tag>
                        )}
                      </Space>
                    </Col>
                  </Row>
                </Card>
              </>
            )}
          </Spin>
        </Card>
      </Col>
    </Row>
  );
}
