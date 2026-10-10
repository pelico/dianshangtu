<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">电商 AI 出图工作台</div>
      <el-menu router :default-active="$route.path" class="menu">
        <el-menu-item index="/new">
          <el-icon><Upload /></el-icon><span>新建项目</span>
        </el-menu-item>
        <el-menu-item index="/presets">
          <el-icon><Setting /></el-icon><span>预设管理</span>
        </el-menu-item>
        <el-menu-item index="/brand-profiles">
          <el-icon><Collection /></el-icon><span>品牌档案</span>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><DataAnalysis /></el-icon><span>历史项目</span>
        </el-menu-item>
        <el-menu-item index="/stats">
          <el-icon><TrendCharts /></el-icon><span>成本统计</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Tools /></el-icon><span>设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="main">
      <el-page-header v-if="$route.meta.title && $route.path !== '/new'" :title="'返回'" @click="$router.back()">
        <template #content>
          <span class="page-title">{{ $route.meta.title }}</span>
        </template>
      </el-page-header>
      <router-view />
    </el-main>
  </el-container>
</template>

<style>
html, body, #app { height: 100%; margin: 0; }
.layout { height: 100%; }
.aside { border-right: 1px solid var(--el-border-color-light); background: var(--el-bg-color); }
.logo { font-weight: 600; padding: 18px 20px; font-size: 15px; color: var(--el-text-color-primary); }
.menu { border-right: none; }
.main { background: var(--el-bg-color-page); }
.page-title { font-weight: 600; }
</style>
