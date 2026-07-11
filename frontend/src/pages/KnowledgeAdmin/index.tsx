import { useState, useEffect, useCallback } from 'react';
import {
  Card, Button, Input, message, Spin, Empty, Space, Tag, Modal, Popconfirm,
  Row, Col, Drawer, Descriptions, Divider,
} from 'antd';
import {
  ReloadOutlined, PlusOutlined, SaveOutlined, StopOutlined,
  CheckCircleOutlined, SyncOutlined, BookOutlined, SearchOutlined,
  FileTextOutlined, InfoCircleOutlined,
} from '@ant-design/icons';
import {
  getKnowledgeDocs, getKnowledgeDoc, saveKnowledgeDoc,
  createKnowledgeDoc, disableKnowledgeDoc, enableKnowledgeDoc,
  reindexKnowledge, getKnowledgeStatus, searchKnowledge,
} from '@/services/api';
import { useAuthStore } from '@/stores';
import type { KnowledgeDocItem, KnowledgeStatus, KnowledgeSearchResult } from '@/types';

export default function KnowledgeAdmin() {
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';

  const [docs, setDocs] = useState<KnowledgeDocItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [contentLoading, setContentLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [editReason, setEditReason] = useState('');

  // 新建
  const [createOpen, setCreateOpen] = useState(false);
  const [createKey, setCreateKey] = useState('');
  const [createLoading, setCreateLoading] = useState(false);

  // 搜索 & 状态
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResult, setSearchResult] = useState<KnowledgeSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try { setDocs(await getKnowledgeDocs()); } catch { message.error('获取知识文档列表失败'); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const selectDoc = async (docKey: string) => {
    setSelectedKey(docKey);
    setContentLoading(true);
    try {
      const d = await getKnowledgeDoc(docKey);
      setContent(d.content);
      setEditReason('');
    } catch { message.error('读取文档失败'); }
    setContentLoading(false);
  };

  const handleSave = async () => {
    if (!selectedKey) return;
    setSaving(true);
    try {
      const res = await saveKnowledgeDoc(selectedKey, { content, reason: editReason || undefined });
      message.success(res.reindexed ? `已保存并重建索引（${res.index_chunks_total} 分块）` : '已保存（未重建索引）');
      fetchDocs();
    } catch (e) { message.error(e instanceof Error ? e.message : '保存失败'); }
    setSaving(false);
  };

  const handleCreate = async () => {
    if (!createKey.trim()) { message.warning('文档标识不能为空'); return; }
    if (!/^[a-zA-Z0-9_]+$/.test(createKey.trim())) { message.warning('文档标识只能包含字母、数字、下划线'); return; }
    setCreateLoading(true);
    try {
      await createKnowledgeDoc({ doc_key: createKey.trim(), content: '' });
      message.success('文档创建成功');
      setCreateOpen(false);
      setCreateKey('');
      fetchDocs();
    } catch (e) { message.error(e instanceof Error ? e.message : '创建失败'); }
    setCreateLoading(false);
  };

  const handleDisable = async (docKey: string) => {
    try {
      await disableKnowledgeDoc(docKey);
      message.success(`${docKey} 已停用`);
      if (selectedKey === docKey) { setSelectedKey(null); setContent(''); }
      fetchDocs();
    } catch (e) { message.error(e instanceof Error ? e.message : '停用失败'); }
  };

  const handleEnable = async (docKey: string) => {
    try { await enableKnowledgeDoc(docKey); message.success(`${docKey} 已启用`); fetchDocs(); } catch (e) { message.error(e instanceof Error ? e.message : '启用失败'); }
  };

  const handleReindex = async () => {
    setReindexing(true);
    try {
      const res = await reindexKnowledge();
      message.success(res.reindexed ? `索引重建完成，共 ${res.index_chunks_total} 个分块` : '索引重建失败');
    } catch (e) { message.error(e instanceof Error ? e.message : '重建失败'); }
    setReindexing(false);
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try { setSearchResult(await searchKnowledge(searchQuery.trim())); } catch { message.error('搜索失败'); }
    setSearching(false);
  };

  const showStatus = async () => {
    setStatusOpen(true);
    setStatusLoading(true);
    try { setStatus(await getKnowledgeStatus()); } catch { message.error('获取状态失败'); }
    setStatusLoading(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      {/* 顶部工具栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space><BookOutlined style={{ fontSize: 18, color: '#1677ff' }} /><span style={{ fontWeight: 600, fontSize: 16 }}>知识库管理</span></Space>
        <Space>
          {isAdmin && <Button icon={<SyncOutlined />} onClick={handleReindex} loading={reindexing}>重建索引</Button>}
          <Button icon={<InfoCircleOutlined />} onClick={showStatus}>索引状态</Button>
          <Button icon={<SearchOutlined />} onClick={() => { setSearchOpen(true); setSearchQuery(''); setSearchResult(null); }}>检索调试</Button>
          <Button icon={<ReloadOutlined />} onClick={fetchDocs} loading={loading}>刷新</Button>
        </Space>
      </div>

      {/* 主内容区 */}
      <Row gutter={16} style={{ flex: 1, minHeight: 0 }}>
        {/* 左侧：文档列表 */}
        <Col span={5} style={{ height: '100%' }}>
          <Card
            size="small"
            title={<span><FileTextOutlined /> 知识文档</span>}
            extra={isAdmin ? <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => { setCreateKey(''); setCreateOpen(true); }}>新建</Button> : null}
            style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            styles={{ body: { flex: 1, overflow: 'hidden', padding: 0, display: 'flex', flexDirection: 'column' } }}
          >
            <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
              <Spin spinning={loading}>
                {docs.length === 0 ? (
                  <Empty description="暂无知识文档" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
                ) : (
                  docs.map((d) => (
                    <div
                      key={d.doc_key}
                      onClick={() => selectDoc(d.doc_key)}
                      style={{
                        cursor: 'pointer', padding: '12px 14px', borderRadius: 8,
                        background: selectedKey === d.doc_key ? '#e6f4ff' : '#fafafa',
                        border: selectedKey === d.doc_key ? '1px solid #91caff' : '1px solid #f0f0f0',
                        marginBottom: 6, opacity: d.active ? 1 : 0.5, transition: 'all 0.2s',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 500, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {d.title}
                          </div>
                          <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                            {d.doc_key} · {d.chunks} 分块 · {(d.bytes / 1024).toFixed(1)} KB
                          </div>
                        </div>
                        <Space size={4} style={{ marginLeft: 8 }}>
                          <Tag color={d.active ? 'success' : 'default'} style={{ margin: 0 }}>{d.active ? '启用' : '停用'}</Tag>
                          {isAdmin && (d.active ? (
                            <Popconfirm key="disable" title={`停用「${d.doc_key}」？`} onConfirm={(e) => { e?.stopPropagation(); handleDisable(d.doc_key); }} onCancel={(e) => e?.stopPropagation()} okText="确认" cancelText="取消">
                              <Button type="link" size="small" danger icon={<StopOutlined />} onClick={(e) => e.stopPropagation()} style={{ padding: 0 }} />
                            </Popconfirm>
                          ) : (
                            <Popconfirm key="enable" title={`启用「${d.doc_key}」？`} onConfirm={(e) => { e?.stopPropagation(); handleEnable(d.doc_key); }} onCancel={(e) => e?.stopPropagation()} okText="确认" cancelText="取消">
                              <Button type="link" size="small" icon={<CheckCircleOutlined />} style={{ color: '#52c41a', padding: 0 }} onClick={(e) => e.stopPropagation()} />
                            </Popconfirm>
                          ))}
                        </Space>
                      </div>
                    </div>
                  ))
                )}
              </Spin>
            </div>
          </Card>
        </Col>

        {/* 右侧：编辑器 */}
        <Col span={19} style={{ height: '100%' }}>
          <Card
            size="small"
            title={selectedKey ? <Space><span>编辑：{selectedKey}</span><Tag color="blue">Markdown</Tag></Space> : '选择一个文档开始编辑'}
            extra={
              selectedKey && isAdmin ? (
                <Space>
                  <Input placeholder="变更原因（可选）" size="small" style={{ width: 180 }} value={editReason} onChange={(e) => setEditReason(e.target.value)} />
                  <Button type="primary" size="small" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>保存</Button>
                </Space>
              ) : null
            }
            style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            styles={{ body: { flex: 1, overflow: 'hidden', padding: 0, display: 'flex', flexDirection: 'column' } }}
          >
            <Spin spinning={contentLoading} style={{ flex: 1, display: 'flex', flexDirection: 'column', width: '100%' }}>
              {!selectedKey ? (
                <Empty description="请在左侧选择文档" style={{ marginTop: 120 }} />
              ) : !isAdmin ? (
                <div style={{
                  flex: 1, width: '100%', padding: 0, whiteSpace: 'pre-wrap',
                  fontFamily: 'Consolas, "Microsoft YaHei", monospace', fontSize: 14, lineHeight: 2,
                  overflow: 'auto', background: '#fdfdfd', color: '#333',
                }}>
                  {content || '(文档内容为空)'}
                </div>
              ) : (
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="# Markdown 内容..."
                  style={{
                    flex: 1, width: '100%', minHeight: 0, resize: 'none', border: 'none',
                    outline: 'none', borderRadius: 0, boxSizing: 'border-box',
                    fontFamily: 'Consolas, "Microsoft YaHei", monospace', fontSize: 15,
                    lineHeight: 2, padding: '20px 24px', background: '#fdfdfd', color: '#333',
                  }}
                />
              )}
            </Spin>
          </Card>
        </Col>
      </Row>

      {/* ===== 新建文档 ===== */}
      <Modal
        title="新建知识文档"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createLoading}
        onOk={handleCreate}
        okText="创建"
      >
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>文档标识（doc_key，字母/数字/下划线） <span style={{ color: '#ff4d4f' }}>*</span></div>
            <Input placeholder="如：expense_policy" value={createKey} onChange={(e) => setCreateKey(e.target.value)} />
          </Col>
        </Row>
      </Modal>

      {/* ===== 检索调试 ===== */}
      <Modal
        title="知识库检索调试"
        open={searchOpen}
        onCancel={() => setSearchOpen(false)}
        footer={null}
        width={640}
      >
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Input placeholder="输入检索查询..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onPressEnter={handleSearch} />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={searching}>搜索</Button>
        </Space.Compact>
        {searchResult && (
          <div>
            <div style={{ marginBottom: 12, fontSize: 13, color: '#666' }}>
              查询「{searchResult.query}」，命中 {searchResult.count} 条：
            </div>
            {searchResult.hits.length === 0 ? (
              <Empty description="无匹配结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              searchResult.hits.map((h, i) => (
                <div key={i} style={{ marginBottom: 12, padding: '10px 14px', background: '#fafafa', borderRadius: 6, border: '1px solid #f0f0f0' }}>
                  <div style={{ marginBottom: 4 }}>
                    <Tag color="blue">{h.doc_key}</Tag>
                    <span style={{ fontSize: 12, color: '#999' }}>相关度：{(h.score * 100).toFixed(1)}%</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: '#555', whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>{h.content.slice(0, 400)}</div>
                </div>
              ))
            )}
          </div>
        )}
      </Modal>

      {/* ===== 索引状态 ===== */}
      <Drawer title="索引状态" open={statusOpen} onClose={() => setStatusOpen(false)} width={480}>
        <Spin spinning={statusLoading}>
          {status ? (
            <>
              <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="索引可用">
                  <Tag color={status.index_available ? 'success' : 'error'}>{status.index_available ? '是' : '否'}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="Embedding 后端">{status.embedding_backend}</Descriptions.Item>
                <Descriptions.Item label="总分块数">{status.index_chunks_total}</Descriptions.Item>
              </Descriptions>
              <Divider orientation="left" plain style={{ fontSize: 13 }}>文件明细</Divider>
              {status.files.map((f) => (
                <div key={f.doc_key} style={{ marginBottom: 10, padding: '8px 12px', background: '#fafafa', borderRadius: 6 }}>
                  <div style={{ fontWeight: 500 }}>{f.doc_key}</div>
                  <div style={{ fontSize: 12, color: '#999' }}>MD5: {f.md5.slice(0, 16)}... · {f.chunks} 分块 · {f.last_built || '-'}</div>
                </div>
              ))}
            </>
          ) : (
            <Empty description="无法获取索引状态" />
          )}
        </Spin>
      </Drawer>
    </div>
  );
}
