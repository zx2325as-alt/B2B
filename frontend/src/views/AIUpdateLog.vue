<template>
  <div class="update-layout">
    <div class="update-sidebar card">
      <div class="sidebar-title">AI更新记录</div>
      <select class="input" v-model.number="selectedCharId">
        <option :value="0">请选择角色</option>
        <option v-for="char in characters" :key="char.id" :value="char.id">{{ char.name }}</option>
      </select>
      <div v-if="summary.total" class="summary-block">
        <div class="summary-item">
          <span>总更新</span>
          <strong>{{ summary.total }}</strong>
        </div>
        <div class="summary-item">
          <span>已自动应用</span>
          <strong>{{ summary.approved }}</strong>
        </div>
        <div class="summary-item">
          <span>待确认</span>
          <strong>{{ summary.pending }}</strong>
        </div>
      </div>
      <button class="btn btn-ghost" @click="goBack">返回角色管理</button>
    </div>

    <div class="update-main">
      <div v-if="!selectedCharId" class="empty-state card">
        <div class="empty-title">选择角色查看结构化变更日志</div>
        <div class="empty-desc">按模块查看来源、依据、置信度、变更类型与自动应用状态。</div>
      </div>

      <template v-else>
        <div class="page-header">
          <div>
            <div class="page-title">{{ activeCharName }} 的 AI 更新记录</div>
            <div class="page-desc">主页面只保留结果概览，这里负责完整展示每次 AI 自动更新的结构化变化。</div>
          </div>
        </div>

        <div v-for="module in moduleOrder" :key="module" class="module-section card">
          <div class="module-header">
            <div class="module-title">{{ module }}</div>
            <span class="tag">{{ grouped[module]?.length || 0 }} 项</span>
          </div>
          <div v-if="!(grouped[module] || []).length" class="empty-desc">暂无该模块更新</div>
          <div v-else class="update-list">
            <div v-for="item in grouped[module]" :key="item.id" class="update-item">
              <div class="update-top">
                <div>
                  <div class="update-name">{{ item.category ? `${item.category}：${item.title}` : item.title }}</div>
                  <div class="update-meta">
                    <span>来源：{{ item.source }}</span>
                    <span>置信度：{{ formatConfidence(item.confidence) }}</span>
                    <span>类型：{{ item.change_type }}</span>
                  </div>
                </div>
                <span class="tag" :class="item.status === 'approved' ? 'green' : item.status === 'pending' ? 'amber' : 'red'">
                  {{ item.status === 'approved' ? '已自动应用' : item.status === 'pending' ? '待确认' : '已忽略' }}
                </span>
              </div>
              <div v-if="item.old_value || item.new_value" class="update-diff">
                <span>{{ item.old_value || '—' }}</span>
                <span>→</span>
                <span>{{ item.new_value || '—' }}</span>
              </div>
              <div class="update-detail">依据：{{ item.evidence || '暂无' }}</div>
              <div v-if="item.trigger" class="update-detail">触发条件：{{ item.trigger }}</div>
              <div v-if="item.example" class="update-detail">示例：{{ item.example }}</div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { characterApi } from '../api/index.js'

const route = useRoute()
const router = useRouter()
const characters = ref([])
const selectedCharId = ref(Number(route.query.charId || 0))
const grouped = ref({})
const summary = ref({ total: 0, approved: 0, pending: 0 })
const moduleOrder = ['基础信息', '人格模型', '行为模式', '核心动机', '核心弱点', '说话风格', '关系网络', '事件时间线']

const activeCharName = computed(() => characters.value.find(item => item.id === selectedCharId.value)?.name || '角色')

function formatConfidence(value) {
  return Number(value || 0).toFixed(2)
}

async function loadCharacters() {
  const res = await characterApi.list()
  characters.value = res.data || []
  if (!selectedCharId.value && characters.value.length) {
    selectedCharId.value = Number(route.query.charId || characters.value[0].id)
  }
}

async function loadUpdateLog() {
  if (!selectedCharId.value) {
    grouped.value = {}
    summary.value = { total: 0, approved: 0, pending: 0 }
    return
  }
  const res = await characterApi.getAiUpdateLog(selectedCharId.value)
  grouped.value = res.data?.groups || {}
  summary.value = res.data?.summary || { total: 0, approved: 0, pending: 0 }
}

function goBack() {
  router.push({ path: '/admin', query: selectedCharId.value ? { charId: selectedCharId.value } : {} })
}

watch(selectedCharId, async (value) => {
  const query = value ? { charId: value } : {}
  router.replace({ path: '/ai-updates', query })
  await loadUpdateLog()
})

onMounted(async () => {
  await loadCharacters()
  await loadUpdateLog()
})
</script>

<style scoped>
.update-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  height: 100%;
  padding: 16px;
  overflow: auto;
}
.update-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: fit-content;
  padding: 16px;
}
.sidebar-title {
  font-size: 16px;
  font-weight: 700;
}
.summary-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.summary-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-secondary);
}
.update-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}
.page-desc,
.empty-desc,
.update-detail,
.update-meta {
  font-size: 12px;
  color: var(--text-secondary);
}
.empty-state {
  padding: 28px;
}
.empty-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.module-section {
  padding: 16px;
}
.module-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.module-title {
  font-size: 15px;
  font-weight: 700;
}
.update-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.update-item {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-soft);
}
.update-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.update-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.update-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.update-diff {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 10px 0 6px;
  font-size: 13px;
  color: var(--text-primary);
}
@media (max-width: 1100px) {
  .update-layout {
    grid-template-columns: 1fr;
  }
}
</style>
