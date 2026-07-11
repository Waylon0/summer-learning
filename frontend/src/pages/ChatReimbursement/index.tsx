import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Card, Input, Button, Space, Upload, message, Collapse, Tag, Modal, Empty, Tooltip,
} from 'antd';
import {
  SendOutlined, UploadOutlined, FilePdfOutlined, FileJpgOutlined, FileTextOutlined,
  LoadingOutlined, DeleteOutlined, PlusOutlined, MessageOutlined, EditOutlined,
  ToolOutlined, BulbOutlined, MailOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import {
  sendChatMessageStream, uploadInvoice,
  createConversation, listConversations, getConversation,
  renameConversation, deleteConversation, sendReimbEmail,
} from '@/services/api';
import type { ChatMessage, ThinkingStep, ConversationSummary } from '@/types';

const fileIcon = (name: string) => {
  const ext = name.split('.').pop()?.toLowerCase();
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />;
  if (['png', 'jpg', 'jpeg'].includes(ext || '')) return <FileJpgOutlined style={{ color: '#1677ff', fontSize: 20 }} />;
  return <FileTextOutlined style={{ color: '#999', fontSize: 20 }} />;
};

const quickPrompts = [
  '帮我报销一笔差旅费，我有住宿和交通发票',
  '录入一笔招待客户的费用，2000 元餐饮',
  '查看我最近报销单的审批进度',
];

// 链接匹配：完整 URL + 相对路径 API 链接
const URL_RE = /((?:https?:\/\/|\/api\/)[^\s<>"'\n]*)/g;

function resolveUrl(raw: string): string {
  if (raw.startsWith('http')) return raw;
  const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/api\/v1\/?$/, '');
  return base + raw;
}

function renderMessageContent(text: string) {
  const parts: React.ReactNode[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = URL_RE.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index));
    }
    const raw = match[0];
    const url = resolveUrl(raw);
    const isPdf = /\.pdf(\?|$)/i.test(raw) || /reimburse-attachments/i.test(raw) || /upload\/files/i.test(raw);

    if (isPdf) {
      parts.push(
        <span key={match.index} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, margin: '2px 0' }}>
          <a href={url} target="_blank" rel="noreferrer"
            style={{
              display: 'inline-block', padding: '3px 12px',
              background: '#e6f4ff', border: '1px solid #91caff',
              borderRadius: 6, color: '#1677ff', fontWeight: 500,
              fontSize: 13, textDecoration: 'none',
            }}
          >
            📄 点击预览
          </a>
          <a href={url} download style={{
            display: 'inline-block', padding: '3px 12px',
            background: '#f5f5f5', border: '1px solid #d9d9d9',
            borderRadius: 6, color: '#555', fontWeight: 500,
            fontSize: 13, textDecoration: 'none',
          }}>
            📥 点击下载
          </a>
        </span>,
      );
    } else {
      parts.push(<a key={match.index} href={url} target="_blank" rel="noreferrer">{raw}</a>);
    }
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx));
  return parts.length > 0 ? parts : text;
}

function ThinkingPanel({ steps, live }: { steps: ThinkingStep[]; live?: boolean }) {
  if (!steps || steps.length === 0) return null;
  return (
    <Collapse
      ghost
      defaultActiveKey={[]}
      style={{ marginTop: 6, background: '#f7f9fc', borderRadius: 8 }}
      items={[{
        key: 't',
        label: (
          <span style={{ fontSize: 12, color: '#8c8c8c' }}>
            <BulbOutlined /> 思考过程（{steps.length} 步）{live && <LoadingOutlined style={{ marginLeft: 6 }} spin />}
          </span>
        ),
        children: (
          <div style={{ fontSize: 12.5 }}>
            {steps.map((s, i) => (
              <div key={i} style={{ marginBottom: 8, paddingLeft: 8, borderLeft: '2px solid #d9e1ec' }}>
                {s.kind === 'tool_call' ? (
                  <div>
                    <Tag color="processing" style={{ marginBottom: 2 }}>
                      <ToolOutlined /> 调用工具
                    </Tag>
                    <span style={{ color: '#555' }}>{s.label}</span>
                    {s.input && Object.keys(s.input).length > 0 && (
                      <div style={{ color: '#999', marginTop: 2, wordBreak: 'break-all' }}>
                        参数: {JSON.stringify(s.input)}
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <Tag color="success" style={{ marginBottom: 2 }}>✓ 结果</Tag>
                    <span style={{ color: '#555' }}>{s.label}</span>
                    <div style={{ color: '#999', marginTop: 2, wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
                      {(s.output || '').slice(0, 300)}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ),
      }]}
    />
  );
}

export default function ChatReimbursement() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [liveThinking, setLiveThinking] = useState<ThinkingStep[]>([]);
  const [emailStatus, setEmailStatus] = useState<Record<string, 'loading' | 'sent' | 'error'>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { refreshConversations(); }, [refreshConversations]);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, liveThinking]);

  const loadConversation = async (id: string) => {
    try {
      const detail = await getConversation(id);
      setSessionId(id);
      setMessages(detail.messages.map((m) => ({
        id: m.id,
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.content,
        timestamp: m.created_at || new Date().toISOString(),
        thinking: (m.reasoning as ThinkingStep[]) || undefined,
      })));
    } catch {
      message.error('加载会话失败');
    }
  };

  const handleNewConversation = async () => {
    try {
      const conv = await createConversation('新对话');
      setSessionId(conv.id);
      setMessages([]);
      setLiveThinking([]);
      await refreshConversations();
    } catch {
      message.error('新建会话失败');
    }
  };

  const handleRename = (conv: ConversationSummary) => {
    let val = conv.title;
    Modal.confirm({
      title: '重命名会话',
      content: <Input defaultValue={conv.title} onChange={(e) => { val = e.target.value; }} />,
      onOk: async () => {
        await renameConversation(conv.id, val);
        await refreshConversations();
      },
    });
  };

  const handleDelete = (conv: ConversationSummary) => {
    Modal.confirm({
      title: '删除会话',
      content: `确定删除「${conv.title}」吗？`,
      okType: 'danger',
      onOk: async () => {
        await deleteConversation(conv.id);
        if (sessionId === conv.id) { setSessionId(null); setMessages([]); }
        await refreshConversations();
      },
    });
  };

  const handleSendEmailFromChat = async (reimbId: string) => {
    setEmailStatus((prev) => ({ ...prev, [reimbId]: 'loading' }));
    try {
      const res = await sendReimbEmail(reimbId, 'manager');
      if (res.sent_count && res.sent_count > 0) {
        setEmailStatus((prev) => ({ ...prev, [reimbId]: 'sent' }));
        message.success(res.message || '邮件已发送');
      } else {
        setEmailStatus((prev) => ({ ...prev, [reimbId]: 'error' }));
        message.warning(res.message || '未找到有效收件邮箱');
      }
    } catch {
      setEmailStatus((prev) => ({ ...prev, [reimbId]: 'error' }));
      message.error('邮件发送失败');
    }
  };

  const handleSend = async () => {
    if (!input.trim() && fileList.length === 0) return;
    const userContent = input || '请识别我上传的票据并帮我报销';

    // 确保有会话
    let sid = sessionId;
    if (!sid) {
      try {
        const conv = await createConversation('新对话');
        sid = conv.id;
        setSessionId(sid);
      } catch { message.error('创建会话失败'); return; }
    }

    setMessages((prev) => [...prev, {
      id: Date.now().toString(), role: 'user', content: userContent,
      timestamp: new Date().toISOString(),
    }]);
    setInput('');
    setLoading(true);
    setStreaming(true);
    setLiveThinking([]);

    const collectedThinking: ThinkingStep[] = [];
    let assistantStarted = false;

    const ensureAssistant = () => {
      if (!assistantStarted) {
        assistantStarted = true;
        setMessages((prev) => [...prev, {
          id: (Date.now() + 1).toString(), role: 'assistant', content: '',
          timestamp: new Date().toISOString(),
        }]);
      }
    };
    const appendContent = (c: string) => {
      ensureAssistant();
      setMessages((prev) => {
        const msgs = [...prev];
        const last = msgs[msgs.length - 1];
        if (last && last.role === 'assistant') msgs[msgs.length - 1] = { ...last, content: last.content + c };
        return msgs;
      });
    };

    try {
      const attachments = await Promise.all(
        fileList.filter((f) => f.originFileObj).map((f) => uploadInvoice(f.originFileObj!)),
      ).then((rs) => rs.map((r) => r.object_name));

      for await (const event of sendChatMessageStream({
        message: userContent,
        session_id: sid || undefined,
        attachments: attachments.length > 0 ? attachments : undefined,
      })) {
        switch (event.type) {
          case 'tool_call': {
            collectedThinking.push({
              kind: 'tool_call', tool: event.tool || '', label: event.label || event.tool || '',
              input: event.input, thought: event.thought,
            });
            setLiveThinking([...collectedThinking]);
            break;
          }
          case 'tool_result': {
            collectedThinking.push({
              kind: 'tool_result', tool: event.tool || '', label: event.label || event.tool || '',
              output: event.output,
            });
            setLiveThinking([...collectedThinking]);
            break;
          }
          case 'message':
            appendContent((event as Record<string, unknown>).content as string || '');
            break;
          case 'done': {
            const reimbId = (event as Record<string, unknown>).reimb_id as string | undefined;
            if (reimbId) {
              setMessages((prev) => {
                const msgs = [...prev];
                const last = msgs[msgs.length - 1];
                if (last && last.role === 'assistant') msgs[msgs.length - 1] = { ...last, reimb_id: reimbId };
                return msgs;
              });
            }
            break;
          }
          case 'error':
            message.error(event.message || '处理异常');
            break;
        }
      }
      // 把思考过程附加到最后一条助手消息
      if (collectedThinking.length > 0) {
        setMessages((prev) => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last && last.role === 'assistant') msgs[msgs.length - 1] = { ...last, thinking: collectedThinking };
          return msgs;
        });
      }
      setFileList([]);
      refreshConversations();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '请求失败');
    } finally {
      setLoading(false);
      setStreaming(false);
      setLiveThinking([]);
    }
  };

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'stretch', height: 'calc(100vh - 140px)' }}>
      {/* ===== 左侧会话列表 ===== */}
      <div style={{ width: 240, flexShrink: 0 }}>
        <Card
          size="small"
          title={<span><MessageOutlined /> 会话</span>}
          extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={handleNewConversation}>新建</Button>}
          styles={{ body: { padding: 8, height: 'calc(100vh - 200px)', overflowY: 'auto' } }}
        >
          {conversations.length === 0 && <Empty description="暂无会话" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => loadConversation(c.id)}
              style={{
                padding: '8px 10px', marginBottom: 4, borderRadius: 8, cursor: 'pointer',
                background: sessionId === c.id ? '#e6f4ff' : 'transparent',
                border: sessionId === c.id ? '1px solid #91caff' : '1px solid transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4,
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13, flex: 1 }}>
                {c.title}
              </span>
              <Space size={2}>
                <Tooltip title="重命名">
                  <EditOutlined style={{ color: '#999', fontSize: 12 }} onClick={(e) => { e.stopPropagation(); handleRename(c); }} />
                </Tooltip>
                <Tooltip title="删除">
                  <DeleteOutlined style={{ color: '#999', fontSize: 12 }} onClick={(e) => { e.stopPropagation(); handleDelete(c); }} />
                </Tooltip>
              </Space>
            </div>
          ))}
        </Card>
      </div>

      {/* ===== 右侧对话区 ===== */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <Card title="智能报销对话" styles={{ body: { display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' } }}>
          <div style={{ flex: 1, overflowY: 'auto', marginBottom: 16, padding: 16, background: '#fafbfc', borderRadius: 8, border: '1px solid #f0f0f0' }}>
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', color: '#999', marginTop: 60 }}>
                <FileTextOutlined style={{ fontSize: 56, marginBottom: 16, color: '#bfbfbf' }} />
                <p style={{ fontSize: 15, color: '#555' }}>你好，我是企业财务报销助手</p>
                <p style={{ fontSize: 13, color: '#999' }}>可以上传票据图片/PDF，或直接描述报销需求</p>
                <Space style={{ marginTop: 16 }} wrap>
                  {quickPrompts.map((p) => (
                    <Tag key={p} color="blue" style={{ cursor: 'pointer', padding: '4px 12px', fontSize: 13 }} onClick={() => setInput(p)}>
                      {p}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}
            {messages.map((msg, idx) => (
              <div key={msg.id || idx} style={{ marginBottom: 20, display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{msg.role === 'user' ? '我' : 'ReimburseAgent'}</div>
                {/* 历史思考过程（折叠） */}
                {msg.role === 'assistant' && msg.thinking && msg.thinking.length > 0 && (
                  <div style={{ maxWidth: '86%', width: '100%' }}><ThinkingPanel steps={msg.thinking} /></div>
                )}
                <div style={{
                  maxWidth: '86%',
                  padding: '12px 18px',
                  borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                  backgroundColor: msg.role === 'user' ? '#1677ff' : '#fff',
                  color: msg.role === 'user' ? '#fff' : '#333',
                  border: msg.role === 'assistant' ? '1px solid #e8e8e8' : 'none',
                  whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 14, marginTop: 6,
                }}>
                  {renderMessageContent(msg.content) || (streaming && idx === messages.length - 1 ? '思考中…' : '')}
                  {streaming && msg.role === 'assistant' && idx === messages.length - 1 && (
                    <LoadingOutlined style={{ marginLeft: 8 }} spin />
                  )}
                </div>
                {/* 发送邮件按钮 */}
                {msg.role === 'assistant' && msg.reimb_id && (
                  <div style={{ marginTop: 6 }}>
                    {emailStatus[msg.reimb_id] === 'sent' ? (
                      <Tag icon={<CheckCircleOutlined />} color="success">邮件已发送</Tag>
                    ) : (
                      <Button
                        size="small"
                        icon={<MailOutlined />}
                        loading={emailStatus[msg.reimb_id] === 'loading'}
                        onClick={() => handleSendEmailFromChat(msg.reimb_id!)}
                      >
                        发送审批邮件
                      </Button>
                    )}
                    {emailStatus[msg.reimb_id] === 'error' && (
                      <Button
                        size="small"
                        icon={<MailOutlined />}
                        onClick={() => handleSendEmailFromChat(msg.reimb_id!)}
                        style={{ marginLeft: 8 }}
                      >
                        重试
                      </Button>
                    )}
                  </div>
                )}
              </div>
            ))}
            {/* 实时思考过程（本轮进行中） */}
            {streaming && liveThinking.length > 0 && (
              <div style={{ maxWidth: '86%' }}><ThinkingPanel steps={liveThinking} live /></div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {fileList.length > 0 && (
            <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {fileList.map((f) => (
                <div key={f.uid} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: '#f5f5f5', borderRadius: 8, border: '1px solid #e8e8e8' }}>
                  {fileIcon(f.name)}
                  <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>{f.name}</span>
                  <DeleteOutlined style={{ cursor: 'pointer', color: '#999', fontSize: 12 }} onClick={() => setFileList((prev) => prev.filter((x) => x.uid !== f.uid))} />
                </div>
              ))}
            </div>
          )}

          <Space.Compact style={{ width: '100%' }}>
            <Upload fileList={fileList} onChange={({ fileList: fl }) => setFileList(fl)} beforeUpload={() => false} accept=".pdf,.png,.jpg,.jpeg" maxCount={5} showUploadList={false}>
              <Button icon={<UploadOutlined />}>上传票据</Button>
            </Upload>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => { e.preventDefault(); handleSend(); }}
              placeholder="描述报销需求…"
              autoSize={{ minRows: 1, maxRows: 4 }}
            />
            <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading}>发送</Button>
          </Space.Compact>
        </Card>
      </div>
    </div>
  );
}
