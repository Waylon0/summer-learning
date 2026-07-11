import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Tag, Input, InputNumber, Select, DatePicker, Button, Space, Row, Col, Drawer, Modal, Descriptions, message, Spin, Alert } from 'antd';
import { SearchOutlined, ReloadOutlined, FileTextOutlined, PlusOutlined, EyeOutlined, DownloadOutlined, CopyOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { getInvoices, generateInvoice } from '@/services/api';
import type { InvoiceRecord, InvoiceGenerateRequest, InvoiceGenerateResponse } from '@/types';
import { EXPENSE_TYPE } from '@/constants';

function resolveDownloadUrl(url: string): string {
  if (url.startsWith('http')) return url;
  const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/api\/v1\/?$/, '');
  return base + url;
}

export default function InvoiceLedger() {
  const [data, setData] = useState<InvoiceRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<InvoiceRecord | null>(null);
  const [genOpen, setGenOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState<InvoiceGenerateResponse | null>(null);
  const [genForm, setGenForm] = useState<InvoiceGenerateRequest>({
    invoice_type: '增值税普通发票',
    seller_name: '',
    amount: undefined,
    tax_amount: 0,
    total_with_tax: undefined,
    remarks: '',
  });

  const [filters, setFilters] = useState<Record<string, string>>({});

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { page, page_size: 20 };
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to) params.date_to = filters.date_to;
      if (filters.expense_type) params.expense_type = filters.expense_type;
      if (filters.seller_name) params.seller_name = filters.seller_name;
      if (filters.keyword) params.keyword = filters.keyword;
      const res = await getInvoices(params as never);
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error('获取发票列表失败');
    }
    setLoading(false);
  }, [page, filters]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns = [
    { title: '发票代码', dataIndex: 'invoice_code', key: 'invoice_code', width: 130, render: (v: string) => v || '-' },
    { title: '发票号码', dataIndex: 'invoice_number', key: 'invoice_number', width: 110, render: (v: string) => v || '-' },
    {
      title: '金额', dataIndex: 'amount', key: 'amount', width: 110,
      render: (v: number) => <span style={{ fontWeight: 600, color: '#1677ff' }}>¥{v?.toLocaleString() || '-'}</span>,
    },
    { title: '开票日期', dataIndex: 'invoice_date', key: 'invoice_date', width: 110, render: (v: string) => v || '-' },
    {
      title: '费用类型', dataIndex: 'expense_type', key: 'expense_type', width: 80,
      render: (v: string) => <Tag>{EXPENSE_TYPE[v] || v || '-'}</Tag>,
    },
    { title: '销售方', dataIndex: 'seller_name', key: 'seller_name', width: 180, ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '报销单', dataIndex: 'reimbursement_id', key: 'reimbursement_id', width: 110,
      render: (v: string) => v ? <Tag color="blue">{v.slice(0, 8)}...</Tag> : <span style={{ color: '#ccc' }}>未关联</span>,
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[12, 8]} align="middle">
          <Col><DatePicker placeholder="开始日期" onChange={(d) => setFilters((f) => ({ ...f, date_from: d?.format('YYYY-MM-DD') || '' }))} allowClear /></Col>
          <Col><DatePicker placeholder="结束日期" onChange={(d) => setFilters((f) => ({ ...f, date_to: d?.format('YYYY-MM-DD') || '' }))} allowClear /></Col>
          <Col>
            <Select
              placeholder="费用类型" allowClear style={{ width: 100 }}
              onChange={(v) => setFilters((f) => ({ ...f, expense_type: v || '' }))}
              options={Object.entries(EXPENSE_TYPE).map(([k, v]) => ({ value: k, label: v }))}
            />
          </Col>
          <Col>
            <Input placeholder="销售方" allowClear style={{ width: 140 }}
              onChange={(e) => setFilters((f) => ({ ...f, seller_name: e.target.value }))} />
          </Col>
          <Col>
            <Input placeholder="发票代码/号码" allowClear style={{ width: 160 }}
              prefix={<SearchOutlined />}
              onChange={(e) => setFilters((f) => ({ ...f, keyword: e.target.value }))} />
          </Col>
          <Col flex="auto" />
          <Col><Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>查询</Button></Col>
          <Col><Button type="primary" icon={<PlusOutlined />} onClick={() => setGenOpen(true)}>生成发票</Button></Col>
        </Row>
      </Card>

      {genResult && (
        <Alert
          type="success"
          showIcon={false}
          closable
          onClose={() => setGenResult(null)}
          style={{ marginBottom: 16, borderColor: '#b7eb8f', background: '#f6ffed' }}
          message={
            <Row align="middle" justify="space-between">
              <Col>
                <span style={{ fontWeight: 600, fontSize: 14 }}>发票已生成</span>
                <span style={{ marginLeft: 16, color: '#666', fontSize: 13 }}>
                  号码：{genResult.invoice_number} &nbsp;|&nbsp;
                  代码：{genResult.invoice_code} &nbsp;|&nbsp;
                  金额：<span style={{ fontWeight: 600, color: '#1677ff' }}>¥{genResult.total_with_tax.toLocaleString()}</span>
                </span>
              </Col>
              <Col>
                <Space>
                  <Button
                    type="primary"
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => window.open(resolveDownloadUrl(genResult.download_url), '_blank')}
                  >
                    预览发票
                  </Button>
                  <Button
                    size="small"
                    icon={<DownloadOutlined />}
                    href={resolveDownloadUrl(genResult.download_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载
                  </Button>
                  <Button
                    size="small"
                    icon={<CopyOutlined />}
                    onClick={() => {
                      navigator.clipboard.writeText(genResult.object_name);
                      message.success('已复制对象名，可粘贴到对话报销中作为附件');
                    }}
                  >
                    复制附件名
                  </Button>
                </Space>
              </Col>
            </Row>
          }
        />
      )}

      <Card title={<Space><FileTextOutlined /> 发票台账</Space>}>
        <Spin spinning={loading}>
          <Table
            dataSource={data}
            columns={columns}
            rowKey="id"
            size="middle"
            pagination={{ current: page, pageSize: 20, total, showTotal: (t) => `共 ${t} 张`, onChange: (p) => setPage(p) }}
            onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
          />
        </Spin>
      </Card>

      <Drawer
        title="发票详情"
        open={!!detail}
        onClose={() => setDetail(null)}
        width={480}
      >
        {detail && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="发票代码">{detail.invoice_code || '-'}</Descriptions.Item>
            <Descriptions.Item label="发票号码">{detail.invoice_number || '-'}</Descriptions.Item>
            <Descriptions.Item label="金额">
              <span style={{ fontWeight: 600, color: '#1677ff' }}>¥{detail.amount?.toLocaleString()}</span>
            </Descriptions.Item>
            <Descriptions.Item label="开票日期">{detail.invoice_date || '-'}</Descriptions.Item>
            <Descriptions.Item label="费用类型"><Tag>{EXPENSE_TYPE[detail.expense_type] || detail.expense_type}</Tag></Descriptions.Item>
            <Descriptions.Item label="销售方">{detail.seller_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="购买方">{detail.buyer_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="关联报销单">
              {detail.reimbursement_id ? <Tag color="blue">{detail.reimbursement_id}</Tag> : '未关联'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>

      <Modal
        title="生成模拟发票"
        open={genOpen}
        onCancel={() => { setGenOpen(false); }}
        confirmLoading={generating}
        onOk={async () => {
          if (!genForm.seller_name.trim()) { message.warning('请输入销售方名称'); return; }
          setGenerating(true);
          try {
            const res = await generateInvoice({
              ...genForm,
              invoice_date: genForm.invoice_date || dayjs().format('YYYY-MM-DD'),
            });
            setGenResult(res);
            setGenOpen(false);
            setGenForm({ invoice_type: '增值税普通发票', seller_name: '', amount: undefined, tax_amount: 0, total_with_tax: undefined, remarks: '' });
            message.success('发票生成成功');
          } catch (e) {
            message.error(e instanceof Error ? e.message : '发票生成失败');
          }
          setGenerating(false);
        }}
        okText="生成"
        cancelText="取消"
        width={480}
      >
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>发票类型</div>
            <Select
              value={genForm.invoice_type}
              onChange={(v) => setGenForm((f) => ({ ...f, invoice_type: v }))}
              style={{ width: '100%' }}
              options={['增值税普通发票', '增值税专用发票'].map((t) => ({ value: t, label: t }))}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>开票日期</div>
            <DatePicker
              style={{ width: '100%' }}
              onChange={(d) => setGenForm((f) => ({ ...f, invoice_date: d?.format('YYYY-MM-DD') || '' }))}
            />
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>销售方名称 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Input
              placeholder="例如：上海华住酒店管理有限公司"
              value={genForm.seller_name}
              onChange={(e) => setGenForm((f) => ({ ...f, seller_name: e.target.value }))}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>不含税金额</div>
            <InputNumber
              style={{ width: '100%' }}
              min={0} precision={2} placeholder="0.00"
              value={genForm.amount}
              onChange={(v) => setGenForm((f) => ({ ...f, amount: v ?? undefined }))}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>税额</div>
            <InputNumber
              style={{ width: '100%' }}
              min={0} precision={2} placeholder="0.00"
              value={genForm.tax_amount}
              onChange={(v) => setGenForm((f) => ({ ...f, tax_amount: v ?? 0 }))}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>价税合计</div>
            <InputNumber
              style={{ width: '100%' }}
              min={0} precision={2} placeholder="自动计算"
              value={genForm.total_with_tax}
              onChange={(v) => setGenForm((f) => ({ ...f, total_with_tax: v ?? undefined }))}
            />
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13, color: '#666' }}>备注</div>
            <Input
              placeholder="备注信息（可选）"
              value={genForm.remarks}
              onChange={(e) => setGenForm((f) => ({ ...f, remarks: e.target.value }))}
            />
          </Col>
        </Row>
      </Modal>
    </div>
  );
}
