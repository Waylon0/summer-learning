import { useState, useRef, useEffect } from 'react';
import { Card, Input, Button, Space, Upload, Tag, message, Spin } from 'antd';
import { SendOutlined, UploadOutlined, FileTextOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { sendChatMessage, uploadInvoice } from '@/services/api';
import { useAppStore } from '@/stores';
import type { ChatMessage } from '@/types';

export default function ChatReimbursement() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, addMessage, sessionId, setSessionId, clearMessages } = useAppStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() && fileList.length === 0) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input || '请识别上传的票据',
      timestamp: new Date().toISOString(),
    };
    addMessage(userMsg);
    setInput('');
    setLoading(true);

    try {
      const attachments: string[] = [];
      for (const f of fileList) {
        if (f.originFileObj) {
          const result = await uploadInvoice(f.originFileObj);
          attachments.push(result.object_name);
        }
      }

      const res = await sendChatMessage({
        message: userMsg.content,
        session_id: sessionId || undefined,
        attachments: attachments.length > 0 ? attachments : undefined,
      });

      if (res.session_id) setSessionId(res.session_id);

      const assistantMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: res.reply,
        timestamp: new Date().toISOString(),
        entities: res.entities,
      };
      addMessage(assistantMsg);
      setFileList([]);
    } catch (e) {
      message.error('请求失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card
      title="智能报销对话"
      extra={<Button size="small" onClick={clearMessages}>清空对话</Button>}
    >
      <div style={{ height: 480, overflowY: 'auto', marginBottom: 16, padding: 8 }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#999', marginTop: 160 }}>
            <FileTextOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <p>你好！我是财务报销助手，请描述你的报销需求，或上传票据文件。</p>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
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
                backgroundColor: msg.role === 'user' ? '#1677ff' : '#f0f0f0',
                color: msg.role === 'user' ? '#fff' : '#000',
                textAlign: 'left',
                whiteSpace: 'pre-wrap',
              }}
            >
              {msg.content}
            </div>
            {msg.entities && msg.role === 'assistant' && (
              <div style={{ marginTop: 4 }}>
                {Object.entries(msg.entities).map(([k, v]) => (
                  <Tag key={k} style={{ marginBottom: 4 }}>
                    {k}: {String(v)}
                  </Tag>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ textAlign: 'center' }}>
            <Spin size="small" /> 处理中...
          </div>
        )}
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
