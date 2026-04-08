import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { characterApi, relationshipApi } from '../api/index.js'

export const useCharacterStore = defineStore('characters', () => {
  const characters = ref([])
  const relationships = ref([])
  const loading = ref(false)
  const selectedId = ref(null)

  const selected = computed(() =>
    characters.value.find(c => c.id === selectedId.value) || null
  )

  const characterMap = computed(() =>
    Object.fromEntries(characters.value.map(c => [c.id, c]))
  )

  async function fetchAll() {
    loading.value = true
    try {
      const [cRes, rRes] = await Promise.all([
        characterApi.list(),
        relationshipApi.listAll(),
      ])
      characters.value = cRes.data
      relationships.value = rRes.data
    } finally {
      loading.value = false
    }
  }

  async function create(data) {
    const res = await characterApi.create(data)
    characters.value.push(res.data)
    return res.data
  }

  async function update(id, data) {
    const res = await characterApi.update(id, data)
    const idx = characters.value.findIndex(c => c.id === id)
    if (idx >= 0) characters.value[idx] = res.data
    return res.data
  }

  async function remove(id) {
    await characterApi.delete(id)
    characters.value = characters.value.filter(c => c.id !== id)
    relationships.value = relationships.value.filter(
      r => r.source_id !== id && r.target_id !== id
    )
    if (selectedId.value === id) selectedId.value = null
  }

  async function createRelationship(data) {
    const res = await relationshipApi.create(data)
    relationships.value.push(res.data)
    return res.data
  }

  async function updateRelationship(id, data) {
    const res = await relationshipApi.update(id, data)
    const idx = relationships.value.findIndex(r => r.id === id)
    if (idx >= 0) relationships.value[idx] = res.data
    return res.data
  }

  async function deleteRelationship(id) {
    await relationshipApi.delete(id)
    relationships.value = relationships.value.filter(r => r.id !== id)
  }

  function select(id) { selectedId.value = id }

  return {
    characters, relationships, loading, selectedId, selected, characterMap,
    fetchAll, create, update, remove,
    createRelationship, updateRelationship, deleteRelationship,
    select,
  }
})
