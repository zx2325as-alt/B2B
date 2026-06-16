import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatApi, sendMessageStream } from '../api/index.js'
import { toast } from '../utils/notify.js'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref([])
  const activeConvId = ref(null)
  const messages = ref([])          // messages for active conversation
  const perspectives = ref({})      // message_id -> [perspective...] 多视角分析
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
    try {
      const pres = await chatApi.getPerspectives(convId)
      perspectives.value = pres.data || {}
    } catch {
      perspectives.value = {}
    }
  }

  async function sendMessage({ speaker, content, characterId, receiverName, activeCharacters, predictionId = null, adoptedConsequence = null, adoptedLabel = null }) {
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
    // 真实对话分析器：只乐观插入「我手动输入的这句」，不再有 AI 模拟的对方回复气泡。
    // 发送其实是"分析这句话"——分析完 reload，对方/自己的消息会带上洞察‖行动。
    messages.value.push({
      id: tempId,
      role: 'user',
      character_name: speaker,
      receiver_name: receiverName || '',
      content,
      _analyzing: true,
      created_at: new Date().toISOString(),
    })

    let hadError = false

    await sendMessageStream(
      {
        conversation_id: activeConvId.value,
        speaker,
        content,
        character_id: characterId || null,
        receiver_name: receiverName || null,
        active_characters: activeCharacters,
        prediction_id: predictionId || null,
        adopted_consequence: adoptedConsequence || null,
        adopted_label: adoptedLabel || null,
      },
      {
        signal: streamController.value.signal,
        onDelta: () => {},          // 不再有流式回复
        onDone: () => {},
        onError: (err) => {
          hadError = true
          toast.error(`分析失败：${err}`)
          const um = messages.value.find(m => m.id === tempId)
          if (um) um._analyzing = false
        },
      }
    )

    // 出错时保留乐观消息，避免 reload 后"消息凭空消失"
    if (activeConvId.value && !hadError) {
      await loadMessages(activeConvId.value)
    }
    streaming.value = false
    streamBuffer.value = ''
    streamController.value = null
    return null
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
    await loadConversations()
    await loadMessages(activeConvId.value)
  }

  async function switchBranch(branchId) {
    if (!activeConvId.value) return
    await chatApi.switchBranch(activeConvId.value, branchId || null)
    await loadConversations()
    await loadMessages(activeConvId.value)
  }

  async function saveParticipants(participants) {
    if (!activeConvId.value) return
    const res = await chatApi.updateConversation(activeConvId.value, { participants })
    const idx = conversations.value.findIndex(c => c.id === activeConvId.value)
    if (idx >= 0) conversations.value[idx] = { ...conversations.value[idx], ...res.data }
  }

  return {
    conversations, activeConvId, messages, perspectives, streaming, streamBuffer, messageTree,
    loadConversations, newConversation, deleteConversation, loadMessages, sendMessage,
    createBranch, switchBranch, saveParticipants, cancelStreaming,
  }
})
