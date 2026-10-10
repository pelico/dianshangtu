import { createRouter, createWebHistory } from 'vue-router'
import SettingsView from './views/SettingsView.vue'
import NewProjectView from './views/NewProjectView.vue'
import PlanView from './views/PlanView.vue'
import ResultsView from './views/ResultsView.vue'
import HistoryView from './views/HistoryView.vue'
import PresetsView from './views/PresetsView.vue'
import BrandView from './views/BrandView.vue'
import StatsView from './views/StatsView.vue'
import PlaceholderView from './views/PlaceholderView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/new' },
    { path: '/new', component: NewProjectView, meta: { title: '新建项目' } },
    { path: '/projects/:id/plan', component: PlanView, meta: { title: '方案' } },
    { path: '/projects/:id/results', component: ResultsView, meta: { title: '结果' } },
    { path: '/presets', component: PresetsView, meta: { title: '预设管理' } },
    { path: '/brand-profiles', component: BrandView, meta: { title: '品牌档案' } },
    { path: '/settings', component: SettingsView, meta: { title: '设置' } },
    { path: '/history', component: HistoryView, meta: { title: '历史与成本' } },
    { path: '/stats', component: StatsView, meta: { title: '成本统计' } },
  ],
})
