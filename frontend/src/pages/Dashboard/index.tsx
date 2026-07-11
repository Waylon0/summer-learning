import { useEffect, useState, useRef } from 'react';
import { Card, Row, Col, Statistic, Progress, Table, Skeleton, Space } from 'antd';
import { WalletOutlined, RiseOutlined, FallOutlined, TrophyOutlined, FileTextOutlined } from '@ant-design/icons';
import { Chart } from '@antv/g2';
import { getAllBudgets, getTrend, getPersonalStats } from '@/services/api';
import type { BudgetInfo, TrendResponse, PersonalStatsResponse } from '@/types';

export default function Dashboard() {
  const [budgets, setBudgets] = useState<BudgetInfo[]>([]);
  const [trend, setTrend] = useState<TrendResponse | null>(null);
  const [personal, setPersonal] = useState<PersonalStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortAsc, setSortAsc] = useState(false);
  const [tableSortMode, setTableSortMode] = useState<'amount' | 'rate'>('amount');
  const ringRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const trendRef = useRef<HTMLDivElement>(null);
  const ringChartRef = useRef<Chart | null>(null);
  const barChartRef = useRef<Chart | null>(null);
  const trendChartRef = useRef<Chart | null>(null);

  useEffect(() => {
    Promise.all([
      getAllBudgets(),
      getTrend({ months: 6 }),
      getPersonalStats(),
    ])
      .then(([b, t, p]) => { setBudgets(b); setTrend(t); setPersonal(p); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (budgets.length === 0) return;

      if (ringRef.current) {
        if (ringChartRef.current) {
          ringChartRef.current.destroy();
          ringChartRef.current = null;
        }
        ringRef.current.innerHTML = '';

        const chart = new Chart({ container: ringRef.current, autoFit: true, height: 380 });

        const chartData = budgets
          .filter((b) => b.used_amount > 0)
          .sort((a, b) => b.used_amount - a.used_amount)
          .map((b) => ({ item: b.department, value: b.used_amount }));

        const total = chartData.length > 0 ? chartData.reduce((s, d) => s + d.value, 0) : 0;
        const colors = ['#5B8FF9', '#F46649', '#30BF78', '#FAAD14', '#5AD8A6', '#FF99C3', '#B681F0', '#FF9845'];

        chart.coordinate({ type: 'theta', outerRadius: 0.85, innerRadius: 0.45 });

        chart
          .interval()
          .data(chartData)
          .encode('y', 'value')
          .encode('color', 'item')
          .scale('color', { range: colors })
          .style({ stroke: '#fff', lineWidth: 2 })
          .tooltip({
            title: 'item',
            items: [
              { channel: 'y', name: '已使用', valueFormatter: (v: number) => `¥${v.toLocaleString()}` },
              (d: { item: string; value: number }) => ({
                name: '占比',
                value: `${((d.value / total) * 100).toFixed(1)}%`,
              }),
            ],
          })
          .legend({ color: { title: '部门', layout: { justifyContent: 'center' } } });

        chart.render();

        ringChartRef.current = chart;

        // 更新外层容器中的中间文字（位于 chart 容器外部，互不干扰）
        const centerEl = document.getElementById('ring-center-text');
        if (centerEl) {
          centerEl.innerHTML = `
            <div style="font-size:13px;color:#999;margin-bottom:4px;">已使用总计</div>
            <div style="font-size:18px;font-weight:700;color:#333;">¥${total.toLocaleString()}</div>
          `;
        }
      }

    if (barRef.current) {
      if (barChartRef.current) barChartRef.current.destroy();
      const chart = new Chart({ container: barRef.current, autoFit: true, height: 360 });
      const barData = budgets.flatMap((b) => [
        { department: b.department, type: '年度预算', amount: b.annual_budget },
        { department: b.department, type: '已使用', amount: b.used_amount },
        { department: b.department, type: '剩余', amount: b.remaining },
      ]);
      chart.interval().data(barData).encode('x', 'department').encode('y', 'amount').encode('color', 'type')
        .scale('color', { range: ['#1677ff', '#ff4d4f', '#52c41a'] })
        .transform({ type: 'dodgeX' }).style({ radiusTopLeft: 4, radiusTopRight: 4 })
        .tooltip({ title: 'department', items: [{ channel: 'y', valueFormatter: (v: number) => `¥${v.toLocaleString()}` }] });
      chart.render();
      barChartRef.current = chart;
    }

    return () => {
      ringChartRef.current?.destroy();
      ringChartRef.current = null;
      barChartRef.current?.destroy();
      barChartRef.current = null;
    };
  }, [budgets]);

  useEffect(() => {
    if (!trend || !trendRef.current) return;
    if (trendChartRef.current) trendChartRef.current.destroy();

    const chart = new Chart({ container: trendRef.current, autoFit: true, height: 360 });
    const lineData: { month: string; type: string; amount: number }[] = [];
    trend.series.forEach((s) => {
      trend.months.forEach((m, i) => { lineData.push({ month: m, type: s.label, amount: s.data[i] || 0 }); });
    });

    chart.data(lineData)
      .encode('x', 'month')
      .encode('y', 'amount')
      .encode('color', 'type')
      .scale('y', { nice: true })
      .axis('y', { labelFormatter: (v: number) => `¥${(v / 10000).toFixed(0)}万` });

    chart.line().encode('shape', 'smooth');
    chart.point().encode('shape', 'point').tooltip(false);
    chart.interaction('tooltip', { shared: true });
    chart.render();
    trendChartRef.current = chart;

    return () => { trendChartRef.current?.destroy(); };
  }, [trend]);

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <Row gutter={16} style={{ marginBottom: 24 }}>
          {[1, 2, 3, 4, 5].map((i) => (
            <Col span={i <= 3 ? 8 : 12} key={i}>
              <Card><Skeleton active paragraph={{ rows: 1 }} /></Card>
            </Col>
          ))}
        </Row>
        <Card style={{ marginBottom: 24 }}><Skeleton active paragraph={{ rows: 3 }} /></Card>
        <Row gutter={16}>
          {[1, 2].map((i) => (
            <Col span={12} key={i}>
              <Card><Skeleton active paragraph={{ rows: 4 }} /></Card>
            </Col>
          ))}
        </Row>
      </div>
    );
  }

  const totalBudget = budgets.reduce((s, b) => s + b.annual_budget, 0);
  const totalUsed = budgets.reduce((s, b) => s + b.used_amount, 0);
  const totalRemaining = totalBudget - totalUsed;

  const columns = [
    { title: '部门', dataIndex: 'department', key: 'department' },
    { title: '年度预算', dataIndex: 'annual_budget', key: 'annual_budget', render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '已使用', dataIndex: 'used_amount', key: 'used_amount', render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '剩余', dataIndex: 'remaining', key: 'remaining', render: (v: number) => (<span style={{ color: v < 0 ? '#ff4d4f' : '#52c41a' }}>¥{v.toLocaleString()}</span>) },
    { title: '使用率', dataIndex: 'usage_rate', key: 'usage_rate', render: (v: number) => (<Progress percent={Math.round(v)} size="small" status={v > 90 ? 'exception' : v > 70 ? 'active' : 'normal'} />) },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }} align="stretch">
        <Col span={6}>
          <Card style={{ height: '100%' }}>
            <Statistic title="年度总预算" value={totalBudget} precision={0} prefix={<WalletOutlined />} suffix="元"
              formatter={(v) => `¥${Number(v).toLocaleString()}`} />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ height: '100%' }}>
            <Statistic title="已使用" value={totalUsed} precision={0} prefix={<RiseOutlined />} suffix="元"
              valueStyle={{ color: '#cf1322' }} formatter={(v) => `¥${Number(v).toLocaleString()}`} />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ height: '100%' }}>
            <Statistic title="剩余可用" value={totalRemaining} precision={0} prefix={<FallOutlined />} suffix="元"
              valueStyle={{ color: totalRemaining < 0 ? '#cf1322' : '#3f8600' }} formatter={(v) => `¥${Number(v).toLocaleString()}`} />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ height: '100%' }}>
            <Statistic title="本月报销" value={personal?.current_month?.count || 0} precision={0} prefix={<FileTextOutlined />} suffix={`笔 / ¥${(personal?.current_month?.total || 0).toLocaleString()}`}
              valueStyle={{ color: '#1677ff' }} formatter={(v) => `${v}`} />
          </Card>
        </Col>
      </Row>

      {personal && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={24}>
            <Card size="small">
              <div style={{ display: 'flex', width: '100%' }}>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <span style={{ color: '#999', fontSize: 13 }}>本月：</span>
                  <span style={{ fontWeight: 600 }}>{personal.current_month.count} 笔</span>
                  <span style={{ marginLeft: 8, fontWeight: 600, color: '#1677ff' }}>¥{personal.current_month.total.toLocaleString()}</span>
                </div>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <span style={{ color: '#999', fontSize: 13 }}>上月：</span>
                  <span style={{ fontWeight: 600 }}>{personal.last_month.count} 笔</span>
                  <span style={{ marginLeft: 8, fontWeight: 600, color: '#1677ff' }}>¥{personal.last_month.total.toLocaleString()}</span>
                </div>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <span style={{ color: '#999', fontSize: 13 }}>待审批：</span>
                  <span style={{ fontWeight: 600, color: '#faad14' }}>{personal.status_breakdown?.pending || 0} 笔</span>
                </div>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <span style={{ color: '#999', fontSize: 13 }}>已通过：</span>
                  <span style={{ fontWeight: 600, color: '#52c41a' }}>{personal.status_breakdown?.approved || 0} 笔</span>
                </div>
              </div>
            </Card>
          </Col>
        </Row>
      )}

      <Card
        title={<Space><TrophyOutlined /> 部门费用排行</Space>}
        style={{ marginBottom: 24 }}
        extra={<span style={{ fontSize: 12, color: '#999', cursor: 'pointer' }} onClick={() => setSortAsc(!sortAsc)}>{sortAsc ? '按已使用金额升序' : '按已使用金额降序'}</span>}
      >
        <Row gutter={[16, 12]}>
          {[...budgets].sort((a, b) => sortAsc ? a.used_amount - b.used_amount : b.used_amount - a.used_amount).map((b, i) => (
            <Col span={i === 0 ? 8 : 4} key={b.id}>
              <Card size="small" style={{ textAlign: 'center', background: b.usage_rate > 90 ? '#fff2f0' : i === 0 ? '#f6ffed' : '#fafafa', border: b.usage_rate > 90 ? '1px solid #ffccc7' : undefined }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
                  {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i + 1}`} {b.department}
                </div>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#1677ff' }}>
                  ¥{(b.used_amount / 10000).toFixed(1)}<span style={{ fontSize: 12 }}>万</span>
                </div>
                <Progress percent={Math.round(b.usage_rate)} size="small" status={b.usage_rate > 90 ? 'exception' : 'normal'} style={{ marginTop: 4 }} />
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {trend && (
        <Card title="费用趋势（近6个月）" style={{ marginBottom: 24 }}>
          <div ref={trendRef} style={{ minHeight: 360 }} />
        </Card>
      )}

      <Row gutter={16} style={{ marginBottom: 24 }} align="stretch">
        <Col span={12}>
          <Card title="各部门预算使用占比" style={{ height: '100%' }}>
            <div style={{ position: 'relative' }}>
              <div ref={ringRef} style={{ minHeight: 360 }} />
              <div id="ring-center-text" style={{
                position: 'absolute',
                top: '55%',
                left: '50%',
                transform: 'translate(-50%,-50%)',
                textAlign: 'center',
                pointerEvents: 'none',
                lineHeight: 1.6,
              }} />
            </div>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="各部门预算对比" style={{ height: '100%' }}><div ref={barRef} style={{ minHeight: 360 }} /></Card>
        </Col>
      </Row>

      <Card
        title="部门预算详情"
        extra={<span style={{ fontSize: 12, color: '#999', cursor: 'pointer' }} onClick={() => setTableSortMode(m => m === 'amount' ? 'rate' : 'amount')}>{tableSortMode === 'amount' ? '按已使用金额降序' : '按使用率降序'}</span>}
      >
        <Table dataSource={[...budgets].sort((a, b) => tableSortMode === 'amount' ? b.used_amount - a.used_amount : b.usage_rate - a.usage_rate)} columns={columns} rowKey="id" pagination={false} size="middle" />
      </Card>
    </div>
  );
}
