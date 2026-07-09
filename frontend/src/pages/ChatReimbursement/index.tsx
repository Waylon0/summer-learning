import { useState, useRef, useEffect } from 'react';
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

const INITIAL_STEPS: FlowStep[] = [
  { key: 'intent', title: '意图识别', description: '等待中', status: 'wait' },
  { key: 'ocr', title: 'OCR票据识别', description: '等待中', status: 'wait' },
  { key: 'compliance', title: '合规检查', description: '等待中', status: 'wait' },
  { key: 'budget', title: '预算检查', description: '等待中', status: 'wait' },
  { key: 'pdf', title: '生成报销单PDF', description: '等待中', status: 'wait' },
  { key: 'email', title: '发送审批邮件', description: '等待中', status: 'wait' },
];

const STEP_PATTERNS: { key: string; pattern: RegExp; doneDesc: string }[] = [
  { key: 'ocr', pattern: /OCR|识别完成|票据信息|发票代码|发票号码|未检测到上传票据/, doneDesc: '已识别票据信息' },
  { key: 'compliance', pattern: /合规检查|符合.*标准|合规.*通过|超标|违规|不符合|政策要求/, doneDesc: '合规检查完成' },
  { key: 'budget', pattern: /预算|余额|剩余.*预算|可用|已使用|部门.*预算|预算充足|预算不足/, doneDesc: '预算检查完成' },
  { key: 'pdf', pattern: /报销单已生成|PDF.*生成|📄/, doneDesc: '报销单已生成' },
  { key: 'email', pattern: /已提交审批|邮件.*发送|📧|审批流程|出纳付款/, doneDesc: '邮件已发送' },
];

function detectSteps(accumulatedText: string, intent: string | null): FlowStep[] {
  return INITIAL_STEPS.map((s) => {
    if (s.key === 'intent') {
      if (intent) return { ...s, status: 'finish', description: `识别为: ${intent}` };
      return s;
    }
    const match = STEP_PATTERNS.find((p) => p.key === s.key);
    if (match && match.pattern.test(accumulatedText)) {
      return { ...s, status: 'finish', description: match.doneDesc };
    }
    return s;
  });
}

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
  const [flowSteps, setFlowSteps] = useState<FlowStep[]>(INITIAL_STEPS);
  const [currentIntent, setCurrentIntent] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, addMessage, appendToLastAssistant, sessionId, setSessionId, clearMessages } = useAppStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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

    // 重置流程步骤
    setCurrentIntent(null);
    setFlowSteps(INITIAL_STEPS.map((s) =>
      s.key === 'intent' ? { ...s, status: 'process' as const, description: '分析中...' } : s,
    ));
    if (streamMode) setStepsVisible(true);

    setLoading(true);

    try {
      const attachments = await Promise.all(
        fileList
          .filter((f) => f.originFileObj)
          .map((f) => uploadInvoice(f.originFileObj!)),
      ).then((results) => results.map((r) => r.object_name));

      if (streamMode) {
        setStreaming(true);
        let accumulated = '';
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
              const intent = (event as Record<string, unknown>).intent as string || event.type;
              setCurrentIntent(intent);
              setFlowSteps((prev) => prev.map((s) =>
                s.key === 'intent' ? { ...s, status: 'finish' as const, description: `识别为: ${intent}` } : s,
              ));
              break;
            }
            case 'message': {
              const content = (event as Record<string, unknown>).content as string || '';
              appendToLastAssistant(content);
              accumulated += content;
              setFlowSteps(detectSteps(accumulated, currentIntent));
              break;
            }
            case 'done':
              if (event.session_id) setSessionId(event.session_id);
              setFlowSteps((prev) => prev.map((s) =>
                s.status === 'wait' ? s : { ...s, status: 'finish' as const },
              ));
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
            <Steps
              direction="vertical"
              size="small"
              current={-1}
              items={stepsItems as never}
              style={{ fontSize: 13 }}
            />
            {!streaming && flowSteps.every((s) => s.status === 'wait') && (
              <div style={{ textAlign: 'center', color: '#999', fontSize: 13, marginTop: 24 }}>
                发送报销消息后<br />自动展示执行步骤
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
