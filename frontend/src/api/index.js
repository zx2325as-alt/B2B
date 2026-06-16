import axios from 'axios'
import { toast } from '../utils/notify.js'

const api = axios.create({ baseURL: '/api/v1' })

// 全局错误提示：所有 axios 请求失败都给用户可见反馈，不再静默吞掉
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error?.response?.data?.detail
    const message = typeof detail === 'string'
      ? detail
      : (detail ? JSON.stringify(detail) : (error?.message || '请求失败'))
    toast.error(message)
    return Promise.reject(error)
  }
)

// ── Characters ──────────────────────────────────────────────────────────────
export const characterApi = {
  list: ()                     => api.get('/characters/'),
  get:  (id)                   => api.get(`/characters/${id}`),
  create: (data)               => api.post('/characters/', data),
  update: (id, data)           => api.put(`/characters/${id}`, data),
  delete: (id)                 => api.delete(`/characters/${id}`),
  previewImport: (formData)    => api.post('/characters/imports/preview', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  commitImport: (data)         => api.post('/characters/imports/commit', data),
  getImportStatus: (id)        => api.get(`/characters/imports/${id}/status`),
  exportAll: ()                => api.get('/characters/exports/full'),
  importProfileJson: (file)    => { const fd = new FormData(); fd.append('file', file); return api.post('/characters/import-profile-json', fd, { headers: { 'Content-Type': 'multipart/form-data' } }) },
  getProfileJsonTemplate: ()   => api.get('/characters/import-profile-json/template'),
  suggestUpdate: (id)          => api.post(`/characters/${id}/suggest-update`),
  listObservations: (id)       => api.get(`/characters/${id}/observations`),
  getProfileView: (id)         => api.get(`/characters/${id}/profile-view`),
  getAiUpdateLog: (id)         => api.get(`/characters/${id}/ai-update-log`),
  listEvidence: (id, limit = 80) => api.get(`/characters/${id}/evidence`, { params: { limit } }),
  listMemories: (id, memoryType = '') => api.get(`/characters/${id}/memories`, { params: memoryType ? { memory_type: memoryType } : {} }),
  listSnapshots: (id)          => api.get(`/characters/${id}/snapshots`),
  listHypotheses: (id, status = '') => api.get(`/characters/${id}/hypotheses`, { params: status ? { status } : {} }),
  restoreSnapshot: (id, snapshotId) => api.post(`/characters/${id}/snapshots/${snapshotId}/restore`),
  mergeCharacter: (targetId, sourceId) => api.post(`/characters/${targetId}/merge`, { source_id: sourceId }),
  compactAll: ()               => api.post('/characters/maintenance/compact'),
  backfillEmbeddings: (limit = 500) => api.post('/characters/maintenance/backfill-embeddings', null, { params: { limit } }),
  uploadKnowledge: (id, file, enrichProfile = true) => { const fd = new FormData(); fd.append('file', file); return api.post(`/characters/${id}/knowledge`, fd, { headers: { 'Content-Type': 'multipart/form-data' }, params: { enrich_profile: enrichProfile } }) },
  listKnowledge: (id) => api.get(`/characters/${id}/knowledge`),
  deleteKnowledge: (id, source = '') => api.delete(`/characters/${id}/knowledge`, { params: source ? { source } : {} }),
  listDiagnoses: (id, limit = 80) => api.get(`/characters/${id}/diagnoses`, { params: { limit } }),
  runLongContextReview: (id, data = {}) => api.post(`/characters/${id}/long-context-review`, data),
  graphHealth: ()              => api.get('/characters/graph/health'),
  startGraph: ()               => api.post('/characters/graph/start'),
  syncGraph: ()                => api.post('/characters/graph/sync-all'),
  getGraphContext: (speakerId, listenerId = null) =>
    api.get('/characters/graph/context', { params: { speaker_id: speakerId, listener_id: listenerId } }),
  graphHubs: ()                => api.get('/characters/graph/multi-hop/hubs'),
  graphIntermediaries: (meId, targetId) => api.get('/characters/graph/multi-hop/intermediaries', { params: { me_id: meId, target_id: targetId } }),
  graphPath: (aId, bId)        => api.get('/characters/graph/multi-hop/path', { params: { a_id: aId, b_id: bId } }),
  graphSentimentPropagation: (meId) => api.get('/characters/graph/multi-hop/sentiment-propagation', { params: { me_id: meId } }),
  graphEvidenceChain: (personId) => api.get('/characters/graph/multi-hop/evidence-chain', { params: { person_id: personId } }),
  reviewObservation: (cid, oid, status) =>
    api.post(`/characters/${cid}/observations/${oid}/review`, { status }),
  createBehaviorPattern: (cid, data) => api.post(`/characters/${cid}/behavior-patterns`, data),
  updateBehaviorPattern: (cid, oid, data) => api.put(`/characters/${cid}/behavior-patterns/${oid}`, data),
  deleteBehaviorPattern: (cid, oid) => api.delete(`/characters/${cid}/behavior-patterns/${oid}`),
  listEvents: (id)             => api.get(`/characters/${id}/events`),
  createEvent: (id, data)      => api.post(`/characters/${id}/events`, data),
  deleteEvent: (cid, eid)      => api.delete(`/characters/${cid}/events/${eid}`),
}

// ── Relationships ───────────────────────────────────────────────────────────
export const relationshipApi = {
  listAll:  ()                 => api.get('/characters/relationships/all'),
  create:   (data)             => api.post('/characters/relationships/', data),
  update:   (id, data)         => api.put(`/characters/relationships/${id}`, data),
  delete:   (id)               => api.delete(`/characters/relationships/${id}`),
  analyze:  (id)               => api.get(`/characters/relationships/${id}/analyze`),
}

// ── Chat ────────────────────────────────────────────────────────────────────
export const chatApi = {
  listConversations: ()        => api.get('/chat/conversations'),
  createConversation: (data)   => api.post('/chat/conversations', data),
  updateConversation: (id, data) => api.patch(`/chat/conversations/${id}`, data),
  deleteConversation: (id)     => api.delete(`/chat/conversations/${id}`),
  getMessages: (id)            => api.get(`/chat/conversations/${id}/messages`),
  getPerspectives: (id)        => api.get(`/chat/conversations/${id}/perspectives`),
  createBranch: (cid, mid)     => api.post(`/chat/conversations/${cid}/branch/${mid}`),
  listBranches: (cid)          => api.get(`/chat/conversations/${cid}/branches`),
  switchBranch: (cid, branchId) => api.post(`/chat/conversations/${cid}/switch-branch`, { branch_id: branchId }),
  getEmotionCurve: (cid, name) => api.get(`/chat/conversations/${cid}/emotion-curve/${name}`),
  getEmotionTension: (cid, source, target) => api.get(`/chat/conversations/${cid}/emotion-tension`, { params: { source, target } }),
  getRelationshipTrajectory: (cid, source, target) => api.get(`/chat/conversations/${cid}/relationship-trajectory`, { params: { source, target } }),
  getStates: (cid)             => api.get(`/chat/conversations/${cid}/states`),
  generateAdvice: (cid, limit = 8) => api.post(`/chat/conversations/${cid}/generate-advice`, null, { params: { limit } }),
  predictReaction: (cid, candidate, me, counterpart) => api.post(`/chat/conversations/${cid}/predict`, { candidate, me, counterpart }),
  getPredictionStats: (cid, counterpart = '') => api.get(`/chat/conversations/${cid}/prediction-stats`, { params: counterpart ? { counterpart } : {} }),
  getGoalProgress: (cid)       => api.get(`/chat/conversations/${cid}/goal-progress`),
  refreshGoalProgress: (cid)   => api.post(`/chat/conversations/${cid}/goal-progress/refresh`),
  theoryOfMind: (cid, me, counterpart) => api.post(`/chat/conversations/${cid}/theory-of-mind`, { me, counterpart }),
  quickIngestPreview: (cid, text) => api.post(`/chat/conversations/${cid}/quick-ingest/preview`, { text }),
  quickIngestCommit: (cid, data) => api.post(`/chat/conversations/${cid}/quick-ingest/commit`, data),
  reanalyzeMessage: (id)       => api.post(`/chat/messages/${id}/reanalyze`),
  adviseMessage: (id)          => api.post(`/chat/messages/${id}/advise`),
  critiqueAnalysis: (id)       => api.post(`/chat/messages/${id}/critique-analysis`),
  rollbackConversation: (cid)  => api.post(`/chat/conversations/${cid}/rollback`),
  editMessage: (id, content)   => api.put(`/chat/messages/${id}`, { content }),
  archiveConversation: (cid, data) => api.post(`/chat/conversations/${cid}/archive`, data),
  previewEvidencePack: (cid, data) => api.post(`/chat/conversations/${cid}/evidence-pack`, data),
  listRetrievalTraces: (cid, limit = 20) => api.get(`/chat/conversations/${cid}/retrieval-traces`, { params: { limit } }),
  listDiagnoses: (cid, limit = 50) => api.get(`/chat/conversations/${cid}/diagnoses`, { params: { limit } }),
  listMessageDiagnoses: (mid) => api.get(`/chat/messages/${mid}/diagnoses`),
  diagnoseMessage: (mid) => api.post(`/chat/messages/${mid}/diagnose`),
}

/**
 * SSE 流式发送消息
 * @param {object} payload
 * @param {function} onDelta   - 每个文字片段回调
 * @param {function} onDone    - 完成回调，传入完整结果
 * @param {function} onSaved   - 消息落库回调，传入 { user_message_id, ai_message_id }
 * @param {function} onError   - 错误回调
 */
export async function sendMessageStream(payload, { onDelta, onDone, onSaved, onError, signal }) {
  try {
    const response = await fetch('/api/v1/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })

    // 非 2xx（403 只读会话 / 422 参数错误等）不是 SSE 流，必须显式报错
    if (!response.ok) {
      let message = `请求失败 (${response.status})`
      try {
        const body = await response.json()
        if (body?.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch { /* 忽略响应体解析失败 */ }
      onError?.(message)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (!raw) continue
        try {
          const msg = JSON.parse(raw)
          if (msg.type === 'delta') onDelta?.(msg.text)
          else if (msg.type === 'done') onDone?.(msg.result)
          else if (msg.type === 'saved') onSaved?.(msg)
          else if (msg.type === 'error') onError?.(msg.message)
        } catch { /* 忽略不完整的 SSE 行 */ }
      }
    }
  } catch (err) {
    if (err?.name === 'AbortError') return
    onError?.(err.message)
  }
}

export default api
