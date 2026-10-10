<template>
  <el-card shadow="never">
    <template #header><b>项目列表</b></template>
    <el-table :data="projects" v-loading="loading" @row-click="open">
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ref_count" label="参考图" width="80" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="" width="90">
        <template #default="{ row }">
          <el-button size="small" text type="primary">打开方案</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !projects.length" description="还没有项目——去「新建项目」创建第一个" />
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

const router = useRouter()
const projects = ref([])
const loading = ref(false)

const STATUS = {
  created: ['info', '待规划'], planning: ['warning', '规划中'],
  planned: ['success', '已规划'], generating: ['warning', '出图中'],
  done: ['success', '已完成'],
}
const statusType = (s) => (STATUS[s] || ['info'])[0]
const statusText = (s) => (STATUS[s] || [null, s])[1]

onMounted(async () => {
  loading.value = true
  try {
    projects.value = (await api.get('/projects')).data
  } finally {
    loading.value = false
  }
})

function open(row) {
  router.push(`/projects/${row.id}/plan`)
}
</script>
