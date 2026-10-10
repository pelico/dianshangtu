<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <b>品牌档案</b><span class="hint">L2 档案层：编译出图提示词时自动注入（品牌调性/配色/禁用词）</span>
        <el-button type="primary" size="small" class="spacer" @click="openEdit(null)">新建档案</el-button>
      </div>
    </template>
    <el-table :data="profiles" v-loading="loading">
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column label="品牌调性" min-width="160">
        <template #default="{ row }">{{ row.body.brand_tone || '—' }}</template>
      </el-table-column>
      <el-table-column label="品牌配色" width="150">
        <template #default="{ row }">{{ row.body.brand_colors || '—' }}</template>
      </el-table-column>
      <el-table-column label="禁用词" min-width="140">
        <template #default="{ row }">{{
          (row.body.forbidden_words || []).join('、') || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !profiles.length" description="还没有品牌档案" />
  </el-card>

  <el-dialog v-model="dialogVisible" :title="form.id ? '编辑档案' : '新建档案'" width="560px">
    <el-form label-width="90px">
      <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="品牌调性">
        <el-input v-model="form.brand_tone" placeholder="如：极简现代、专业科技质感" />
      </el-form-item>
      <el-form-item label="品牌配色">
        <el-input v-model="form.brand_colors" placeholder="如：#E02424 / #111111 / #007185" />
      </el-form-item>
      <el-form-item label="禁用词">
        <el-input v-model="form.forbidden_words_str" placeholder="逗号分隔，如：cheap, best, waterproof" />
      </el-form-item>
      <el-form-item label="Logo 文字">
        <el-input v-model="form.logo_text" placeholder="固定保留的品牌标识文字（可选）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const profiles = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const form = reactive({ id: null, name: '', brand_tone: '', brand_colors: '', forbidden_words_str: '', logo_text: '' })

async function load() {
  loading.value = true
  try { profiles.value = (await api.get('/brand-profiles')).data } finally { loading.value = false }
}

function openEdit(row) {
  form.id = row?.id || null
  form.name = row?.name || ''
  form.brand_tone = row?.body?.brand_tone || ''
  form.brand_colors = row?.body?.brand_colors || ''
  form.forbidden_words_str = (row?.body?.forbidden_words || []).join(', ')
  form.logo_text = row?.body?.logo_text || ''
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) { ElMessage.warning('请填写名称'); return }
  saving.value = true
  try {
    const body = {
      brand_tone: form.brand_tone, brand_colors: form.brand_colors,
      logo_text: form.logo_text,
      forbidden_words: form.forbidden_words_str.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    }
    if (form.id) await api.put(`/brand-profiles/${form.id}`, { name: form.name, body })
    else await api.post('/brand-profiles', { name: form.name, body })
    ElMessage.success('已保存')
    dialogVisible.value = false
    load()
  } finally { saving.value = false }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除档案「${row.name}」？`, '删除确认', { type: 'warning' })
  await api.delete(`/brand-profiles/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.head { display: flex; align-items: baseline; gap: 10px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); flex: 1; }
</style>
