import { useState, useRef, useEffect } from 'react';
import { Card, Input, Button, Space, Upload, Tag, message, Spin, Switch } from 'antd';
import { SendOutlined, UploadOutlined, FileTextOutlined, LoadingOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { useAppStore } from '@/stores';
import { uploadInvoice } from '@/services/api';
import type { ChatMessage, SSEEvent } from '@/types';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export default function ChatReimbursement() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [streamMode, setStreamMode] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    messages, addMessage, appendToLastAssistant,
    setLastAssistantEntities, sessionId, setSessionId, clearMessages,
  } = useAppStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const uploadFiles = async (): Promise<string[]> => {
    const results = await Promise.all(
      fileList
        .filter((f) => f.originFileObj)
        .map((f) => uploadInvoice(f.originFileObj!))
    );
    return results.map((r) => r.object_name);
  };

  const buildRequestBody = (userContent: string, attachments: string[]) => ({
    message: userContent,
    session_id: sessionId || undefined,
    attachments: attachments.length > 0 ? attachments : undefined,
  });

  const handleSendNormal = async (userContent: string, attachments: string[]) => {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody(userContent, attachments)),
    });
    if (!res.ok) throw new Error('请求失败');
    const data = await res.json();
    if (data.session_id) setSessionId(data.session_id);
    addMessage({
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: data.reply,
      timestamp: new Date().toISOString(),
      intent: data.intent,
      entities: data.entities,
    });
  };

  const handleSendStream = async (userContent: string, attachments: string[]): Promise<void> => {
    const res = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody(userContent, attachments)),
    });
    if (!res.ok) throw new Error('流式请求失败');

    const reader = res.body?.getReader();
    if (!reader) throw new Error('无法读取流式响应');

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event: SSEEvent = JSON.parse(line.slice(6));
          switch (event.type) {
            case 'intent':
              setSessionId(event.session_id || null);
              setLastAssistantEntities(event.intent);
              break;
            case 'message':
              appendToLastAssistant(event.content || '');
              break;
            case 'done':
              setSessionId(event.session_id || null);
              break;
            case 'error':
              message.error(event.content || '处理异常');
              break;
          }
        } catch {
          // 忽略非 JSON 行
        }
      }
    }
  };

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
    setLoading(true);
    setStreaming(streamMode);

    try {
      const attachments = await uploadFiles();
      if (streamMode) {
        setStreaming(true);
        await handleSendStream(userContent, attachments);
      } else {
        await handleSendNormal(userContent, attachments);
      }
      setFileList([]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '请求失败，请检查后端服务是否启动';
      message.error(msg);
    } finally {
      setLoading(false);
      setStreaming(false);
    }
  };

  return (
    <Card
      title="智能报销对话"
      extra={
        <Space>
          <span style={{ fontSize: 12, color: '#999' }}>SSE流式</span>
          <Switch size="small" checked={streamMode} onChange={setStreamMode} />
          <Button size="small" onClick={clearMessages}>清空对话</Button>
        </Space>
      }
    >
      <div style={{ height: 480, overflowY: 'auto', marginBottom: 16, padding: 8, background: '#fafafa', borderRadius: 8 }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#999', marginTop: 160 }}>
            <FileTextOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <p>你好！我是财务报销助手。</p>
            <p style={{ fontSize: 12 }}>试试说：我要报销差旅费 1500 元，部门技术部</p>
          </div>
        )}
        {messages.map((msg, idx) => (
          <div
            key={msg.id || idx}
            style={{
              marginBottom: 16,
              textAlign: msg.role === 'user' ? 'right' : 'left',
            }}
          >
            <div
              style={{
                display: 'inline-block',
                maxWidth: '80%',
                padding: '10px 16px',
                borderRadius: 12,
                backgroundColor: msg.role === 'user' ? '#1677ff' : '#e6f4ff',
                color: msg.role === 'user' ? '#fff' : '#000',
                textAlign: 'left',
                whiteSpace: 'pre-wrap',
              }}
            >
              {msg.content}
              {streaming && msg.role === 'assistant' && idx === messages.length - 1 && (
                <LoadingOutlined style={{ marginLeft: 8 }} spin />
              )}
            </div>
            {(msg.intent || msg.entities) && msg.role === 'assistant' && (
              <div style={{ marginTop: 4 }}>
                {msg.intent && <Tag color="blue">意图: {msg.intent}</Tag>}
                {msg.entities && Object.entries(msg.entities).map(([k, v]) => (
                  <Tag key={k} style={{ marginBottom: 4 }}>
                    {k}: {String(v)}
                  </Tag>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <Space.Compact style={{ width: '100%' }}>
        <Upload
          fileList={fileList}
          onChange={({ fileList: fl }) => setFileList(fl)}
          beforeUpload={() => false}
          accept=".pdf,.png,.jpg,.jpeg"
          maxCount={5}
        >
          <Button icon={<UploadOutlined />}>上传票据</Button>
        </Upload>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => { e.preventDefault(); handleSend(); }}
          placeholder="描述报销需求... (如: 我要报销差旅费1500元，部门技术部)"
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
        <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading}>
          发送
        </Button>
      </Space.Compact>
    </Card>
  );
}
