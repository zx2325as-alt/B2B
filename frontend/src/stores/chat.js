import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatApi, sendMessageStream } from '../api/index.js'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref([])
  const activeConvId = ref(null)
  const messages = ref([])          // messages for active conversation
  const streaming = ref(false)
  const streamBuffer = ref('')      // in-progress streamed text
  const streamController = ref(null)

  // Branch tree: parent_id → [children]
  const messageTree = computed(() => {
    const tree = {}
    for (const m of messages.value) {
      const pid = m.parent_id ?? 'root'
      if (!tree[pid]) tree[pid] = []
      tree[pid].push(m)
    }
    return tree
  })

  async function loadConversations() {
    const res = await chatApi.listConversations()
    conversations.value = res.data
  }

  async function newConversation(title = '新对话', scenario = 'general') {
    const res = await chatApi.createConversation({ title, scenario })
    conversations.value.unshift(res.data)
    activeConvId.value = res.data.id
    messages.value = []
    return res.data
  }

  async function deleteConversation(convId) {
    await chatApi.deleteConversation(convId)
    conversations.value = conversations.value.filter(c => c.id !== convId)
  }

  async function loadMessages(convId) {
    activeConvId.value = convId
    const res = await chatApi.getMessages(convId)
    messages.value = res.data
  }

  async function sendMessage({ speaker, content, characterId, activeCharacters }) {
    if (streaming.value && streamController.value) {
      streamController.value.abort()
      streaming.value = false
      streamBuffer.value = ''
    }
    if (!activeConvId.value) await newConversation()
    streaming.value = true
    streamBuffer.value = ''
    streamController.value = new AbortController()

    // Optimistic user message
    const tempId = Date.now()
    messages.value.push({
      id: tempId,
      role: 'user',
      character_name: speaker,
      content,
      created_at: new Date().toISOString(),
    })

    // Placeholder AI message
    const aiPlaceholderId = tempId + 1
    messages.value.push({
      id: aiPlaceholderId,
      role: 'assistant',
      character_name: 'AI分析',
      content: '',
      _streaming: true,
      created_at: new Date().toISOString(),
    })

    let finalResult = null

    await sendMessageStream(
      {
        conversation_id: activeConvId.value,
        speaker,
        content,
        character_id: characterId || null,
        active_characters: activeCharacters,
      },
      {
        signal: streamController.value.signal,
        onDelta: (text) => {
          streamBuffer.value += text
          const aiMsg = messages.value.find(m => m.id === aiPlaceholderId)
          if (aiMsg) aiMsg.content = streamBuffer.value
        },
        onDone: (result) => {
          finalResult = result
          const aiMsg = messages.value.find(m => m.id === aiPlaceholderId)
          if (aiMsg) {
            aiMsg.content = result.reply || streamBuffer.value
            aiMsg.inner_monologue = result.inner_monologue
            aiMsg.emotion_label = result.emotion_label
            aiMsg.emotion_score = result.emotion_score
            aiMsg.subtext = result.subtext
            aiMsg.psychological_tag = result.psychological_tag
            aiMsg._streaming = false
          }
        },
        onError: (err) => {
          const aiMsg = messages.value.find(m => m.id === aiPlaceholderId)
          if (aiMsg) {
            aiMsg.content = `[分析出错: ${err}]`
            aiMsg._streaming = false
            aiMsg._error = true
          }
        },
      }
    )

    if (activeConvId.value) {
      await loadMessages(activeConvId.value)
    }
    streaming.value = false
    streamBuffer.value = ''
    streamController.value = null
    return finalResult
  }

  function cancelStreaming() {
    if (streamController.value) {
      streamController.value.abort()
      streamController.value = null
    }
    streaming.value = false
    streamBuffer.value = ''
  }

  async function createBranch(messageId) {
    if (!activeConvId.value) return
    await chatApi.createBranch(activeConvId.value, messageId)
    // Truncate messages to up to branch point
    const idx = messages.value.findIndex(m => m.id === messageId)
    if (idx >= 0) messages.value = messages.value.slice(0, idx + 1)
  }

  return {
    conversations, activeConvId, messages, streaming, streamBuffer, messageTree,
    loadConversations, newConversation, deleteConversation, loadMessages, sendMessage, createBranch, cancelStreaming,
  }
})
