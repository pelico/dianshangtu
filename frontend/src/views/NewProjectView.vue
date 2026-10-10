<template>
  <div class="new-project">
    <el-card shadow="never" class="mb">
      <template #header><b>商品参考图</b><span class="hint">（多角度，第一张为主参考；jpg/png/webp）</span></template>
      <el-upload
        v-model:file-list="fileList"
        drag multiple list-type="picture-card" :auto-upload="false"
        accept=".jpg,.jpeg,.png,.webp"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽图片到此处，或<em>点击选择</em></div>
      </el-upload>
    </el-card>

    <el-card shadow="never" class="mb">
      <template #header><b>商品信息</b></template>
      <el-form label-width="120px" max-width="720px">
        <el-form-item label="项目名称">
          <el-input v-model="form.name" placeholder="留空自动生成" />
        </el-form-item>
        <el-form-item label="卖点说明">
          <el-input v-model="form.brief" type="textarea" :rows="4"
            placeholder="卖点、约束、目标人群等。规划器只允许使用这里写明的或图中可见的卖点（防不实宣传）" />
        </el-form-item>
        <el-form-item label="预设">
          <el-select v-model="form.preset_id" style="width: 320px">
            <el-option v-for="p in presets" :key="p.id"
              :label="`${p.name} (v${p.latest_version})`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌档案">
          <el-select v-model="form.brand_profile_id" clearable style="width: 320px"
            placeholder="不使用（可选，注入品牌调性/禁用词）">
            <el-option v-for="b in brandProfiles" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="文案语言">
          <el-select v-model="form.copy_language" style="width: 200px">
            <el-option label="English" value="English" />
            <el-option label="中文" value="Chinese" />
          </el-select>
        </el-form-item>
        <el-form-item label="模块数量">
          <el-input-number v-model="form.n_modules" :min="1" :max="12" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-button type="primary" size="large" :loading="submitting" @click="submit">
      创建项目
    </el-button>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const fileList = ref([])
const presets = ref([])
const brandProfiles = ref([])
const submitting = ref(false)
const form = reactive({
  name: '', brief: '', preset_id: 'aplus_banner', brand_profile_id: '',
  copy_language: 'English', n_modules: 5,
})

onMounted(async () => {
  const [p, b] = await Promise.all([api.get('/presets'), api.get('/brand-profiles')])
  presets.value = p.data
  brandProfiles.value = b.data
})

async function submit() {
  if (!fileList.value.length) {
    ElMessage.warning('请先上传至少一张商品参考图')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    for (const f of fileList.value) fd.append('files', f.raw)
    fd.append('name', form.name)
    fd.append('brief', form.brief)
    fd.append('preset_id', form.preset_id)
    fd.append('brand_profile_id', form.brand_profile_id || '')
    fd.append('params_json', JSON.stringify({
      copy_language: form.copy_language, n_modules: form.n_modules,
    }))
    const { data } = await api.post('/projects', fd)
    ElMessage.success('项目已创建，开始 AI 规划')
    router.push(`/projects/${data.id}/plan`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.new-project { max-width: 900px; }
.mb { margin-bottom: 14px; }
.hint { margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
