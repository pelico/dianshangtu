<template>
  <div v-if="stats">
    <el-row :gutter="14" class="mb">
      <el-col :span="8">
        <el-card shadow="never">
          <el-statistic title="产出资产总数" :value="stats.total.assets" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <el-statistic title="累计成本（¥，按设置页单价估算）" :value="stats.total.cost" :precision="2" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>质检分布</template>
          <div class="qa-line" v-for="q in stats.qa_status" :key="q.qa_status">
            <el-tag size="small" :type="tagType(q.qa_status)" class="mr">{{ q.qa_status || '未检' }}</el-tag>
            {{ q.n }} 张
          </div>
          <div v-if="!stats.qa_status.length" class="hint">暂无</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="mb">
      <template #header>按模型角色</template>
      <el-table :data="stats.by_role" size="small">
        <el-table-column prop="role" label="角色" min-width="160" />
        <el-table-column prop="n" label="数量" width="90" />
        <el-table-column label="成本（¥）" width="140">
          <template #default="{ row }">{{ (row.c || 0).toFixed(4) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-row :gutter="14">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>按项目</template>
          <el-table :data="stats.by_project" size="small">
            <el-table-column prop="name" label="项目" min-width="160" />
            <el-table-column prop="n" label="资产" width="80" />
            <el-table-column label="成本（¥）" width="120">
              <template #default="{ row }">{{ (row.c || 0).toFixed(4) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>按日期（近 30 天）</template>
          <el-table :data="stats.by_day" size="small">
            <el-table-column prop="d" label="日期" min-width="120" />
            <el-table-column prop="n" label="资产" width="80" />
            <el-table-column label="成本（¥）" width="120">
              <template #default="{ row }">{{ (row.c || 0).toFixed(4) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
    <div class="hint mt">单价在「设置 → 角色→模型映射」里配置（unit_price）；成本为估算值，随设置变动，历史记录按当时单价累计。</div>
  </div>
  <el-skeleton v-else :rows="6" animated />
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../api'

const stats = ref(null)

function tagType(s) {
  return { pass: 'success', approved: 'success', needs_review: 'danger', fail: 'danger' }[s] || 'info'
}

onMounted(async () => {
  const { data } = await api.get('/stats/cost')
  stats.value = data
})
</script>

<style scoped>
.mb { margin-bottom: 14px; }
.mt { margin-top: 10px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.qa-line { font-size: 13px; margin-bottom: 6px; }
.mr { margin-right: 6px; }
</style>
