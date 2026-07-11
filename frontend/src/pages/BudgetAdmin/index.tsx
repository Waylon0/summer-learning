import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Modal, Input, InputNumber, Select, message, Space, Tag,
  Drawer, Tooltip, Popconfirm, Row, Col, Spin, Empty,
} from 'antd';
import {
  PlusOutlined, EditOutlined, SwapOutlined, ToolOutlined,
  ReloadOutlined, HistoryOutlined, FundOutlined, InfoCircleOutlined,
} from '@ant-design/icons';
import {
  getAllBudgets, createBudget, adjustBudget, correctBudget,
  transferBudget, getBudgetAdjustments, getBudgetConsumption,
} from '@/services/api';
import { useAuthStore } from '@/stores';
import type {
  BudgetInfo, BudgetAdjustmentRecord, BudgetConsumptionItem,
  BudgetConsumptionResponse,
} from '@/types';

const changeTypeLabels: Record<string, { label: string; color: string }> = {
  create: { label: '新建', color: 'green' },
  increase: { label: '追加', color: 'blue' },
  decrease: { label: '调减', color: 'orange' },
  transfer_in: { label: '调入', color: 'cyan' },
  transfer_out: { label: '调出', color: 'purple' },
  correction: { label: '冲正', color: 'red' },
};

export default function BudgetAdmin() {
  const { user } = useAuthStore();
  const canWrite = user?.role === 'admin' || user?.role === 'finance';

  const [budgets, setBudgets] = useState<BudgetInfo[]>([]);
  const [loading, setLoading] = useState(false);

  // 新建
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ department: '', annual_budget: 0, fiscal_year: 2026, note: '' });
  const [createLoading, setCreateLoading] = useState(false);

  // 调额
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustDept, setAdjustDept] = useState('');
  const [adjustType, setAdjustType] = useState<'delta' | 'absolute'>('delta');
  const [adjustValue, setAdjustValue] = useState(0);
  const [adjustReason, setAdjustReason] = useState('');
  const [adjustLoading, setAdjustLoading] = useState(false);

  // 冲正
  const [correctOpen, setCorrectOpen] = useState(false);
  const [correctDept, setCorrectDept] = useState('');
  const [correctDelta, setCorrectDelta] = useState(0);
  const [correctReason, setCorrectReason] = useState('');
  const [correctLoading, setCorrectLoading] = useState(false);

  // 调拨
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferForm, setTransferForm] = useState({ from_dept: '', to_dept: '', amount: 0, reason: '' });
  const [transferLoading, setTransferLoading] = useState(false);

  // 变更流水
  const [adjDrawerOpen, setAdjDrawerOpen] = useState(false);
  const [adjDept, setAdjDept] = useState('');
  const [adjustments, setAdjustments] = useState<BudgetAdjustmentRecord[]>([]);
  const [adjLoading, setAdjLoading] = useState(false);

  // 消耗明细
  const [consDrawerOpen, setConsDrawerOpen] = useState(false);
  const [consDept, setConsDept] = useState('');
  const [consumptions, setConsumptions] = useState<BudgetConsumptionItem[]>([]);
  const [consTotal, setConsTotal] = useState(0);
  const [consLoading, setConsLoading] = useState(false);

  const fetch = useCallback(async () => {
    setLoading(true);
    try { setBudgets(await getAllBudgets()); } catch { message.error('获取预算列表失败'); }
    setLoading(false);
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const showAdjustments = async (dept: string) => {
    setAdjDept(dept);
    setAdjDrawerOpen(true);
    setAdjLoading(true);
    try { setAdjustments(await getBudgetAdjustments(dept)); } catch { message.error('获取变更流水失败'); }
    setAdjLoading(false);
  };

  const showConsumption = async (dept: string) => {
    setConsDept(dept);
    setConsDrawerOpen(true);
    setConsLoading(true);
    try {
      const res = await getBudgetConsumption(dept);
      setConsumptions(res.reimbursements);
      setConsTotal(res.committed_total);
    } catch { message.error('获取消耗明细失败'); }
    setConsLoading(false);
  };

  const columns = [
    { title: '部门', dataIndex: 'department', key: 'department', width: 120 },
    {
      title: '年度预算', dataIndex: 'annual_budget', key: 'annual_budget', width: 140,
      render: (v: number) => <span style={{ fontWeight: 600 }}>¥{v.toLocaleString()}</span>,
    },
    {
      title: '已使用', dataIndex: 'used_amount', key: 'used_amount', width: 140,
      render: (v: number) => <span style={{ color: '#cf1322', fontWeight: 600 }}>¥{v.toLocaleString()}</span>,
    },
    {
      title: '剩余', dataIndex: 'remaining', key: 'remaining', width: 140,
      render: (v: number) => (
        <span style={{ color: v < 0 ? '#ff4d4f' : '#3f8600', fontWeight: 600 }}>
          {v < 0 && '⚠ '}¥{v.toLocaleString()}
        </span>
      ),
    },
    {
      title: '使用率', dataIndex: 'usage_rate', key: 'usage_rate', width: 160,
      render: (v: number) => {
        const pct = Math.round(v);
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ flex: 1, height: 6, background: '#f0f0f0', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(pct, 100)}%`, height: '100%', borderRadius: 3, background: pct > 90 ? '#ff4d4f' : pct > 70 ? '#faad14' : '#52c41a' }} />
            </div>
            <span style={{ fontSize: 12, color: '#999', minWidth: 40 }}>{pct}%</span>
          </div>
        );
      },
    },
    { title: '财年', dataIndex: 'fiscal_year', key: 'fiscal_year', width: 70 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => v === 'frozen' ? <Tag color="warning">冻结</Tag> : <Tag color="success">正常</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: unknown, r: BudgetInfo) => (
        <Space>
          <Tooltip title="变更流水">
            <Button type="link" size="small" icon={<HistoryOutlined />} onClick={() => showAdjustments(r.department)} />
          </Tooltip>
          <Tooltip title="消耗明细">
            <Button type="link" size="small" icon={<InfoCircleOutlined />} onClick={() => showConsumption(r.department)} />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title={<Space><FundOutlined />预算管理</Space>}
        extra={<Button icon={<ReloadOutlined />} onClick={fetch} loading={loading}>刷新</Button>}
        style={{ marginBottom: 16 }}
      >
        {canWrite && (
          <Space style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateForm({ department: '', annual_budget: 0, fiscal_year: 2026, note: '' }); setCreateOpen(true); }}>新建预算</Button>
            <Button icon={<EditOutlined />} onClick={() => { const d = budgets[0]?.department || ''; setAdjustDept(d); setAdjustType('delta'); setAdjustValue(0); setAdjustReason(''); setAdjustOpen(true); }}>调整额度</Button>
            <Button icon={<ToolOutlined />} onClick={() => { const d = budgets[0]?.department || ''; setCorrectDept(d); setCorrectDelta(0); setCorrectReason(''); setCorrectOpen(true); }}>人工冲正</Button>
            <Button icon={<SwapOutlined />} onClick={() => { setTransferForm({ from_dept: '', to_dept: '', amount: 0, reason: '' }); setTransferOpen(true); }}>跨部门调拨</Button>
          </Space>
        )}
        <Spin spinning={loading}>
          {budgets.length === 0 ? (
            <Empty description="暂无预算数据" style={{ padding: 40 }} />
          ) : (
            <Table
              dataSource={budgets}
              columns={columns}
              rowKey="id"
              size="middle"
              pagination={false}
            />
          )}
        </Spin>
      </Card>

      {/* ===== 新建预算 ===== */}
      <Modal
        title="新建部门预算"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createLoading}
        onOk={async () => {
          if (!createForm.department.trim()) { message.warning('请输入部门名称'); return; }
          if (createForm.annual_budget <= 0) { message.warning('年度预算必须大于 0'); return; }
          setCreateLoading(true);
          try { await createBudget(createForm); message.success('预算创建成功'); setCreateOpen(false); fetch(); } catch (e) { message.error(e instanceof Error ? e.message : '创建失败'); }
          setCreateLoading(false);
        }}
      >
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          <Col span={24}><div style={{ marginBottom: 4, fontSize: 13 }}>部门名称 <span style={{ color: '#ff4d4f' }}>*</span></div><Input placeholder="如：技术部" value={createForm.department} onChange={(e) => setCreateForm((f) => ({ ...f, department: e.target.value }))} /></Col>
          <Col span={12}><div style={{ marginBottom: 4, fontSize: 13 }}>年度预算 <span style={{ color: '#ff4d4f' }}>*</span></div><InputNumber style={{ width: '100%' }} min={1} precision={2} value={createForm.annual_budget} onChange={(v) => setCreateForm((f) => ({ ...f, annual_budget: v ?? 0 }))} /></Col>
          <Col span={12}><div style={{ marginBottom: 4, fontSize: 13 }}>财年</div><InputNumber style={{ width: '100%' }} min={2020} max={2099} value={createForm.fiscal_year} onChange={(v) => setCreateForm((f) => ({ ...f, fiscal_year: v ?? 2026 }))} /></Col>
          <Col span={24}><div style={{ marginBottom: 4, fontSize: 13 }}>备注</div><Input placeholder="可选" value={createForm.note} onChange={(e) => setCreateForm((f) => ({ ...f, note: e.target.value }))} /></Col>
        </Row>
      </Modal>

      {/* ===== 调整额度 ===== */}
      <Modal
        title="调整部门额度"
        open={adjustOpen}
        onCancel={() => setAdjustOpen(false)}
        confirmLoading={adjustLoading}
        onOk={async () => {
          if (!adjustDept) { message.warning('请选择部门'); return; }
          if (!adjustReason.trim()) { message.warning('请填写调整原因'); return; }
          setAdjustLoading(true);
          try {
            const data = adjustType === 'delta' ? { delta: adjustValue, reason: adjustReason } : { new_annual_budget: adjustValue, reason: adjustReason };
            await adjustBudget(adjustDept, data);
            message.success('额度调整成功'); setAdjustOpen(false); fetch();
          } catch (e) { message.error(e instanceof Error ? e.message : '调整失败'); }
          setAdjustLoading(false);
        }}
      >
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>部门 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Select style={{ width: '100%' }} value={adjustDept || undefined} onChange={(v) => setAdjustDept(v)} options={budgets.map((b) => ({ value: b.department, label: `${b.department}（余额 ¥${b.remaining.toLocaleString()}）` }))} />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>调整方式</div>
            <Select style={{ width: '100%' }} value={adjustType} onChange={(v) => { setAdjustType(v); setAdjustValue(0); }} options={[{ value: 'delta', label: '增减量' }, { value: 'absolute', label: '调整到' }]} />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>{adjustType === 'delta' ? '增减额（+追加 / -调减）' : '目标年度预算'} <span style={{ color: '#ff4d4f' }}>*</span></div>
            <InputNumber style={{ width: '100%' }} precision={2} value={adjustValue} onChange={(v) => setAdjustValue(v ?? 0)} />
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>调整原因 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Input.TextArea rows={2} placeholder="必填，审计留痕" value={adjustReason} onChange={(e) => setAdjustReason(e.target.value)} />
          </Col>
        </Row>
      </Modal>

      {/* ===== 人工冲正 ===== */}
      <Modal
        title="人工冲正 used_amount"
        open={correctOpen}
        onCancel={() => setCorrectOpen(false)}
        confirmLoading={correctLoading}
        onOk={async () => {
          if (!correctDept) { message.warning('请选择部门'); return; }
          if (!correctReason.trim()) { message.warning('请填写冲正原因'); return; }
          setCorrectLoading(true);
          try {
            await correctBudget(correctDept, { delta_used: correctDelta, reason: correctReason });
            message.success('冲正成功'); setCorrectOpen(false); fetch();
          } catch (e) { message.error(e instanceof Error ? e.message : '冲正失败'); }
          setCorrectLoading(false);
        }}
      >
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>部门 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Select style={{ width: '100%' }} value={correctDept || undefined} onChange={(v) => setCorrectDept(v)} options={budgets.map((b) => ({ value: b.department, label: `${b.department}（已使用 ¥${b.used_amount.toLocaleString()}）` }))} />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>已使用修正值（+/-） <span style={{ color: '#ff4d4f' }}>*</span></div>
            <InputNumber style={{ width: '100%' }} precision={2} value={correctDelta} onChange={(v) => setCorrectDelta(v ?? 0)} />
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>冲正原因 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Input.TextArea rows={2} placeholder="必填，审计留痕" value={correctReason} onChange={(e) => setCorrectReason(e.target.value)} />
          </Col>
        </Row>
      </Modal>

      {/* ===== 跨部门调拨 ===== */}
      <Modal
        title="跨部门额度调拨"
        open={transferOpen}
        onCancel={() => setTransferOpen(false)}
        confirmLoading={transferLoading}
        onOk={async () => {
          if (!transferForm.from_dept) { message.warning('请选择调出部门'); return; }
          if (!transferForm.to_dept) { message.warning('请选择调入部门'); return; }
          if (transferForm.from_dept === transferForm.to_dept) { message.warning('调出/调入部门不能相同'); return; }
          if (transferForm.amount <= 0) { message.warning('调拨金额必须大于 0'); return; }
          if (!transferForm.reason.trim()) { message.warning('请填写调拨原因'); return; }
          setTransferLoading(true);
          try {
            await transferBudget(transferForm);
            message.success('调拨完成'); setTransferOpen(false); fetch();
          } catch (e) { message.error(e instanceof Error ? e.message : '调拨失败'); }
          setTransferLoading(false);
        }}
      >
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>调出部门 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Select style={{ width: '100%' }} value={transferForm.from_dept || undefined} onChange={(v) => setTransferForm((f) => ({ ...f, from_dept: v }))} options={budgets.map((b) => ({ value: b.department, label: `${b.department}（剩余 ¥${b.remaining.toLocaleString()}）` }))} />
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>调入部门 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Select style={{ width: '100%' }} value={transferForm.to_dept || undefined} onChange={(v) => setTransferForm((f) => ({ ...f, to_dept: v }))} options={budgets.map((b) => ({ value: b.department, label: `${b.department}（剩余 ¥${b.remaining.toLocaleString()}）` }))} />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>调拨金额 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} value={transferForm.amount} onChange={(v) => setTransferForm((f) => ({ ...f, amount: v ?? 0 }))} />
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>调拨原因 <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Input.TextArea rows={2} placeholder="必填，审计留痕" value={transferForm.reason} onChange={(e) => setTransferForm((f) => ({ ...f, reason: e.target.value }))} />
          </Col>
        </Row>
      </Modal>

      {/* ===== 变更流水 ===== */}
      <Drawer
        title={`${adjDept} — 变更流水`}
        open={adjDrawerOpen}
        onClose={() => setAdjDrawerOpen(false)}
        width={640}
      >
        <Spin spinning={adjLoading}>
          {adjustments.length === 0 ? (
            <Empty description="暂无变更记录" />
          ) : (
            adjustments.map((a) => (
              <div key={a.id} style={{ marginBottom: 12, padding: '12px 14px', background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                <Space wrap>
                  <Tag color={changeTypeLabels[a.change_type]?.color}>{changeTypeLabels[a.change_type]?.label || a.change_type}</Tag>
                  <span style={{ fontWeight: 500 }}>{a.operator}</span>
                  <span style={{ color: '#999', fontSize: 12 }}>{a.created_at ? new Date(a.created_at).toLocaleString('zh-CN') : '-'}</span>
                </Space>
                <div style={{ marginTop: 8, fontSize: 13 }}>
                  年度预算：¥{a.before_annual.toLocaleString()} → ¥{a.after_annual.toLocaleString()}
                  {a.delta_annual !== 0 && <span style={{ marginLeft: 8, color: a.delta_annual > 0 ? '#52c41a' : '#ff4d4f' }}>({a.delta_annual > 0 ? '+' : ''}¥{a.delta_annual.toLocaleString()})</span>}
                  {a.delta_used !== 0 && <span style={{ marginLeft: 8 }}> ｜ 已使用修正：{a.delta_used > 0 ? '+' : ''}¥{a.delta_used.toLocaleString()}</span>}
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: '#666' }}>{a.reason}</div>
              </div>
            ))
          )}
        </Spin>
      </Drawer>

      {/* ===== 消耗明细 ===== */}
      <Drawer
        title={`${consDept} — 预算消耗明细（占用总额 ¥${consTotal.toLocaleString()}）`}
        open={consDrawerOpen}
        onClose={() => setConsDrawerOpen(false)}
        width={640}
      >
        <Spin spinning={consLoading}>
          {consumptions.length === 0 ? (
            <Empty description="暂无消耗记录" />
          ) : (
            <Table
              dataSource={consumptions}
              rowKey="id"
              size="small"
              pagination={false}
              columns={[
                { title: '单号', dataIndex: 'id', width: 110, render: (v: string) => v.slice(0, 8) + '...' },
                { title: '申请人', dataIndex: 'user_name', width: 80 },
                { title: '类型', dataIndex: 'expense_type', width: 80 },
                { title: '金额', dataIndex: 'total_amount', width: 110, render: (v: number) => `¥${v.toLocaleString()}` },
                { title: '提交时间', dataIndex: 'created_at', render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
              ]}
            />
          )}
        </Spin>
      </Drawer>
    </div>
  );
}
