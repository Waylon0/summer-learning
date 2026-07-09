import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Card, Input, Button, Space, Upload, Tag, message, Switch, Descriptions, Steps,
} from 'antd';
import {
  SendOutlined, UploadOutlined, FileTextOutlined, FilePdfOutlined,
  FileJpgOutlined, LoadingOutlined, DeleteOutlined, NodeIndexOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { useAppStore } from '@/stores';
import { sendChatMessage, sendChatMessageStream, uploadInvoice } from '@/services/api';
import type { ChatMessage, FlowStep } from '@/types';

// =============================================================================
// 步骤定义 — 按意图分流，每组步骤有独立的触发正则
// =============================================================================

interface StepDef { key: string; title: string; trigger: RegExp; doneDesc: string }

// 新建报销 / 上传票据 → 走完整链路
const STEPS_REIMBURSEMENT: StepDef[] = [
  { key: 'intent', title: '意图识别', trigger: /.*/, doneDesc: '意图已识别' },
  { key: 'ocr', title: 'OCR票据识别', trigger: /OCR|识别完成|票据信息|发票代码|发票号码|金额合计|未检测到上传票据|按您提供的金额/, doneDesc: '已识别票据信息' },
  { key: 'compliance', title: '合规检查', trigger: /合规检查|符合.*标准|合规.*通过|超标|人均|政策要求|不符合/, doneDesc: '合规检查完成' },
  { key: 'budget', title: '预算检查', trigger: /预算检查|部门.*预算|预算余额|剩余.*预算|可用|预算充足|预算不足|已使用/, doneDesc: '预算检查完成' },
  { key: 'save', title: '保存报销单', trigger: /保存|已记录|已创建|已写入/, doneDesc: '报销单已保存' },
  { key: 'pdf', title: '生成报销单PDF', trigger: /报销单已生成|PDF.*已生成|📄/, doneDesc: '报销单PDF已生成' },
  { key: 'email', title: '发送审批邮件', trigger: /已提交审批|邮件.*发送|📧|审批流程|出纳付款/, doneDesc: '邮件已发送' },
];

// 查询进度
const STEPS_QUERY: StepDef[] = [
  { key: 'intent', title: '意图识别', trigger: /.*/, doneDesc: '意图已识别' },
  { key: 'query', title: '查询处理', trigger: /📋|找到.*条|未找到|报销单.*状态/, doneDesc: '查询完成' },
];

// 政策咨询 / 一般对话
const STEPS_KNOWLEDGE: StepDef[] = [
  { key: 'intent', title: '意图识别', trigger: /.*/, doneDesc: '意图已识别' },
  { key: 'search', title: '知识检索', trigger: /检索|查找到|根据.*规定|根据.*政策|搜索结果/, doneDesc: '知识检索完成' },
  { key: 'reply', title: '生成回答', trigger: /.*/, doneDesc: '回答已生成' },
];

// 生成发票
const STEPS_INVOICE: StepDef[] = [
  { key: 'intent', title: '意图识别', trigger: /.*/, doneDesc: '意图已识别' },
  { key: 'generate', title: '生成发票PDF', trigger: /发票.*生成|票据.*生成|download_url|object_name/, doneDesc: '发票已生成' },
];

// 审批操作
const STEPS_APPROVAL: StepDef[] = [
  { key: 'intent', title: '意图识别', trigger: /.*/, doneDesc: '意图已识别' },
  { key: 'approval', title: '审批处理', trigger: /审批.*记录|已通过|已驳回|已更新/, doneDesc: '审批已处理' },
];

// 默认（通用对话）
const STEPS_DEFAULT: StepDef[] = [
  { key: 'intent', title: '意图识别', trigger: /.*/, doneDesc: '意图已识别' },
  { key: 'reply', title: '生成回复', trigger: /.*/, doneDesc: '回复已生成' },
];

function pickSteps(intent: string | null): StepDef[] {
  if (!intent) return STEPS_DEFAULT;
  if (intent === 'reimbursement_create' || intent === 'document_parse') return STEPS_REIMBURSEMENT;
  if (intent === 'reimbursement_query') return STEPS_QUERY;
  if (intent === 'policy_inquiry' || intent === 'general_chat') return STEPS_KNOWLEDGE;
  if (intent === 'invoice_generate') return STEPS_INVOICE;
  if (intent === 'approval_action') return STEPS_APPROVAL;
  return STEPS_DEFAULT;
}

function intentLabel(intent: string | null): string {
  const map: Record<string, string> = {
    reimbursement_create: '新建报销', document_parse: '票据解析', reimbursement_query: '进度查询',
    policy_inquiry: '政策咨询', invoice_generate: '生成发票', approval_action: '审批操作',
    general_chat: '通用对话', reimbursement_modify: '修改报销',
  };
  return map[intent || ''] || intent || '未知';
}

// =============================================================================
// 组件
// =============================================================================

const fileIcon = (name: string) => {
  const ext = name.split('.').pop()?.toLowerCase();
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />;
  if (['png', 'jpg', 'jpeg'].includes(ext || '')) return <FileJpgOutlined style={{ color: '#1677ff', fontSize: 20 }} />;
  return <FileTextOutlined style={{ color: '#999', fontSize: 20 }} />;
};

const quickPrompts = [
  '我要报销差旅费 1500 元，部门技术部',
  '查询我的报销进度',
  '上传发票并新建报销',
];

export default function ChatReimbursement() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [streamMode, setStreamMode] = useState(true);
  const [stepsVisible, setStepsVisible] = useState(false);

  // 流程步骤状态机
  const [flowSteps, setFlowSteps] = useState<FlowStep[]>([]);
  const stepDefsRef = useRef<StepDef[]>(STEPS_DEFAULT);
  const stepAccRef = useRef('');
  const intentRef = useRef<string | null>(null);

  // 视觉动画：即使后端事件瞬时到达，前端按 400ms/步节奏依次点亮
  const targetCursorRef = useRef(0);
  const visualCursorRef = useRef(0);
  const tickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, addMessage, appendToLastAssistant, sessionId, setSessionId, clearMessages } = useAppStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 清理定时器
  useEffect(() => () => { if (tickTimerRef.current) clearTimeout(tickTimerRef.current); }, []);

  // ---- 渲染步骤到指定 cursor ----
  const renderSteps = useCallback((cursor: number, defs: StepDef[], intent: string | null) => {
    setFlowSteps(defs.map((d, i) => {
      if (i < cursor) return { key: d.key, title: d.title, description: d.doneDesc, status: 'finish' as const };
      if (i === cursor) return { key: d.key, title: d.title, description: '执行中...', status: 'process' as const };
      return { key: d.key, title: d.title, description: '等待中', status: 'wait' as const };
    }));
  }, []);

  // ---- 视觉动画 tick：每次推进 visualCursor 一步 ----
  const scheduleTick = useCallback(() => {
    if (tickTimerRef.current) return; // 已在动画中
    const tick = () => {
      if (visualCursorRef.current < targetCursorRef.current) {
        visualCursorRef.current++;
        renderSteps(visualCursorRef.current, stepDefsRef.current, intentRef.current);
        tickTimerRef.current = setTimeout(tick, 400);
      } else {
        tickTimerRef.current = null;
        // 如果全部完成，全标 finish
        const defs = stepDefsRef.current;
        if (visualCursorRef.current >= defs.length) {
          setFlowSteps(defs.map((d) => ({ key: d.key, title: d.title, description: d.doneDesc, status: 'finish' as const })));
        }
      }
    };
    tick();
  }, [renderSteps]);

  // ---- 推进 targetCursor（SSE 事件触发） ----
  const bumpTarget = useCallback((newCursor: number) => {
    if (newCursor > targetCursorRef.current) {
      targetCursorRef.current = Math.min(newCursor, stepDefsRef.current.length);
      scheduleTick();
    }
  }, [scheduleTick]);

  // ---- 初始化步骤（意图识别后调用） ----
  const initStepsForIntent = useCallback((intent: string | null) => {
    const defs = pickSteps(intent);
    stepDefsRef.current = defs;
    stepAccRef.current = '';
    intentRef.current = intent;
    // 重置：step 0 完成，target 推进到 1
    targetCursorRef.current = 1;
    visualCursorRef.current = 0;
    if (tickTimerRef.current) { clearTimeout(tickTimerRef.current); tickTimerRef.current = null; }
    renderSteps(0, defs, intent); // 先渲染 step 0 完成
    // 启动动画推进到 step 1
    targetCursorRef.current = 1;
    scheduleTick();
  }, [renderSteps, scheduleTick]);

  const handleSend = async () => {
    if (!input.trim() && fileList.length === 0) return;

    const userContent = input || '请识别上传的票据';
    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: userContent,
      timestamp: new Date().toISOString(),
    };
    addMessage(userMsg);
    setInput('');

    // 重置
    stepDefsRef.current = STEPS_DEFAULT;
    stepAccRef.current = '';
    intentRef.current = null;
    targetCursorRef.current = 0;
    visualCursorRef.current = 0;
    if (tickTimerRef.current) { clearTimeout(tickTimerRef.current); tickTimerRef.current = null; }
    setFlowSteps([{ key: 'intent', title: '意图识别', description: '分析中...', status: 'process' as const }]);

    setLoading(true);

    try {
      const attachments = await Promise.all(
        fileList
          .filter((f) => f.originFileObj)
          .map((f) => uploadInvoice(f.originFileObj!)),
      ).then((results) => results.map((r) => r.object_name));

      if (streamMode) {
        setStreaming(true);
        setStepsVisible(true);
        for await (const event of sendChatMessageStream({
          message: userContent,
          session_id: sessionId || undefined,
          attachments: attachments.length > 0 ? attachments : undefined,
        })) {
          switch (event.type) {
            case 'start':
              if (event.session_id) setSessionId(event.session_id);
              break;

            case 'intent': {
              if (event.session_id) setSessionId(event.session_id);
              const intent = (event as Record<string, unknown>).intent as string || '';
              initStepsForIntent(intent || null);
              break;
            }

            case 'message': {
              const content = (event as Record<string, unknown>).content as string || '';
              appendToLastAssistant(content);

              // 状态机：累积文本，匹配当前步骤触发词 → 推进 targetCursor
              const defs = stepDefsRef.current;
              const cursor = targetCursorRef.current;
              if (cursor < defs.length) {
                stepAccRef.current += content;
                if (defs[cursor].trigger.test(stepAccRef.current)) {
                  stepAccRef.current = '';
                  bumpTarget(cursor + 1);
                }
              }
              break;
            }

            case 'done':
              if (event.session_id) setSessionId(event.session_id);
              // 推进到终点 → 动画逐一点亮剩余步骤
              bumpTarget(stepDefsRef.current.length);
              break;

            case 'error':
              message.error((event as Record<string, unknown>).content as string || '处理异常');
              break;
          }
        }
      } else {
        const data = await sendChatMessage({
          message: userContent,
          session_id: sessionId || undefined,
          attachments: attachments.length > 0 ? attachments : undefined,
        });
        if (data.session_id) setSessionId(data.session_id);
        addMessage({
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.reply,
          timestamp: new Date().toISOString(),
          intent: data.intent,
          entities: data.entities,
        });
      }
      setFileList([]);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '请求失败');
    } finally {
      setLoading(false);
      setStreaming(false);
    }
  };

  const stepsItems = flowSteps.map((s) => ({
    title: s.title,
    description: s.description,
    status: s.status,
    icon: s.status === 'finish' ? <CheckCircleOutlined /> : s.status === 'process' ? <LoadingOutlined /> : undefined,
  }));

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div style={{ flex: stepsVisible ? 3 : 1, minWidth: 0 }}>
        <Card
          title="智能报销对话"
          extra={
            <Space>
              <Button
                size="small"
                icon={<NodeIndexOutlined />}
                type={stepsVisible ? 'primary' : 'default'}
                onClick={() => setStepsVisible((v) => !v)}
              >
                {stepsVisible ? '隐藏流程' : '流程演示'}
              </Button>
              <span style={{ fontSize: 12, color: '#999' }}>SSE</span>
              <Switch size="small" checked={streamMode} onChange={setStreamMode} />
              <Button size="small" onClick={clearMessages}>清空</Button>
            </Space>
          }
        >
          <div
            style={{
              height: 460,
              overflowY: 'auto',
              marginBottom: 16,
              padding: 16,
              background: '#fafbfc',
              borderRadius: 8,
              border: '1px solid #f0f0f0',
            }}
          >
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', color: '#999', marginTop: 90 }}>
                <FileTextOutlined style={{ fontSize: 56, marginBottom: 16, color: '#bfbfbf' }} />
                <p style={{ fontSize: 15, color: '#555', marginBottom: 4 }}>你好，我是企业财务报销助手</p>
                <p style={{ fontSize: 13, color: '#999' }}>
                  可以上传票据图片/PDF，或直接描述报销需求
                </p>
                <Space style={{ marginTop: 16 }} wrap>
                  {quickPrompts.map((p) => (
                    <Tag
                      key={p}
                      style={{ cursor: 'pointer', padding: '4px 12px', fontSize: 13 }}
                      color="blue"
                      onClick={() => { setInput(p); }}
                    >
                      {p}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}
            {messages.map((msg, idx) => (
              <div
                key={msg.id || idx}
                style={{
                  marginBottom: 20,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                }}
              >
                <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>
                  {msg.role === 'user' ? '我' : 'ReimburseAgent'}
                </div>
                <div
                  style={{
                    maxWidth: '82%',
                    padding: '12px 18px',
                    borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                    backgroundColor: msg.role === 'user' ? '#1677ff' : '#fff',
                    color: msg.role === 'user' ? '#fff' : '#333',
                    border: msg.role === 'assistant' ? '1px solid #e8e8e8' : 'none',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.7,
                    fontSize: 14,
                    boxShadow: msg.role === 'assistant' ? '0 1px 3px rgba(0,0,0,0.04)' : 'none',
                  }}
                >
                  {msg.content}
                  {streaming && msg.role === 'assistant' && idx === messages.length - 1 && (
                    <LoadingOutlined style={{ marginLeft: 8 }} spin />
                  )}
                </div>
                {msg.entities && msg.role === 'assistant' && (
                  <div
                    style={{
                      marginTop: 10,
                      maxWidth: '82%',
                      background: '#f6ffed',
                      border: '1px solid #b7eb8f',
                      borderRadius: 10,
                      padding: '12px 16px',
                    }}
                  >
                    <Descriptions size="small" column={2} colon={false}>
                      {msg.entities.department ? (
                        <Descriptions.Item label="部门">{String(msg.entities.department)}</Descriptions.Item>
                      ) : null}
                      {msg.entities.expense_type ? (
                        <Descriptions.Item label="费用类型">{String(msg.entities.expense_type)}</Descriptions.Item>
                      ) : null}
                      {Number(msg.entities.total_amount) > 0 && (
                        <Descriptions.Item label="金额">
                          <span style={{ fontWeight: 600, color: '#1677ff' }}>
                            ¥{Number(msg.entities.total_amount).toLocaleString()}
                          </span>
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                  </div>
                )}
                {msg.intent && msg.role === 'assistant' && (
                  <Tag color="blue" style={{ marginTop: 6 }}>意图: {msg.intent}</Tag>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {fileList.length > 0 && (
            <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {fileList.map((f) => (
                <div
                  key={f.uid}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 12px',
                    background: '#f5f5f5',
                    borderRadius: 8,
                    border: '1px solid #e8e8e8',
                  }}
                >
                  {fileIcon(f.name)}
                  <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>
                    {f.name}
                  </span>
                  <DeleteOutlined
                    style={{ cursor: 'pointer', color: '#999', fontSize: 12 }}
                    onClick={() => setFileList((prev) => prev.filter((x) => x.uid !== f.uid))}
                  />
                </div>
              ))}
            </div>
          )}

          <Space.Compact style={{ width: '100%' }}>
            <Upload
              fileList={fileList}
              onChange={({ fileList: fl }) => setFileList(fl)}
              beforeUpload={() => false}
              accept=".pdf,.png,.jpg,.jpeg"
              maxCount={5}
              showUploadList={false}
            >
              <Button icon={<UploadOutlined />}>上传票据</Button>
            </Upload>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => { e.preventDefault(); handleSend(); }}
              placeholder="描述报销需求..."
              autoSize={{ minRows: 1, maxRows: 4 }}
            />
            <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading}>
              发送
            </Button>
          </Space.Compact>
        </Card>
      </div>

      {/* ===== 右侧流程演示面板 ===== */}
      {stepsVisible && (
        <div style={{ width: 300, flexShrink: 0 }}>
          <Card
            title={<Space><NodeIndexOutlined />流程演示</Space>}
            size="small"
            extra={
              <Button size="small" type="text" onClick={() => setStepsVisible(false)}>收起</Button>
            }
          >
            {flowSteps.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', fontSize: 13, marginTop: 24 }}>
                发送报销消息后<br />自动展示执行步骤
              </div>
            ) : (
              <Steps
                direction="vertical"
                size="small"
                current={-1}
                items={stepsItems as never}
                style={{ fontSize: 13 }}
              />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
