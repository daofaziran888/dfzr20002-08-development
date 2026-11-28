import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'
import BoothPipelineView from '@/views/BoothPipelineView.vue'
import QuotaDashboardView from '@/views/QuotaDashboardView.vue'
import PowerReceiptView from '@/views/PowerReceiptView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/pipeline', name: 'pipeline', component: BoothPipelineView },
    { path: '/dashboard', name: 'dashboard', component: QuotaDashboardView },
    { path: '/power-receipts', name: 'power-receipts', component: PowerReceiptView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router