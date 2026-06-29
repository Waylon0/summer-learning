import { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Progress, Table, Spin } from 'antd';
import { WalletOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons';
import { getAllBudgets } from '@/services/api';
import type { BudgetInfo } from '@/types';

export default function Dashboard() {
  const [budgets, setBudgets] = useState<BudgetInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAllBudgets()
      .then(setBudgets)
      .finally(() => setLoading(false));
  }, []);

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
        <span style={{ color: v < 0 ? 'red' : 'green' }}>¥{v.toLocaleString()}</span>
      ),
    },
    {
      title: '使用率',
      dataIndex: 'usage_rate',
      key: 'usage_rate',
      render: (v: number) => (
        <Progress percent={Math.round(v)} size="small" status={v > 90 ? 'exception' : v > 70 ? 'active' : 'normal'} />
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
