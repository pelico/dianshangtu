<template>
  <div v-if="project">
    <div class="head mb">
      <span class="name">{{ project.name }}</span>
      <el-tag :type="statusType">{{ statusText }}</el-tag>
      <el-tag v-if="plan" size="small" effect="plain">方案 v{{ plan.revision }} · {{ plan.source === 'ai' ? 'AI 生成' : '用户编辑' }}</el-tag>
      <div class="spacer" />
      <template v-if="plan && !editing">
        <el-button @click="startEdit">编辑方案</el-button>
        <el-button @click="openPrompts">提示词预览</el-button>
        <el-button :loading="planning" @click="replan">重新规划</el-button>
        <el-button type="primary" :disabled="planning" @click="generate">确认方案并生成图片</el-button>
      </template>
      <template v-else-if="editing">
        <el-button @click="editing = false">取消</el-button>
        <el-button type="primary" :loading="savingPlan" @click="savePlan">保存修改（新版本）</el-button>
      </template>
    </div>

    <el-alert v-if="failedJob" type="error" :closable="false" show-icon class="mb"
      title="规划任务失败" :description="failedJob.error" />

    <div class="refs mb">
      <div class="refs-title">参考图（第一张为主参考）</div>
      <el-image v-for="r in project.refs" :key="r.id" :src="r.url"
        fit="cover" class="ref-img" :preview-src-list="[r.url]" hide-on-click-modal />
    </div>

    <template v-if="plan">
      <el-card shadow="never" class="mb">
        <template #header><b>商品锚点</b>（会注入每张出图提示词，保证商品一致）</template>
        <p class="anchor">{{ plan.plan.product.anchor }}</p>
        <div v-if="plan.plan.product.selling_points?.length">
          <el-tag v-for="s in plan.plan.product.selling_points" :key="s" size="small" class="mr">{{ s }}</el-tag>
        </div>
      </el-card>

      <el-card shadow="never" class="mb">
        <template #header><b>整体设计规范</b></template>
        <template v-if="!editing">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="风格">{{ plan.plan.design_spec.style }}</el-descriptions-item>
            <el-descriptions-item label="配色">{{ plan.plan.design_spec.palette }}</el-descriptions-item>
            <el-descriptions-item label="布光">{{ plan.plan.design_spec.lighting }}</el-descriptions-item>
            <el-descriptions-item label="文案语言">{{ plan.plan.design_spec.copy_language }}</el-descriptions-item>
          </el-descriptions>
        </template>
        <template v-else>
          <el-row :gutter="10">
            <el-col :span="12"><el-form-item label="风格"><el-input v-model="editPlan.design_spec.style" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="配色"><el-input v-model="editPlan.design_spec.palette" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="布光"><el-input v-model="editPlan.design_spec.lighting" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="文案语言"><el-input v-model="editPlan.design_spec.copy_language" /></el-form-item></el-col>
          </el-row>
        </template>
      </el-card>

      <div v-if="editing" class="mb">
        <el-button size="small" @click="addModule">+ 添加模块</el-button>
      </div>

      <el-row :gutter="14">
        <el-col v-for="(m, idx) in displayModules" :key="m.id" :span="editing ? 12 : 8" class="mb">
          <el-card shadow="never" class="module">
            <template #header>
              <template v-if="!editing">
                <b>{{ m.title_cn }}</b><el-tag size="small" class="mr-l">{{ m.role }}</el-tag>
              </template>
              <template v-else>
                <div class="edit-head">
                  <el-input v-model="m.title_cn" size="small" style="width: 130px" />
                  <el-tag size="small">{{ m.id }}</el-tag>
                  <span class="spacer" />
                  <el-button size="small" text type="danger" @click="removeModule(idx)">删除</el-button>
                </div>
              </template>
            </template>
            <template v-if="!editing">
              <div class="headline">{{ m.headline }}</div>
              <div class="subline">{{ m.subline }}</div>
              <el-divider style="margin: 10px 0" />
              <p><b>场景：</b>{{ m.scene }}</p>
              <p><b>姿态：</b>{{ m.product_pose }}</p>
              <p><b>构图：</b>{{ m.composition }}（文案区：{{ m.text_side }}）</p>
              <p><b>画面：</b>{{ m.visual_description }}</p>
            </template>
            <template v-else>
              <el-form label-width="60px" size="small" label-position="left">
                <el-form-item label="标题"><el-input v-model="m.headline" /></el-form-item>
                <el-form-item label="副题"><el-input v-model="m.subline" /></el-form-item>
                <el-form-item label="角色">
                  <el-select v-model="m.role" size="small" style="width: 140px">
                    <el-option v-for="r in roles" :key="r" :label="r" :value="r" />
                  </el-select>
                  <span class="mr-l">文案区</span>
                  <el-select v-model="m.text_side" size="small" style="width: 80px">
                    <el-option label="左" value="left" /><el-option label="右" value="right" />
                  </el-select>
                </el-form-item>
                <el-form-item label="场景"><el-input v-model="m.scene" /></el-form-item>
                <el-form-item label="姿态"><el-input v-model="m.product_pose" /></el-form-item>
                <el-form-item label="目标"><el-input v-model="m.photo_goal" /></el-form-item>
                <el-form-item label="画面"><el-input v-model="m.visual_description" type="textarea" :rows="2" /></el-form-item>
                <el-form-item label="构图"><el-input v-model="m.composition" type="textarea" :rows="2" /></el-form-item>
              </el-form>
            </template>
          </el-card>
        </el-col>
      </el-row>
    </template>
    <el-empty v-else-if="!planning && !failedJob" description="尚未生成方案" />

    <el-drawer v-model="promptsVisible" title="编译后出图提示词" size="45%">
      <div v-for="p in prompts" :key="p.module_id" class="mb">
        <b>{{ p.title_cn }}</b> <el-tag size="small">{{ p.headline }}</el-tag>
        <pre class="prompt-pre">{{ p.prompt }}</pre>
      </div>
    </el-drawer>
  </div>
  <el-skeleton v-else :rows="6" animated />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id
const project = ref(null)
const plan = ref(null)
const planning = ref(false)
const promptsVisible = ref(false)
const prompts = ref([])
const editing = ref(false)
const editPlan = ref(null)
const savingPlan = ref(false)
const roles = ['hero', 'feature', 'fit', 'scene', 'lifestyle']
let es = null

const STATUS = {
  created: ['info', '待规划'], planning: ['warning', 'AI 规划中'],
  planned: ['success', '方案已就绪'], generating: ['warning', '出图中'],
  done: ['success', '已完成'],
}
const statusType = computed(() => (STATUS[project.value?.status] || ['info'])[0])
const statusText = computed(() => (STATUS[project.value?.status] || ['未知'])[1])
const failedJob = computed(() => project.value?.jobs?.find(j => j.status === 'failed'))
const displayModules = computed(() => editing.value ? editPlan.value.modules : (plan.value?.plan?.modules || []))

async function loadAll() {
  const [p, planResp] = await Promise.all([
    api.get(`/projects/${projectId}`),
    api.get(`/projects/${projectId}/plan`).catch(() => null),
  ])
  project.value = p.data
  plan.value = planResp?.data || null
  planning.value = p.data.status === 'planning'
}

let lastSig = ''
function listen() {
  es = new EventSource(`/api/projects/${projectId}/events`)
  es.onmessage = (ev) => {
    const snap = JSON.parse(ev.data)
    const sig = JSON.stringify([snap.project_status, snap.plan_revision,
      snap.jobs.map(j => `${j.id}:${j.status}`)])
    if (sig !== lastSig) {
      lastSig = sig
      loadAll()
    }
  }
}

function startEdit() {
  editPlan.value = JSON.parse(JSON.stringify(plan.value.plan))
  editing.value = true
}

function addModule() {
  const n = editPlan.value.modules.length + 1
  editPlan.value.modules.push({
    id: `m${Date.now().toString(36)}${n}`, title_cn: `新模块${n}`, role: 'feature',
    scene: '', product_pose: '', photo_goal: '', visual_description: '',
    composition: '', text_side: 'right', headline: '', subline: '',
  })
}

function removeModule(idx) {
  editPlan.value.modules.splice(idx, 1)
}

async function savePlan() {
  savingPlan.value = true
  try {
    await api.put(`/projects/${projectId}/plan`, { plan: editPlan.value })
    ElMessage.success('已保存为新方案版本')
    editing.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally { savingPlan.value = false }
}

async function openPrompts() {
  try {
    prompts.value = (await api.get(`/projects/${projectId}/prompts`)).data
    promptsVisible.value = true
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '获取提示词失败')
  }
}

async function generate() {
  try {
    await api.post(`/projects/${projectId}/generate`, {})
    ElMessage.success('出图任务已全部提交')
    router.push(`/projects/${projectId}/results`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}

async function replan() {
  try {
    await api.post(`/projects/${projectId}/plan`)
    planning.value = true
    ElMessage.success('已重新触发规划')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}

onMounted(() => { loadAll(); listen() })
onBeforeUnmount(() => es?.close())
</script>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.name { font-size: 18px; font-weight: 600; }
.spacer { flex: 1; }
.refs { display: flex; gap: 8px; flex-wrap: wrap; }
.refs-title { width: 100%; font-size: 13px; color: var(--el-text-color-secondary); }
.ref-img { width: 88px; height: 88px; border-radius: 6px; border: 1px solid var(--el-border-color); }
.module { height: 100%; }
.module p { margin: 4px 0; font-size: 13px; color: var(--el-text-color-regular); }
.headline { font-size: 17px; font-weight: 700; letter-spacing: .5px; }
.subline { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 2px; }
.edit-head { display: flex; align-items: center; gap: 6px; }
.edit-head .spacer { flex: 1; }
.mr { margin-right: 6px; }
.mr-l { margin-left: 8px; }
.anchor { white-space: pre-wrap; margin: 0 0 8px; }
.prompt-pre { white-space: pre-wrap; font-size: 12px; margin: 6px 0 0;
  max-height: 260px; overflow: auto; background: var(--el-fill-color-light);
  padding: 10px; border-radius: 6px; }
.mb { margin-bottom: 14px; }
</style>
