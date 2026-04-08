import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

// ── Characters ──────────────────────────────────────────────────────────────
export const characterApi = {
  list: ()                     => api.get('/characters/'),
  get:  (id)                   => api.get(`/characters/${id}`),
  create: (data)               => api.post('/characters/', data),
  update: (id, data)           => api.put(`/characters/${id}`, data),
  delete: (id)                 => api.delete(`/characters/${id}`),
  suggestUpdate: (id)          => api.post(`/characters/${id}/suggest-update`),
  listObservations: (id)       => api.get(`/characters/${id}/observations`),
  reviewObservation: (cid, oid, status) =>
    api.post(`/characters/${cid}/observations/${oid}/review`, { status }),
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
  getMessages: (id)            => api.get(`/chat/conversations/${id}/messages`),
  createBranch: (cid, mid)     => api.post(`/chat/conversations/${cid}/branch/${mid}`),
  getEmotionCurve: (cid, name) => api.get(`/chat/conversations/${cid}/emotion-curve/${name}`),
}

/**
 * SSE 流式发送消息
 * @param {object} payload
 * @param {function} onDelta   - 每个文字片段回调
 * @param {function} onDone    - 完成回调，传入完整结果
 * @param {function} onError   - 错误回调
 */
export async function sendMessageStream(payload, { onDelta, onDone, onError }) {
  try {
    const response = await fetch('/api/v1/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

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
          else if (msg.type === 'error') onError?.(msg.message)
        } catch {}
      }
    }
  } catch (err) {
    onError?.(err.message)
  }
}

export default api
