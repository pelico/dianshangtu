// 轻量全局状态：Vue3 reactive，不引入 Pinia（技术栈决策：纯 JS 精简版）
import { reactive } from 'vue'
import api from './api'

export const ROLE_ORDER = ['planner', 'qa_vlm', 'image_main', 'image_alt', 'video']
export const ROLE_LABELS = {
  planner: '规划器 (LLM)',
  qa_vlm: '质检 VLM',
  image_main: '出图主模型',
  image_alt: '出图备选',
  video: '视频 (后期)',
}

export const settings = reactive({
  loaded: false,
  connection: { base_url: '', has_api_key: false },
  roles: {},
  testing: false,
  testResults: [],
  saving: false,
})

export async function loadSettings() {
  const { data } = await api.get('/settings')
  settings.connection = data.connection
  settings.roles = data.roles
  settings.loaded = true
}

export async function saveSettings({ baseUrl, apiKey, roles }) {
  settings.saving = true
  try {
    const payload = { connection: { base_url: baseUrl } }
    if (apiKey) payload.connection.api_key = apiKey
    if (roles) payload.roles = roles
    const { data } = await api.put('/settings', payload)
    settings.connection = { base_url: data.connection.base_url, has_api_key: data.connection.has_api_key }
    settings.roles = data.roles
    return true
  } finally {
    settings.saving = false
  }
}

export async function testConnection(role) {
  settings.testing = true
  try {
    const { data } = await api.post('/settings/test', role ? { role } : {})
    settings.testResults = data.results
    return data.results
  } finally {
    settings.testing = false
  }
}
