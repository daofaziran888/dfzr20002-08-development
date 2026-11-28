<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>用电核验与调试放行</h2>
        <p class="page-desc">
          用电核验回执固化设计负荷与回路额定功率结论，影音调试放行回执按回路占用额度；
          一个回路同一时段只能有一个有效放行，失效额度不能再办新试音，已开始试音允许收尾复核。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="refresh-power" type="button" @click="refreshAll">
          刷新回执与占用
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    <p v-if="infoMessage" class="info-text">{{ infoMessage }}</p>

    <!-- 设计负荷变更模拟 -->
    <section class="dashboard-card">
      <h4>设计负荷变更（触发核验结论重算）</h4>
      <form class="filter-bar" @submit.prevent="onLoadChange">
        <label class="filter-item">
          <span>设计方案ID</span>
          <input v-model="designId" data-testid="design-id" placeholder="如 1" />
        </label>
        <label class="filter-item">
          <span>新设计负荷(kW)</span>
          <input v-model="newLoad" data-testid="new-load" placeholder="如 70" />
        </label>
        <button class="btn primary" data-testid="apply-load-change" type="submit">应用负荷变更</button>
      </form>
      <p v-if="loadResult" class="info-text">
        {{ loadResult.booth_no }}：{{ loadResult.old_load_kw }}kW → {{ loadResult.new_load_kw }}kW，
        即时核对{{ loadResult.quota_ok ? '通过' : '超限' }}；
        失效回执 {{ loadResult.invalidated_receipts.map((r) => r.receipt_no).join('、') || '无' }}，
        占用中放行 {{ loadResult.occupying_releases.map((r) => r.receipt_no).join('、') || '无' }}
        <template v-if="loadResult.new_work_blocked">；旧占用未结清，新试音已被冻结</template>
      </p>
    </section>

    <!-- 按原编号反查 -->
    <section class="dashboard-card">
      <h4>按原编号查核验回执（审核员负荷明细反查）</h4>
      <form class="filter-bar" @submit.prevent="onLookup">
        <label class="filter-item">
          <span>回执编号</span>
          <input v-model="lookupNo" data-testid="lookup-no" placeholder="如 PWR-0001" />
        </label>
        <button class="btn" data-testid="lookup-btn" type="submit">查询当时负荷明细</button>
      </form>
      <div v-if="lookedUp" class="receipt-box">
        <p>
          <strong>{{ lookedUp.receipt_no }}</strong>
          ｜状态：{{ lookedUp.status }}
          ｜结论：{{ lookedUp.verification }}
          ｜设计负荷：{{ lookedUp.design_load_kw }}kW
          ｜回路总额定：{{ lookedUp.total_circuit_power_kw }}kW
        </p>
        <ul class="detail-list">
          <li v-for="d in lookedUp.load_detail" :key="d.circuit_id">
            {{ d.circuit_id }}：{{ d.power }}kW（{{ d.status }}）
          </li>
        </ul>
        <p v-if="lookedUp.reason" class="error-text">失效原因：{{ lookedUp.reason }}</p>
      </div>
    </section>

    <!-- 用电核验回执 -->
    <section class="dashboard-card">
      <h4>用电核验回执（{{ receipts.length }}）</h4>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>回执编号</th><th>展位</th><th>回路</th><th>状态</th><th>核验结论</th>
            <th>设计负荷</th><th>回路额定</th><th>总功率</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in receipts" :key="r.id" :data-status="r.status">
            <td>{{ r.receipt_no }}</td>
            <td>{{ r.booth_no }}</td>
            <td>{{ r.circuit_no }}</td>
            <td :class="r.status === '有效' ? 'text-success' : 'text-danger'">{{ r.status }}</td>
            <td>{{ r.verification }}</td>
            <td>{{ r.design_load_kw }}kW</td>
            <td>{{ r.rated_power_kw }}kW</td>
            <td>{{ r.total_circuit_power_kw }}kW</td>
            <td class="row-actions">
              <button class="link" type="button" @click="onReissue(r.id)">从新单重新核验</button>
            </td>
          </tr>
          <tr v-if="!receipts.length">
            <td colspan="9" class="empty-state">暂无核验回执，请先在「用电配置」对已核验回路执行「出具核验回执」</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 调试放行回执 -->
    <section class="dashboard-card">
      <h4>调试放行回执（{{ releases.length }}）</h4>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>放行编号</th><th>关联核验回执</th><th>回路</th><th>影音设备</th><th>状态</th>
            <th>完成记录</th><th>复核</th><th>复核人</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rel in releases" :key="rel.id" :data-status="rel.status">
            <td>{{ rel.receipt_no }}</td>
            <td>{{ rel.power_receipt_no }}</td>
            <td>{{ rel.circuit_no }}</td>
            <td>{{ rel.av_name || '—' }}</td>
            <td :class="rel.status === '占用中' ? 'text-warn' : 'text-success'">{{ rel.status }}</td>
            <td>{{ rel.completion || '未登记' }}</td>
            <td :class="rel.review_required ? 'text-danger' : ''">
              {{ rel.review_required ? '需复核' : '无需' }}
            </td>
            <td>{{ rel.reviewer || '—' }}</td>
            <td class="row-actions">
              <button
                v-if="rel.status === '占用中' && !rel.completion"
                class="link"
                type="button"
                @click="onCompletion(rel.id)"
              >
                登记试音完成
              </button>
              <button
                v-if="rel.status === '占用中'"
                class="link"
                type="button"
                @click="onSettle(rel.id)"
              >
                结清并释放
              </button>
            </td>
          </tr>
          <tr v-if="!releases.length">
            <td colspan="9" class="empty-state">暂无放行回执；在「影音布置」执行调试设备即自动占用回路额度</td>
          </tr>
        </tbody>
      </table>

      <form class="filter-bar" @submit.prevent="onGrant">
        <label class="filter-item">
          <span>从有效回执ID办理新放行</span>
          <input v-model="grantReceiptId" data-testid="grant-receipt-id" placeholder="核验回执 id" />
        </label>
        <label class="filter-item">
          <span>影音设备ID(可选)</span>
          <input v-model="grantAvId" data-testid="grant-av-id" placeholder="audio_visual id" />
        </label>
        <button class="btn primary" data-testid="grant-btn" type="submit">办理调试放行</button>
      </form>
    </section>

    <!-- 回路占用一致性核对 -->
    <section class="dashboard-card">
      <h4>回路占用一致性核对</h4>
      <form class="filter-bar" @submit.prevent="onOccupancy">
        <label class="filter-item">
          <span>回路编号</span>
          <input v-model="occupancyCircuit" data-testid="occupancy-circuit" placeholder="如 ELEC-A01-1" />
        </label>
        <button class="btn" data-testid="occupancy-btn" type="submit">核对占用状态</button>
      </form>
      <div v-if="occupancy" class="receipt-box">
        <p>
          回执与用电侧占用：
          <strong :class="occupancy.consistent ? 'text-success' : 'text-danger'">
            {{ occupancy.consistent ? '一致' : '不一致' }}
          </strong>
          <span v-if="occupancy.conflict" class="text-danger">（{{ occupancy.conflict }}）</span>
        </p>
        <p>释放状态：{{ occupancy.release_state }}<template v-if="occupancy.released_at">
          ，释放时间 {{ formatTime(occupancy.released_at) }}
        </template></p>
        <p>
          当前有效回执：{{ occupancy.active_receipt?.receipt_no || '无' }}
          ｜占用放行：{{ occupancy.occupying_release?.receipt_no || '无' }}
          ｜可办新单：{{ occupancy.new_work_allowed ? '是' : '否' }}
        </p>
        <p v-if="occupancy.review_required" class="error-text">
          需复核旧记录，复核人：{{ occupancy.reviewer || '值班审核员' }}
        </p>
        <ul v-if="occupancy.review_items.length" class="detail-list">
          <li v-for="item in occupancy.review_items" :key="item.release_no">
            {{ item.release_no }}（{{ item.status }}）复核人 {{ item.reviewer }}：{{ item.note }}
          </li>
        </ul>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  applyDesignLoadChange,
  fetchCircuitOccupancy,
  fetchPowerReceipts,
  fetchReceiptByNo,
  fetchReleases,
  grantRelease,
  reissueReceipt,
  settleRelease,
  submitReleaseCompletion,
} from '@/api/power-client'
import type {
  CircuitOccupancy,
  LoadChangeResult,
  PowerReceipt,
  ReleaseReceipt,
} from '@/data/exhibition-types'

const receipts = ref<PowerReceipt[]>([])
const releases = ref<ReleaseReceipt[]>([])
const errorMessage = ref('')
const infoMessage = ref('')

const designId = ref('1')
const newLoad = ref('70')
const loadResult = ref<LoadChangeResult | null>(null)

const lookupNo = ref('PWR-0001')
const lookedUp = ref<PowerReceipt | null>(null)

const grantReceiptId = ref('')
const grantAvId = ref('')

const occupancyCircuit = ref('ELEC-A01-1')
const occupancy = ref<CircuitOccupancy | null>(null)

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

async function refreshAll() {
  errorMessage.value = ''
  try {
    const [receiptData, releaseData] = await Promise.all([
      fetchPowerReceipts(),
      fetchReleases(),
    ])
    receipts.value = receiptData.items
    releases.value = releaseData.items
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '回执数据读取失败'
  }
}

async function onLoadChange() {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    loadResult.value = await applyDesignLoadChange(Number(designId.value), Number(newLoad.value))
    await refreshAll()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '负荷变更失败'
  }
}

async function onLookup() {
  errorMessage.value = ''
  try {
    lookedUp.value = await fetchReceiptByNo(lookupNo.value.trim())
  } catch (e) {
    lookedUp.value = null
    errorMessage.value = e instanceof Error ? e.message : '回执查询失败'
  }
}

async function onReissue(id: number) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const result = await reissueReceipt(id)
    infoMessage.value = `已从新单出具回执 ${result.receipt.receipt_no}（状态：${result.receipt.status}）`
    await refreshAll()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '重新核验被拒绝'
  }
}

async function onGrant() {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const avId = grantAvId.value.trim() ? Number(grantAvId.value) : null
    const result = await grantRelease(Number(grantReceiptId.value), avId)
    infoMessage.value = `放行回执 ${result.release.receipt_no} 已办理，占用回路 ${result.release.circuit_no}`
    await refreshAll()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '放行办理被拒绝'
  }
}

async function onCompletion(id: number) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const result = await submitReleaseCompletion(id, '现场提交试音完成记录')
    infoMessage.value = result.release.review_required
      ? `放行 ${result.release.receipt_no} 已登记完成，原额度失效需复核后结清`
      : `放行 ${result.release.receipt_no} 已登记试音完成`
    await refreshAll()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '完成登记失败'
  }
}

async function onSettle(id: number) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const result = await settleRelease(id)
    infoMessage.value = result.release.review_required
      ? `放行 ${result.release.receipt_no} 已结清释放，旧记录仍需 ${result.release.reviewer} 复核`
      : `放行 ${result.release.receipt_no} 已结清并释放回路`
    await refreshAll()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '结清失败'
  }
}

async function onOccupancy() {
  errorMessage.value = ''
  try {
    occupancy.value = await fetchCircuitOccupancy(occupancyCircuit.value.trim())
  } catch (e) {
    occupancy.value = null
    errorMessage.value = e instanceof Error ? e.message : '占用核对失败'
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.dashboard-card {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.dashboard-card h4 { margin: 0 0 12px; color: #333; }
.data-table.compact { font-size: 12px; }
.data-table.compact th, .data-table.compact td { padding: 6px 8px; }
.receipt-box {
  background: #fff; border-radius: 6px; padding: 12px; margin-top: 8px;
  font-size: 13px;
}
.detail-list { margin: 8px 0 0; padding-left: 18px; font-size: 12px; color: #555; }
.info-text { color: #1890ff; font-size: 13px; }
.text-success { color: #52c41a; }
.text-danger { color: #f5222d; }
.text-warn { color: #fa8c16; }
.row-actions { white-space: nowrap; }
</style>
