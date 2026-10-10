<template>
  <div v-if="project">
    <div class="head mb">
      <span class="name">{{ project.name }}</span>
      <el-tag>{{ STATUS_TEXT[project.status] || project.status }}</el-tag>
      <div class="spacer" />
      <el-button :disabled="!assets.length" tag="a"
        :href="`/api/projects/${projectId}/export.zip`">批量下载 zip</el-button>
      <el-button type="primary" :loading="generating" :disabled="!plan" @click="regenerate">
        重新生成全部
      </el-button>
    </div>

    <el-alert v-if="failedJobs.length" type="error" :closable="false" show-icon class="mb"
      :title="`${failedJobs.length} 个出图任务失败`">
      <div v-for="j in failedJobs" :key="j.id" class="err-line">{{ j.error }}</div>
    </el-alert>

    <el-empty v-if="!assets.length && !failedJobs.length && !generating"
      description="还没有产出图片——回到方案页点击「确认方案并生成图片」" />

    <div v-for="group in grouped" :key="group.module_id" class="mb">
      <div class="group-title">
        {{ group.title_cn || group.module_id }}
        <el-tag size="small" class="mr-l">v{{ group.assets.length }}</el-tag>
      </div>
      <el-row :gutter="14">
        <el-col v-for="a in group.assets" :key="a.id" :span="12" class="mb">
          <el-card shadow="never" body-style="padding: 10px">
            <el-image :src="a.url" fit="contain" class="asset-img"
              :preview-src-list="[a.url, a.raw_url]" hide-on-click-modal />
            <div class="meta">
              <el-tag size="small" type="info" class="mr">{{ a.model }}</el-tag>
              <el-tag size="small" type="info" class="mr">{{ a.mode }}</el-tag>
              <span>{{ a.width }}×{{ a.height }} · {{ a.elapsed_s }}s</span>
              <el-tag v-if="a.parent_asset_id" size="small" type="warning" class="mr">衍生自 #{{ a.parent_asset_id }}</el-tag>
              <el-tag v-if="a.prompt_edited" size="small" type="warning" class="mr">已改提示词</el-tag>
              <span class="spacer" />
              <el-tag size="small" class="mr">¥{{ (a.cost_estimate || 0).toFixed(2) }}</el-tag>
              <el-tooltip v-if="qaIssues(a).length" placement="top">
                <template #content>
                  <div v-for="(i, k) in qaIssues(a)" :key="k" class="qa-issue">{{ i }}</div>
                </template>
                <el-tag size="small" :type="qaTagType(a.qa_status)">
                  QA {{ QA_TEXT[a.qa_status] || a.qa_status || '未检' }}
                </el-tag>
              </el-tooltip>
              <el-tag v-else size="small" :type="qaTagType(a.qa_status)">
                QA {{ QA_TEXT[a.qa_status] || a.qa_status || '未检' }}
              </el-tag>
              <el-button v-if="a.qa_status === 'needs_review'" size="small" type="warning"
                @click="approve(a)">人工放行</el-button>
              <el-button size="small" text type="primary" @click="openRedo(a)">重出</el-button>
              <a :href="`${a.url}`" :download="`${group.module_id}_${a.id}.png`">
                <el-button size="small" text type="primary">下载</el-button>
              </a>
            </div>
            <el-collapse class="prompt-collapse">
              <el-collapse-item title="查看提示词">
                <pre class="prompt-pre">{{ a.prompt_text }}</pre>
              </el-collapse-item>
            </el-collapse>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <el-dialog v-model="redoVisible" title="单图重出（产生新版本，不覆盖）" width="640px">
      <el-form label-width="90px">
        <el-form-item label="模型角色">
          <el-select v-model="redoForm.model_ref" style="width: 240px">
            <el-option label="出图主模型 (image_main)" value="image_main" />
            <el-option label="出图备选 (image_alt)" value="image_alt" />
          </el-select>
        </el-form-item>
        <el-form-item label="提示词">
          <el-input v-model="redoForm.prompt_text" type="textarea" :rows="10" />
          <div class="hint">留空则按方案重新编译；修改后重出的图会标记「已改提示词」</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="redoVisible = false">取消</el-button>
        <el-button type="primary" :loading="redoing" @click="submitRedo">重出</el-button>
      </template>
    </el-dialog>

    <el-divider content-position="left">视频（图生视频，M6）</el-divider>

    <el-card shadow="never" body-style="padding: 14px" class="mb">
      <div class="video-head">
        <el-button size="small" :loading="scriptLoading" @click="planVideo">生成镜头脚本</el-button>
        <span v-if="script?.created_at" class="hint">脚本生成于 {{ script.created_at }}（UTC）</span>
      </div>
      <el-table v-if="script?.body?.shots?.length" :data="script.body.shots" size="small" class="mt">
        <el-table-column prop="index" label="#" width="50" />
        <el-table-column prop="description" label="镜头" min-width="200" />
        <el-table-column prop="motion" label="运动" min-width="140" />
        <el-table-column prop="duration_s" label="时长(s)" width="80" />
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-select v-model="videoModule[row.index]" size="small" placeholder="选模块" style="width: 110px; margin-right: 6px">
              <el-option v-for="g in grouped" :key="g.module_id" :value="g.module_id"
                :label="g.title_cn || g.module_id" />
            </el-select>
            <el-button size="small" type="primary" :loading="videoLoading[row.index]"
              @click="genVideo(row)">生成</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="hint mt">还没有脚本。生成脚本后按镜头出视频：每个镜头取对应模块最新质检通过的图作首帧。</div>
    </el-card>

    <div v-for="v in videos" :key="v.id" class="mb">
      <el-card shadow="never" body-style="padding: 10px">
        <video :src="v.url" controls class="video-player" />
        <div class="meta">
          <el-tag size="small" type="info">{{ v.model }}</el-tag>
          <span>模块 {{ v.module_id }} · 镜头 {{ shotOf(v) }} · {{ v.elapsed_s }}s · ¥{{ (v.cost_estimate || 0).toFixed(2) }}</span>
          <span class="spacer" />
          <a :href="v.url" :download="`video_${v.id}.mp4`">
            <el-button size="small" text type="primary">下载</el-button>
          </a>
        </div>
      </el-card>
    </div>
  </div>
  <el-skeleton v-else :rows="6" animated />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const route = useRoute()
const projectId = route.params.id
const project = ref(null)
const plan = ref(null)
const assets = ref([])
const generating = ref(false)
let es = null

const STATUS_TEXT = {
  created: '待规划', planning: '规划中', planned: '已规划',
  generating: '出图中', done: '已完成',
}

const grouped = computed(() => {
  const byModule = {}
  for (const a of assets.value) (byModule[a.module_id] ||= []).push(a)
  const titles = {}
  for (const m of plan.value?.plan?.modules || []) titles[m.id] = m.title_cn
  return Object.entries(byModule).map(([module_id, list]) => ({
    module_id, title_cn: titles[module_id], assets: list,
  }))
})

const failedJobs = computed(() => project.value?.jobs?.filter(j => j.status === 'failed') || [])

function withUrls(list) {
  return list.map(a => ({ ...a }))
}

async function loadAll() {
  const [p, planResp, a] = await Promise.all([
    api.get(`/projects/${projectId}`),
    api.get(`/projects/${projectId}/plan`).catch(() => null),
    api.get(`/assets?project_id=${projectId}`),
  ])
  project.value = p.data
  plan.value = planResp?.data || null
  assets.value = withUrls(a.data)
  generating.value = p.data.status === 'generating'
}

let lastSig = ''
function listen() {
  es = new EventSource(`/api/projects/${projectId}/events`)
  es.onmessage = (ev) => {
    const snap = JSON.parse(ev.data)
    const sig = JSON.stringify([snap.project_status, snap.plan_revision,
      snap.jobs.map(j => `${j.id}:${j.status}`)])
    if (sig !== lastSig) { lastSig = sig; loadAll(); loadVideoData() }
  }
}

async function regenerate() {
  generating.value = true
  try {
    await api.post(`/projects/${projectId}/generate`, {})
    ElMessage.success('已触发重新生成')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
    generating.value = false
  }
}

const redoVisible = ref(false)
const redoing = ref(false)
const redoForm = reactive({ assetId: null, model_ref: 'image_main', prompt_text: '' })

function openRedo(a) {
  redoForm.assetId = a.id
  redoForm.model_ref = a.model === 'img-alt' || a.mode === 'alt' ? 'image_alt' : 'image_main'
  redoForm.prompt_text = a.prompt_text || ''
  redoVisible.value = true
}

async function submitRedo() {
  redoing.value = true
  try {
    await api.post(`/assets/${redoForm.assetId}/regenerate`, {
      prompt_text: redoForm.prompt_text,
      model_ref: redoForm.model_ref,
    })
    ElMessage.success('重出任务已提交')
    redoVisible.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  } finally { redoing.value = false }
}

// ---------- M4：QA 展示与人工放行 ----------
const QA_TEXT = { pass: '通过', fail: '未通过', needs_review: '待放行', approved: '已放行' }

function qaTagType(s) {
  return { pass: 'success', approved: 'success', needs_review: 'danger', fail: 'danger' }[s] || 'info'
}

function qaIssues(a) {
  try { return JSON.parse(a.qa_json || '{}')?.issues || [] } catch { return [] }
}

async function approve(a) {
  try {
    await api.post(`/assets/${a.id}/approve`, { note: '' })
    ElMessage.success('已放行')
    loadAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '放行失败')
  }
}

// ---------- M6：视频 ----------
const script = ref(null)
const scriptLoading = ref(false)
const videos = ref([])
const videoModule = reactive({})
const videoLoading = reactive({})

async function loadVideoData() {
  const [s, v] = await Promise.all([
    api.get(`/projects/${projectId}/video/script`).catch(() => null),
    api.get(`/assets?project_id=${projectId}&kind=video`).catch(() => null),
  ])
  script.value = s?.data || null
  videos.value = v?.data || []
}

async function planVideo() {
  scriptLoading.value = true
  try {
    await api.post(`/projects/${projectId}/video/plan`)
    ElMessage.success('镜头脚本生成中')
    const timer = setInterval(async () => {
      await loadVideoData()
      if (script.value) { clearInterval(timer); scriptLoading.value = false }
    }, 2000)
    setTimeout(() => { clearInterval(timer); scriptLoading.value = false }, 120000)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
    scriptLoading.value = false
  }
}

function shotOf(v) {
  try { return JSON.parse(v.params_json || '{}')?.shot?.index ?? '-' } catch { return '-' }
}

async function genVideo(shot) {
  const mid = videoModule[shot.index]
  if (!mid) { ElMessage.warning('先选模块（用该模块最新质检通过的图作首帧）'); return }
  videoLoading[shot.index] = true
  try {
    await api.post(`/projects/${projectId}/video/generate`, { module_id: mid, shot_index: shot.index })
    ElMessage.success('视频生成任务已提交（长任务，完成后出现在下方）')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  } finally { videoLoading[shot.index] = false }
}

onMounted(() => { loadAll(); loadVideoData(); listen() })
onBeforeUnmount(() => es?.close())
</script>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
.name { font-size: 18px; font-weight: 600; }
.spacer { flex: 1; }
.group-title { font-size: 15px; font-weight: 600; margin-bottom: 10px; }
.asset-img { width: 100%; height: 240px; }
.meta { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-size: 12px;
  color: var(--el-text-color-secondary); }
.mr { margin-right: 4px; }
.mr-l { margin-left: 6px; }
.prompt-collapse :deep(.el-collapse-item__header) { font-size: 12px; height: 32px; }
.prompt-pre { white-space: pre-wrap; font-size: 12px; margin: 0;
  max-height: 220px; overflow: auto; }
.err-line { font-size: 12px; }
.mb { margin-bottom: 14px; }
.mt { margin-top: 10px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.video-head { display: flex; align-items: center; gap: 12px; }
.video-player { width: 100%; max-height: 320px; background: #000; }
.qa-issue { max-width: 320px; white-space: normal; }
</style>
