// =============================================================================
// 后端英文字段 → 前端中文展示 统一映射
// =============================================================================

/** 费用类型 */
export const EXPENSE_TYPE: Record<string, string> = {
  travel: '差旅费',
  entertainment: '招待费',
  office: '办公用品',
  communication: '通信费',
  transport: '市内交通费',
  meeting: '会议费',
  training: '培训费',
  other: '其他费用',
  rd_materials: '研发材料费',
  rd_equipment: '研发设备费',
  tech_acquisition: '技术引进费',
  software_license: '软件许可费',
  advertisement: '广告推广费',
  exhibition: '展会费',
  client_maintenance: '客户维护费',
  audit: '审计服务费',
  recruitment: '招聘费',
  renovation: '装修费',
  cloud_service: '云服务费',
};

/** 费用类型颜色 */
export const EXPENSE_TYPE_COLOR: Record<string, string> = {
  travel: 'blue',
  entertainment: 'orange',
  office: 'green',
  communication: 'purple',
  transport: 'cyan',
  meeting: 'geekblue',
  training: 'lime',
  other: 'default',
  rd_materials: 'magenta',
  rd_equipment: 'red',
  tech_acquisition: 'volcano',
  software_license: 'gold',
  advertisement: 'orange',
  exhibition: 'purple',
  client_maintenance: 'cyan',
  audit: 'blue',
  recruitment: 'green',
  renovation: 'geekblue',
  cloud_service: 'lime',
};

/** 报销单状态 */
export const STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  pending: { label: '待审批', color: 'processing' },
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
  returned: { label: '已退回', color: 'warning' },
  paid: { label: '已付款', color: 'success' },
  cancelled: { label: '已撤销', color: 'default' },
};

/** 审批操作 */
export const ACTION: Record<string, { label: string; color: string }> = {
  pending: { label: '待审批', color: 'processing' },
  approve: { label: '通过', color: 'success' },
  reject: { label: '驳回', color: 'error' },
  return: { label: '退回', color: 'warning' },
  pay: { label: '付款', color: 'blue' },
  cancelled: { label: '已取消', color: 'default' },
};

/** 用户角色 */
export const ROLE: Record<string, string> = {
  employee: '员工',
  manager: '部门经理',
  finance: '财务',
  admin: '超级管理员',
};
