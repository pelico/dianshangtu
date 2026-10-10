<template>
  <div v-if="settings.loaded" class="settings">
    <el-alert
      v-if="!settings.connection.base_url || !settings.connection.has_api_key"
      type="warning" :closable="false" show-icon class="mb"
      title="尚未配置网关地址或 API Key——配置并测试通过后才能触发规划与出图"
    />

    <el-card shadow="never" class="mb">
      <template #header><b>网关连接</b>（OpenAI 兼容接口）</template>
      <el-form label-width="110px" max-width="640px">
        <el-form-item label="Base URL">
          <el-input v-model="baseUrl" placeholder="https://your-gateway/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="apiKey" type="password" show-password autocomplete="new-password"
            :placeholder="settings.connection.has_api_key ? '已保存——留空则不修改' : 'sk-...'"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="mb">
      <template #header>
        <div class="card-head">
          <b>角色 → 模型映射</b>
          <span class="hint">每个角色独立配置模型、调用方式、超时与并发；点行首箭头可为该角色配置独立的 Base URL / API Key（留空使用全局）</span>
        </div>
      </template>
      <el-table :data="roleRows" border>
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div class="role-conn">
              <el-input v-model="row.cfg.base_url"
                placeholder="独立 Base URL，留空则使用全局网关">
                <template #prepend>Base URL</template>
              </el-input>
              <el-input v-model="roleApiKeys[row.role]" type="password" show-password
                autocomplete="new-password"
                :placeholder="row.cfg.has_api_key ? '已保存独立 Key——留空则不修改' : '独立 API Key，留空则使用全局'" />
              <el-button v-if="row.cfg.has_api_key" size="small" text type="danger"
                @click="clearRoleKey(row.role)">清除独立 Key（回退全局）</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="130">
          <template #default="{ row }">{{ ROLE_LABELS[row.role] }}</template>
        </el-table-column>
        <el-table-column label="模型名" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.cfg.model" placeholder="网关暴露的模型名" />
          </template>
        </el-table-column>
        <el-table-column label="调用方式" width="150">
          <template #default="{ row }">
            <el-select v-model="row.cfg.mode">
              <el-option label="chat（聊天出图）" value="chat" />
              <el-option label="edits（图像编辑）" value="edits" />
              <el-option label="generations（文生图）" value="generations" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="原生尺寸" width="140">
          <template #default="{ row }">
            <el-input v-model="row.cfg.size" placeholder="如 1536x1024" />
          </template>
        </el-table-column>
        <el-table-column label="超时(s)" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.cfg.timeout_s" :min="10" :max="1800" controls-position="right" style="width: 100px" />
          </template>
        </el-table-column>
        <el-table-column label="并发" width="110">
          <template #default="{ row }">
            <el-input-number v-model="row.cfg.concurrency" :min="1" :max="8" controls-position="right" style="width: 90px" />
          </template>
        </el-table-column>
        <el-table-column label="单价(≈/次)" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.cfg.unit_price" :min="0" :step="0.01" controls-position="right" style="width: 100px" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div class="actions">
      <el-button type="primary" :loading="settings.saving" @click="save">保存设置</el-button>
      <el-button :loading="settings.testing" @click="testAll">测试全部连接</el-button>
    </div>

    <el-card v-if="settings.testResults.length" shadow="never" class="mb">
      <template #header><b>连接测试结果</b></template>
      <el-alert
        v-for="r in settings.testResults" :key="r.role" class="mb"
        :type="r.ok ? 'success' : 'error'" :closable="false" show-icon
        :title="`${ROLE_LABELS[r.role]} — ${r.ok ? '通过' : '失败'}（${r.elapsed_s}s）`"
        :description="r.detail"
      />
    </el-card>
  </div>
  <el-skeleton v-else :rows="6" animated />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ROLE_LABELS, loadSettings, saveSettings, settings, testConnection } from '../store'

const baseUrl = ref('')
const apiKey = ref('')
const roleApiKeys = ref({})     // 角色级独立 Key（仅本次输入，保存后清空）
const clearKeyFlags = ref({})   // 标记清除独立 Key

const roleRows = computed(() =>
  Object.entries(settings.roles).map(([role, cfg]) => ({ role, cfg }))
)

onMounted(async () => {
  await loadSettings()
  baseUrl.value = settings.connection.base_url
})

async function save() {
  const roles = {}
  for (const { role, cfg } of roleRows.value) {
    roles[role] = { ...cfg, api_key: roleApiKeys.value[role] || '' }
    if (clearKeyFlags.value[role]) roles[role].clear_api_key = true
  }
  await saveSettings({ baseUrl: baseUrl.value, apiKey: apiKey.value, roles })
  apiKey.value = ''
  roleApiKeys.value = {}
  clearKeyFlags.value = {}
  ElMessage.success('已保存')
}

function clearRoleKey(role) {
  clearKeyFlags.value[role] = true
  ElMessage.info(`${ROLE_LABELS[role]} 将清除独立 Key，保存后回退全局`)
}

async function testAll() {
  const results = await testConnection()
  const failed = results.filter(r => !r.ok).length
  if (results.every(r => r.ok)) ElMessage.success('全部角色连接正常')
  else ElMessage.warning(`${results.length - failed}/${results.length} 通过，详见下方结果`)
}
</script>

<style scoped>
.settings { max-width: 1080px; }
.mb { margin-bottom: 14px; }
.card-head { display: flex; align-items: baseline; gap: 12px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.actions { margin: 16px 0; }
.role-conn { display: flex; flex-direction: column; gap: 8px; padding: 4px 12px; max-width: 640px; }
</style>
