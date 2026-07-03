import { useEffect, useState, useRef } from 'react';
import { Card, Row, Col, Statistic, Progress, Table, Spin } from 'antd';
import { WalletOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons';
import { Chart } from '@antv/g2';
import { getAllBudgets } from '@/services/api';
import type { BudgetInfo } from '@/types';

export default function Dashboard() {
  const [budgets, setBudgets] = useState<BudgetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const ringRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const ringChartRef = useRef<Chart | null>(null);
  const barChartRef = useRef<Chart | null>(null);

  useEffect(() => {
    getAllBudgets()
      .then(setBudgets)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (budgets.length === 0) return;

    // 环形图 —— 各部门预算使用率
    if (ringRef.current) {
      if (ringChartRef.current) ringChartRef.current.destroy();
      const chart = new Chart({
        container: ringRef.current,
        autoFit: true,
        height: 360,
      });
      chart.coordinate({ type: 'theta', outerRadius: 0.8, innerRadius: 0.5 });
      chart
        .interval()
        .data(budgets.map((b) => ({ item: b.department, value: b.used_amount })))
        .encode('y', 'value')
        .encode('color', 'item')
        .style({ stroke: '#fff', lineWidth: 2 })
        .label({
          text: (d: { item: string; value: number }) =>
            `${d.item}\n¥${(d.value / 10000).toFixed(1)}万`,
          position: 'outside',
        })
        .tooltip({ title: 'item', items: [{ channel: 'y', valueFormatter: (v: number) => `¥${v.toLocaleString()}` }] })
        .legend(false);
      chart.render();
      ringChartRef.current = chart;
    }

    // 柱状图 —— 各部门预算 vs 已使用 vs 剩余
    if (barRef.current) {
      if (barChartRef.current) barChartRef.current.destroy();
      const chart = new Chart({
        container: barRef.current,
        autoFit: true,
        height: 360,
      });
      const barData = budgets.flatMap((b) => [
        { department: b.department, type: '年度预算', amount: b.annual_budget },
        { department: b.department, type: '已使用', amount: b.used_amount },
        { department: b.department, type: '剩余', amount: b.remaining },
      ]);
      chart
        .interval()
        .data(barData)
        .encode('x', 'department')
        .encode('y', 'amount')
        .encode('color', 'type')
        .transform({ type: 'dodgeX' })
        .style({ radiusTopLeft: 4, radiusTopRight: 4 })
        .tooltip({ title: 'department', items: [{ channel: 'y', valueFormatter: (v: number) => `¥${v.toLocaleString()}` }] });
      chart.render();
      barChartRef.current = chart;
    }

    return () => {
      ringChartRef.current?.destroy();
      barChartRef.current?.destroy();
    };
  }, [budgets]);

  if (loading) return <Spin style={{ display: 'block', margin: '100px auto' }} />;

  const totalBudget = budgets.reduce((s, b) => s + b.annual_budget, 0);
  const totalUsed = budgets.reduce((s, b) => s + b.used_amount, 0);
  const totalRemaining = totalBudget - totalUsed;

  const columns = [
    { title: '部门', dataIndex: 'department', key: 'department' },
    {
      title: '年度预算',
      dataIndex: 'annual_budget',
      key: 'annual_budget',
      render: (v: number) => `¥${v.toLocaleString()}`,
    },
    {
      title: '已使用',
      dataIndex: 'used_amount',
      key: 'used_amount',
      render: (v: number) => `¥${v.toLocaleString()}`,
    },
    {
      title: '剩余',
      dataIndex: 'remaining',
      key: 'remaining',
      render: (v: number, r: BudgetInfo) => (
        <span style={{ color: v < 0 ? '#ff4d4f' : '#52c41a' }}>¥{v.toLocaleString()}</span>
      ),
    },
    {
      title: '使用率',
      dataIndex: 'usage_rate',
      key: 'usage_rate',
      render: (v: number) => (
        <Progress
          percent={Math.round(v)}
          size="small"
          status={v > 90 ? 'exception' : v > 70 ? 'active' : 'normal'}
        />
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="年度总预算"
              value={totalBudget}
              precision={0}
              prefix={<WalletOutlined />}
              suffix="元"
              formatter={(v) => `¥${Number(v).toLocaleString()}`}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="已使用"
              value={totalUsed}
              precision={0}
              prefix={<RiseOutlined />}
              suffix="元"
              valueStyle={{ color: '#cf1322' }}
              formatter={(v) => `¥${Number(v).toLocaleString()}`}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="剩余可用"
              value={totalRemaining}
              precision={0}
              prefix={<FallOutlined />}
              suffix="元"
              valueStyle={{ color: totalRemaining < 0 ? '#cf1322' : '#3f8600' }}
              formatter={(v) => `¥${Number(v).toLocaleString()}`}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={12}>
          <Card title="各部门预算使用占比">
            <div ref={ringRef} style={{ minHeight: 360 }} />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="各部门预算对比">
            <div ref={barRef} style={{ minHeight: 360 }} />
          </Card>
        </Col>
      </Row>

      <Card title="部门预算详情">
        <Table
          dataSource={budgets}
          columns={columns}
          rowKey="id"
          pagination={false}
          size="middle"
        />
      </Card>
    </div>
  );
}
