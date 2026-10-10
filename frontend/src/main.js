import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(ElementPlus, { locale: zhCn })
app.use(router)
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}
app.mount('#app')
