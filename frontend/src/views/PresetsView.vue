<template>
  <el-card shadow="never" class="mb">
    <template #header>
      <div class="head"><b>预设管理</b><span class="hint">工作流即配置：提示词 / 模块库 / 尺寸 / 文字模式 / 质检规则全部可调，保存即新版本</span></div>
    </template>
    <el-select v-model="currentId" style="width: 300px" @change="loadPreset">
      <el-option v-for="p in presets" :key="p.id" :label="`${p.name} (${p.id})`" :value="p.id" />
    </el-select>
  </el-card>

  <el-row v-if="body" :gutter="14">
    <el-col :span="14">
      <el-card shadow="never" class="mb">
        <template #header>
          <div class="head"><b>编辑器</b><el-tag size="small" class="spacer">当前 v{{ currentVersion }}</el-tag>
            <el-button size="small" type="primary" :loading="saving" @click="saveVersion">保存为新版本</el-button>
          </div>
        </template>
        <el-form label-width="110px" size="small">
          <el-form-item label="预设名称"><el-input v-model="body.name" /></el-form-item>
          <el-row>
            <el-col :span="12"><el-form-item label="画布宽"><el-input-number v-model="body.canvas.width" :min="200" :max="4096" style="width: 130px" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="画布高"><el-input-number v-model="body.canvas.height" :min="200" :max="4096" style="width: 130px" /></el-form-item></el-col>
          </el-row>
          <el-row>
            <el-col :span="12"><el-form-item label="文字模式">
              <el-select v-model="body.text.mode" style="width: 160px">
                <el-option label="model 模型直出" value="model" />
                <el-option label="blank 留白后贴" value="blank_then_overlay" />
              </el-select>
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="出图方式">
              <el-select v-model="body.image.mode" style="width: 160px">
                <el-option label="edits 图像编辑" value="edits" />
                <el-option label="chat 聊天出图" value="chat" />
                <el-option label="generations 文生图" value="generations" />
              </el-select>
            </el-form-item></el-col>
          </el-row>
          <el-row>
            <el-col :span="12"><el-form-item label="生成尺寸"><el-input v-model="body.image.gen_size" placeholder="如 1536x1024" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="自动重试"><el-input-number v-model="body.qa.max_auto_retries" :min="0" :max="5" style="width: 130px" /></el-form-item></el-col>
          </el-row>
          <el-form-item label="规划提示词">
            <el-input v-model="body.planner.system_prompt" type="textarea" :rows="10" />
          </el-form-item>
          <el-form-item label="出图模板">
            <el-input v-model="body.image.template" type="textarea" :rows="10" />
          </el-form-item>
          <el-form-item label="负面约束">
            <el-input v-model="body.image.negative" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="模块库">
            <el-input v-model="moduleLibraryStr" type="textarea" :rows="4" />
          </el-form-item>
        </el-form>
      </el-card>
    </el-col>

    <el-col :span="10">
      <el-card shadow="never" class="mb">
        <template #header><b>版本历史</b></template>
        <el-table :data="versions" size="small" @row-click="viewVersion">
          <el-table-column prop="version" label="版本" width="70" />
          <el-table-column prop="created_at" label="保存时间" min-width="150" />
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click.stop="viewVersion(row)">查看</el-button>
              <el-button size="small" text type="warning" :disabled="row.version === currentVersion"
                @click.stop="rollback(row.version)">回滚</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="hint" style="margin-top: 8px">回滚 = 以旧版本内容创建新版本；旧版本只读保留。点击行可查看旧版内容。</div>
      </el-card>

      <el-card shadow="never">
        <template #header><b>用样例商品试跑一张</b></template>
        <el-upload :auto-upload="false" :limit="1" accept="image/*" v-model:file-list="testFile" drag>
          <div class="el-upload__text">拖一张样例商品图，或<em>点击选择</em></div>
        </el-upload>
        <el-input v-model="testBrief" placeholder="卖点说明（可选）" style="margin: 10px 0" />
        <el-button type="primary" :loading="testing" :disabled="!testFile.length" @click="runTest">
          试跑（规划 + 出图，约 1–2 分钟）
        </el-button>
        <el-alert v-if="testError" type="error" :closable="false" class="mt" :title="testError" />
        <div v-if="testResult">
          <el-image :src="testResult.image_url" fit="contain" class="test-img"
            :preview-src-list="[testResult.image_url]" hide-on-click-modal />
          <div class="hint">规划 {{ testResult.plan_elapsed_s }}s · 出图 {{ testResult.gen_elapsed_s }}s ·
            模块「{{ testResult.module?.title_cn }}」{{ testResult.module?.headline }}</div>
          <el-collapse>
            <el-collapse-item title="查看提示词">
              <pre class="prompt-pre">{{ testResult.prompt }}</pre>
            </el-collapse-item>
            <el-collapse-item title="查看方案 JSON">
              <pre class="prompt-pre">{{ JSON.stringify(testResult.plan, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const presets = ref([])
const currentId = ref('aplus_banner')
const currentVersion = ref(null)
const body = ref(null)
const moduleLibraryStr = ref('[]')
const versions = ref([])
const saving = ref(false)

const testFile = ref([])
const testBrief = ref('')
const testing = ref(false)
const testResult = ref(null)
const testError = ref('')

async function loadList() {
  presets.value = (await api.get('/presets')).data
}

async function loadPreset() {
  const data = (await api.get(`/presets/${currentId.value}/versions`)).data
  versions.value = data
  currentVersion.value = data[0]?.version
  const v = (await api.get(`/presets/${currentId.value}/versions/${currentVersion.value}`)).data
  body.value = v.body
  moduleLibraryStr.value = JSON.stringify(v.body.module_library || [], null, 1)
  testResult.value = null
  testError.value = ''
}

async function saveVersion() {
  let lib
  try { lib = JSON.parse(moduleLibraryStr.value) } catch { ElMessage.error('模块库不是合法 JSON'); return }
  const payload = JSON.parse(JSON.stringify(body.value))
  payload.module_library = lib
  saving.value = true
  try {
    await api.post(`/presets/${currentId.value}/versions`, { body: payload })
    ElMessage.success('已保存为新版本')
    await loadList()
    await loadPreset()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}

async function viewVersion(row) {
  const v = (await api.get(`/presets/${currentId.value}/versions/${row.version}`)).data
  body.value = v.body
  moduleLibraryStr.value = JSON.stringify(v.body.module_library || [], null, 1)
  ElMessage.info(`正在查看 v${row.version}（保存后会成为新版本）`)
}

async function rollback(version) {
  await api.post(`/presets/${currentId.value}/rollback`, { version })
  ElMessage.success(`已回滚：v${version} 内容已存为新版本`)
  await loadList()
  await loadPreset()
}

async function runTest() {
  testing.value = true
  testResult.value = null
  testError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', testFile.value[0].raw)
    fd.append('brief', testBrief.value)
    const { data } = await api.post(`/presets/${currentId.value}/test-run`, fd)
    // 轮询 job
    const deadline = Date.now() + 300000
    while (Date.now() < deadline) {
      const j = (await api.get(`/jobs/${data.job_id}`)).data
      if (j.status === 'done') { testResult.value = j.payload.result; break }
      if (j.status === 'failed') { testError.value = j.error; break }
      await new Promise(r => setTimeout(r, 2000))
    }
    if (!testResult.value && !testError.value) testError.value = '试跑超时'
  } catch (e) {
    testError.value = e.response?.data?.detail || '试跑失败'
  } finally { testing.value = false }
}

onMounted(async () => { await loadList(); await loadPreset() })
</script>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; }
.head .spacer { flex: 1; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.mb { margin-bottom: 14px; }
.mt { margin-top: 10px; }
.test-img { width: 100%; max-height: 260px; margin: 10px 0; }
.prompt-pre { white-space: pre-wrap; font-size: 12px; margin: 0;
  max-height: 300px; overflow: auto; background: var(--el-fill-color-light);
  padding: 10px; border-radius: 6px; }
</style>
