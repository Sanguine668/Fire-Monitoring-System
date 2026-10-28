<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const router = useRouter()
const { realtime } = useRealtime()
const loading = ref(false)
const info = ref({ agents: [], metrics: {}, settings: {}, pipeline: [] })
const cameras = ref([])
const sample = ref(null)
const recent = ref([])
const paused = ref(false)
const selectedCameraId = ref(null)
let timer = null

// ── 证据抽屉：每个 Agent 展示一张自家眼睛拍到的实拍图 ─────────
const drawerVisible = ref(false)
const activeAgent = ref(null)
const evidenceMeta = ref(null)
const evidenceMetaError = ref(false)
const imageError = ref(false)
const imageTs = ref(Date.now())
let evidenceTimer = null

const EVIDENCE_KIND = {
  perception: 'detect',
  farfield: 'tiles',
  temporal: 'films',
  verification: 'verify'
}

const EVIDENCE_HINT = {
  perception: '对着画面点一处真实火焰或烟雾，证据图应立刻多出 fire/smoke 细框；移开后框消失。',
  farfield: '到系统设置把切片边长从 640 改成 320 再回来看：网格会变密、片数变多，说明切的是当前真实画面。',
  temporal: '持续制造烟雾 3 秒以上，底部 5 帧缩略图的烟雾分数应连续非零；只闪一下则断续，说明连续帧规则生效。',
  verification: '到系统设置关掉「告警二次复核」，再触发同类告警，告警列表的「已复核」标签会消失，复核统计也不再增长。',
  decision: '到系统设置把 fire 阈值临时调到 0.9，同一处火源的风险指针应明显回落、不再生成告警；调回后再复现。'
}

const latest = computed(() => sample.value)
const metrics = computed(() => info.value.metrics || {})
const risk = computed(() => latest.value?.risk ?? 0)
const riskColor = computed(() => (risk.value >= 80 ? '#e5484d' : risk.value >= 45 ? '#e6a23c' : '#23a06b'))

const statusText = computed(() => {
  const status = latest.value?.status
  return status === 'critical' ? '严重告警' : status === 'warning' ? '预警' : status === 'normal' ? '正常' : '等待数据'
})

const statusType = computed(() => {
  const status = latest.value?.status
  return status === 'critical' ? 'danger' : status === 'warning' ? 'warning' : 'success'
})

const verifyText = computed(() => {
  const v = latest.value?.agents?.verification
  if (!v) return '等待数据'
  if (!v.active) return '已关闭'
  if (v.passed === null) {
    const total = v.history?.total || 0
    if (v.triggered) return '复核中'
    return total ? `待触发 · 累计 ${total} 次` : '待触发'
  }
  return v.passed ? `通过 · ${Math.round(v.confidence * 100)}%` : '已拦截'
})

const activeStage = computed(() => {
  const t = latest.value?.agents
  if (!t) return ''
  if (t.verification.triggered) return 'verification'
  if (t.decision.alarm) return 'decision'
  if (t.temporal.smoke_streak > 0) return 'temporal'
  if (t.farfield.active) return 'farfield'
  return t.perception.active ? 'perception' : ''
})

const STATE_META = {
  running: { label: '运行中', color: '#23a06b', ink: '#1b7d53' },
  processing: { label: '处理中', color: '#e6a23c', ink: '#b9781d' },
  alert: { label: '告警', color: '#e5484d', ink: '#c52f34' },
  idle: { label: '待命', color: '#c0c4cc', ink: '#7b8494' },
  off: { label: '已关闭', color: '#c0c4cc', ink: '#7b8494' }
}

const ACTIVE_ACTIONS = {
  perception: '整图烟火检测',
  farfield: '切片扫描',
  temporal: '连续帧确认',
  verification: '局部复核',
  decision: '风险分级'
}

function agentStatus(key, t) {
  if (!t) return STATE_META.idle
  if (key === 'perception') {
    return t.perception.active ? STATE_META.running : STATE_META.idle
  }
  if (key === 'farfield') {
    if (t.farfield.enabled === false) return STATE_META.off
    return t.farfield.active ? STATE_META.processing : STATE_META.running
  }
  if (key === 'temporal') {
    return t.temporal.smoke_streak > 0 ? STATE_META.processing : STATE_META.running
  }
  if (key === 'verification') {
    const v = t.verification
    if (!v.active) return STATE_META.off
    if (!v.triggered) return STATE_META.idle
    if (v.passed === null) return STATE_META.processing
    return v.passed ? STATE_META.running : STATE_META.alert
  }
  const d = t.decision
  return d.alarm || d.status === 'critical' || d.status === 'warning' ? STATE_META.alert : STATE_META.running
}

function agentDoing(key, t) {
  if (!t) return '等待检测数据'
  if (key === 'perception') {
    const p = t.perception
    if (!p.active) return '感知已停止 · 等待画面恢复'
    return `整图检测 · 检出 ${p.objects} 个候选（最高置信度 ${Number(p.top_confidence ?? 0).toFixed(2)}）`
  }
  if (key === 'farfield') {
    const f = t.farfield
    return f.active
      ? `切片扫描中 · ${f.tile_size} 瓦片`
      : `整图模式 · 保留 ${f.held} 个切片结果`
  }
  if (key === 'temporal') {
    const m = t.temporal
    return `烟雾连续 ${m.smoke_streak}/${m.required} 帧 · 冷却 ${m.cooldown}s`
  }
  if (key === 'verification') {
    const v = t.verification
    const h = v.history || {}
    if (!v.active) return '复核已关闭'
    if (v.triggered || v.passed !== null) {
      if (v.passed === null) return '局部复核中'
      const confidence = v.confidence === null || v.confidence === undefined ? '—' : `${Math.round(v.confidence * 100)}%`
      return v.passed ? `复核通过 · ${confidence}` : '复核拦截'
    }
    // 复核只在告警触发帧执行，平时采样抓不到；用累计统计说明它一直在工作
    if (h.total) {
      const last = h.last_passed === null || h.last_passed === undefined
        ? ''
        : ` · 最近${h.last_passed ? '通过' : '拦截'} ${Math.round((h.last_confidence || 0) * 100)}%（${(h.last_ts || '').slice(11)}）`
      return `累计复核 ${h.total} 次（通过 ${h.passed} · 拦截 ${h.blocked}）${last}`
    }
    return '待触发（当前无告警）'
  }
  const d = t.decision
  return d.alarm ? `已生成告警 · 风险 ${d.risk}` : `状态 ${d.status} · 风险 ${d.risk}`
}

function agentMetric(key, t) {
  if (key === 'farfield') {
    if (!t) return { value: '—', caption: '瓦片边长 / 保留数' }
    if (t.farfield.enabled === false) return { value: '关', caption: '切片扫描已关闭' }
    return t.farfield.active
      ? { value: `${t.farfield.tile_size}`, caption: '瓦片边长 (px)' }
      : { value: `${t.farfield.held}`, caption: '保留切片数' }
  }
  if (!t) {
    const captions = {
      perception: '候选数',
      temporal: '连续烟雾帧',
      verification: '局部复核结果',
      decision: '当前风险分'
    }
    return { value: '—', caption: captions[key] || '主指标' }
  }
  if (key === 'perception') {
    return { value: `${t.perception.objects}`, caption: '候选数' }
  }
  if (key === 'temporal') {
    return { value: `${t.temporal.smoke_streak}/${t.temporal.required}`, caption: '连续烟雾帧' }
  }
  if (key === 'verification') {
    const v = t.verification
    const h = v.history || {}
    if (!v.active) return { value: '关', caption: '复核已关闭' }
    if (v.passed !== null && v.passed !== undefined) {
      return { value: v.passed ? '通过' : '拦截', caption: '本次复核结果' }
    }
    if (h.total) return { value: `${h.total}`, caption: `累计复核（通过 ${h.passed}）` }
    return { value: '—', caption: '尚无告警需复核' }
  }
  return { value: `${t.decision.risk}`, caption: '当前风险分' }
}

const agentCards = computed(() => {
  const t = latest.value?.agents
  return (info.value.agents || []).map((agent, index) => ({
    ...agent,
    index,
    status: agentStatus(agent.key, t),
    doing: agentDoing(agent.key, t),
    metric: agentMetric(agent.key, t),
    isActive: activeStage.value === agent.key
  }))
})

const activeSummary = computed(() => {
  const stage = activeStage.value
  if (!latest.value || !stage) return null
  const agent = info.value.agents.find((item) => item.key === stage)
  if (!agent) return null
  return {
    name: agent.name,
    action: ACTIVE_ACTIONS[stage] || agent.role,
    color: agentStatus(stage, latest.value.agents).ink
  }
})

const metricBlocks = computed(() => [
  { label: '官方 test mAP50', value: pct(metrics.value.map50), note: '验收线 ≥70%' },
  { label: '远景小目标召回', value: pct(metrics.value.farfield_recall), note: `旧模型 ${pct(metrics.value.farfield_old)}` },
  { label: '整图 → 切片召回', value: `${pct(metrics.value.tiling_plain)} → ${pct(metrics.value.tiling_tiled)}`, note: '每 2 秒低频扫描' },
  { label: 'SmokeFire 烟雾召回', value: pct(metrics.value.smokefire_smoke), note: '未参与训练的跨域集' },
  { label: '校准后 fire 误报', value: pct(metrics.value.calibrated_fire_fpr), note: '困难负样本，阈值 0.40' }
])

const timeline = computed(() => {
  const t = latest.value?.agents
  if (!t) return []
  return [
    { key: 'perception', title: '感知 Agent', detail: `检出 ${t.perception.objects} 个候选，最高置信度 ${t.perception.top_confidence}` },
    { key: 'farfield', title: '远场 Agent', detail: t.farfield.enabled === false ? '切片扫描已关闭，走整图模式' : (t.farfield.active ? `执行 ${t.farfield.tile_size} 瓦片扫描` : `整图模式，保留切片结果 ${t.farfield.held} 个`) },
    { key: 'temporal', title: '时序 Agent', detail: `烟雾连续 ${t.temporal.smoke_streak}/${t.temporal.required} 帧，冷却 ${t.temporal.cooldown}s` },
    {
      key: 'verification',
      title: '复核 Agent',
      detail: t.verification.active
        ? t.verification.passed === null
          ? (t.verification.triggered
            ? '局部复核进行中'
            : (t.verification.history?.total ? `未触发（累计已复核 ${t.verification.history.total} 次）` : '未触发（当前无告警）'))
          : t.verification.passed
            ? `局部复核通过，置信度 ${Math.round(t.verification.confidence * 100)}%`
            : '局部复核不通过，已抑制告警'
        : '复核关闭'
    },
    {
      key: 'decision',
      title: '决策 Agent',
      detail: `状态 ${t.decision.status}，风险 ${t.decision.risk}${t.decision.alarm ? '，已生成告警' : ''}`
    }
  ]
})

function pct(value) {
  return value === undefined || value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function cameraName(id) {
  return cameras.value.find((c) => c.id === id)?.name || `视频源 ${id}`
}

function syncSample() {
  if (paused.value) return
  const source = selectedCameraId.value
    ? realtime.traces.filter((trace) => trace.camera_id === selectedCameraId.value)
    : realtime.traces
  sample.value = source[0] || null
  recent.value = source.slice(0, 10)
}

watch(selectedCameraId, () => syncSample())

function togglePause() {
  paused.value = !paused.value
  if (!paused.value) syncSample()
}

const evidenceCameraId = computed(() => selectedCameraId.value || latest.value?.camera_id || null)
const evidenceImageUrl = computed(() => {
  const cameraId = evidenceCameraId.value
  const kind = EVIDENCE_KIND[activeAgent.value?.key]
  if (!cameraId || !kind) return ''
  return `/api/agents/evidence?camera_id=${cameraId}&kind=${kind}&t=${imageTs.value}`
})
const evidenceHint = computed(() => EVIDENCE_HINT[activeAgent.value?.key] || '')
const decisionRisk = computed(() => {
  const value = evidenceMeta.value?.decision?.risk ?? risk.value
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)))
})
const decisionStatus = computed(() => {
  const status = evidenceMeta.value?.decision?.status ?? latest.value?.status
  return status === 'critical' ? '严重告警' : status === 'warning' ? '预警' : status === 'normal' ? '正常' : '等待数据'
})
const decisionTone = computed(() => {
  const status = evidenceMeta.value?.decision?.status ?? latest.value?.status
  return status === 'critical' ? 'critical' : status === 'warning' ? 'warning' : 'normal'
})

const evidenceNumbers = computed(() => {
  const m = evidenceMeta.value
  const key = activeAgent.value?.key
  if (!m) {
    const captions = { perception: '候选数', farfield: '瓦片数', temporal: '连续烟雾帧', verification: '累计复核', decision: '当前风险分' }
    return [
      { label: captions[key] || '主指标', value: '—' },
      { label: '最高置信度', value: '—' },
      { label: '证据帧', value: '—' }
    ]
  }
  if (key === 'perception') {
    return [
      { label: '候选数', value: `${m.perception.objects}` },
      { label: '最高置信度', value: Number(m.perception.top ?? 0).toFixed(2) },
      { label: '可用证据帧', value: `${m.temporal.frames.length}` }
    ]
  }
  if (key === 'farfield') {
    return [
      { label: '瓦片数', value: `${m.farfield.tiles}` },
      { label: '瓦片边长', value: `${m.farfield.tile_size}px` },
      { label: '合并后候选', value: `${m.farfield.held}` }
    ]
  }
  if (key === 'temporal') {
    return [
      { label: '烟雾连续', value: `${m.temporal.streak}/${m.temporal.required}` },
      { label: '告警冷却', value: `${m.temporal.cooldown}s` },
      { label: '留档帧', value: `${m.temporal.frames.length}` }
    ]
  }
  if (key === 'verification') {
    return [
      { label: '累计复核', value: `${m.verification.total}` },
      { label: '通过', value: `${m.verification.passed}` },
      { label: '拦截', value: `${m.verification.blocked}` }
    ]
  }
  return [
    { label: '风险分', value: `${m.decision.risk}` },
    { label: '状态', value: decisionStatus.value },
    { label: '告警', value: m.decision.alarm ? '已生成' : '未触发' }
  ]
})

async function loadEvidence() {
  imageTs.value = Date.now()
  const cameraId = evidenceCameraId.value
  if (!cameraId) {
    evidenceMeta.value = null
    evidenceMetaError.value = true
    return
  }
  try {
    const response = await fetch(`/api/agents/evidence/meta?camera_id=${cameraId}`, { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    evidenceMeta.value = await response.json()
    evidenceMetaError.value = false
  } catch {
    evidenceMeta.value = null
    evidenceMetaError.value = true
  }
}

function openEvidence(card) {
  activeAgent.value = card
  drawerVisible.value = true
  imageError.value = false
  evidenceMeta.value = null
  evidenceMetaError.value = false
  loadEvidence()
  clearInterval(evidenceTimer)
  evidenceTimer = setInterval(loadEvidence, 2000)
}

function stopEvidence() {
  clearInterval(evidenceTimer)
  evidenceTimer = null
}

function goMonitor() {
  drawerVisible.value = false
  router.push('/monitor')
}

watch(evidenceCameraId, () => {
  if (drawerVisible.value) loadEvidence()
})

async function load() {
  loading.value = true
  try {
    const [agentInfo, cameraList] = await Promise.all([api.agents(), api.cameras()])
    info.value = agentInfo
    cameras.value = cameraList
    if (!selectedCameraId.value && cameraList.length) {
      selectedCameraId.value = (cameraList.find((camera) => camera.online) || cameraList[0]).id
    }
  } catch (error) {
    ElMessage.error(`加载智能体信息失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  syncSample()
  timer = setInterval(syncSample, 3000)
})
onUnmounted(() => {
  clearInterval(timer)
  clearInterval(evidenceTimer)
})
</script>

<template>
  <div v-loading="loading" class="agents-page">
    <div class="page-head">
      <div class="head-left">
        <span class="toolbar-hint">感知 → 远场 → 时序 → 复核 → 决策</span>
        <el-select v-model="selectedCameraId" size="small" style="width: 170px" placeholder="选择视频源">
          <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
        </el-select>
      </div>
      <div class="head-actions">
        <el-tag :type="paused ? 'info' : 'success'" effect="dark" size="small">
          {{ paused ? '已暂停' : '实时采样 · 3 秒' }}
        </el-tag>
        <el-button size="small" @click="togglePause">{{ paused ? '继续刷新' : '暂停刷新' }}</el-button>
        <el-button size="small" type="primary" plain @click="router.push('/monitor')">打开实时监控</el-button>
      </div>
    </div>

    <!-- 智能体运行概览：五个独立状态卡 -->
    <div class="agent-overview">
      <div class="agent-summary">
        <span
          class="summary-dot"
          :style="{ background: activeSummary ? activeSummary.color : '#c0c4cc' }"
          aria-hidden="true"
        />
        <span class="summary-copy">
          <template v-if="activeSummary">当前由 <b>{{ activeSummary.name }}</b> 执行{{ activeSummary.action }}</template>
          <template v-else>等待检测数据 · 五个智能体处于待命状态</template>
        </span>
        <span class="summary-meta">
          共 {{ info.agents.length }} 个智能体<template v-if="latest"> · {{ cameraName(latest.camera_id) }}</template>
        </span>
      </div>

      <div class="agent-grid">
        <article
          v-for="card in agentCards"
          :key="card.key"
          class="agent-card"
          :class="{ 'is-active': card.isActive }"
          :style="{ '--state-color': card.status.color, '--state-ink': card.status.ink }"
          role="button"
          tabindex="0"
          :aria-label="`查看 ${card.name} 的实拍证据`"
          @click="openEvidence(card)"
          @keydown.enter="openEvidence(card)"
          @keydown.space.prevent="openEvidence(card)"
        >
          <span class="agent-bar" :class="{ 'is-live': card.isActive }" aria-hidden="true" />
          <div class="agent-card-body">
            <div class="agent-head">
              <span class="agent-index" aria-hidden="true">{{ card.index + 1 }}</span>
              <h3 class="agent-name">{{ card.name }}</h3>
              <span class="agent-status">{{ card.status.label }}</span>
            </div>

            <div class="agent-role">
              <span class="role-label">负责</span>
              <span>{{ card.role }}</span>
            </div>

            <div class="agent-doing">
              <span class="doing-label">本轮正在做</span>
              <p>{{ card.doing }}</p>
            </div>

            <div class="agent-metric">
              <strong>{{ card.metric.value }}</strong>
              <span>{{ card.metric.caption }}</span>
            </div>

            <div class="agent-evidence-hint" aria-hidden="true">
              查看证据 <span>→</span>
            </div>
          </div>
        </article>
      </div>
    </div>

    <!-- 最新轨迹与当前决策：沿用 15 / 9 分栏，保留风险分仪表盘 -->
    <el-row :gutter="16">
      <el-col :span="15">
        <el-card shadow="never" class="trajectory-panel">
          <template #header>
            <div class="panel-head">
              <b>最新决策轨迹</b>
              <span class="sub">当前画面：{{ latest ? cameraName(latest.camera_id) : '等待视频源' }}</span>
            </div>
          </template>

          <div class="evidence">
            <div class="evidence-title">
              本轮执行摘要
              <span>每 3 秒采样一次，避免数字闪烁</span>
            </div>
            <div v-if="timeline.length === 0" class="empty">等待检测数据，请先到「实时监控」打开视频源。</div>
            <div v-for="item in timeline" :key="item.key" class="evidence-row">
              <span class="evidence-dot" />
              <b>{{ item.title }}</b>
              <span>{{ item.detail }}</span>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="9">
        <el-card shadow="never" class="decision-panel">
          <template #header>
            <div class="panel-head">
              <b>当前决策</b>
              <el-tag :type="statusType" size="small">{{ statusText }}</el-tag>
            </div>
          </template>
          <div class="gauge">
            <el-progress type="dashboard" :percentage="risk" :color="riskColor" :width="150">
              <template #default>
                <div class="gauge-value">{{ risk }}</div>
                <div class="gauge-label">风险分</div>
              </template>
            </el-progress>
          </div>
          <div class="decision-meta">
            <span>{{ latest ? cameraName(latest.camera_id) : '—' }}</span>
            <span>{{ latest ? (latest.timestamp || '').slice(11) : '—' }}</span>
            <span>{{ latest ? `${latest.fps ?? '—'} FPS` : '—' }}</span>
          </div>
          <div class="decision-rows">
            <div><span>复核</span><b>{{ verifyText }}</b></div>
            <div><span>告警</span><b>{{ latest?.agents?.decision?.alarm ? '已生成' : '未触发' }}</b></div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <div class="metric-band">
      <div v-for="item in metricBlocks" :key="item.label" class="metric-block">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.note }}</small>
      </div>
    </div>

    <el-card shadow="never" class="recent-panel">
      <template #header>
        <div class="panel-head">
          <b>最近 Agent 轨迹</b>
          <span class="sub">最近 10 条 · 3 秒采样</span>
        </div>
      </template>
      <el-table :data="recent" size="small" empty-text="等待检测数据">
        <el-table-column label="时间" width="112">
          <template #default="{ row }">{{ (row.timestamp || '').slice(11) }}</template>
        </el-table-column>
        <el-table-column label="视频源" min-width="150">
          <template #default="{ row }">{{ cameraName(row.camera_id) }}</template>
        </el-table-column>
        <el-table-column label="感知" width="70">
          <template #default="{ row }">{{ row.objects }}</template>
        </el-table-column>
        <el-table-column label="远场" width="70">
          <template #default="{ row }">{{ row.tiled ? '切片' : '整图' }}</template>
        </el-table-column>
        <el-table-column label="复核" width="82">
          <template #default="{ row }">
            {{ row.agents.verification.passed === null ? '—' : row.agents.verification.passed ? '通过' : '拦截' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'critical' ? 'danger' : row.status === 'warning' ? 'warning' : 'success'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="risk" label="风险" width="64" />
      </el-table>
    </el-card>

    <!-- 证据抽屉：一张该 Agent 自己产出的实拍图 + 三个关键数字 -->
    <el-drawer
      v-model="drawerVisible"
      :title="activeAgent ? `${activeAgent.name} · 实拍证据` : '实拍证据'"
      size="820px"
      class="evidence-drawer"
      @closed="stopEvidence"
    >
      <div v-if="activeAgent" class="evidence-body">
        <div class="evidence-headline">
          <span class="evidence-role">{{ activeAgent.role }}</span>
          <span class="evidence-source">
            {{ evidenceCameraId ? cameraName(evidenceCameraId) : '未选择视频源' }}
          </span>
        </div>

        <div v-if="activeAgent.key !== 'decision'" class="evidence-frame">
          <img
            v-if="evidenceImageUrl"
            :src="evidenceImageUrl"
            :class="{ 'is-failed': imageError }"
            :alt="`${activeAgent.name} 实拍证据`"
            @load="imageError = false"
            @error="imageError = true"
          />
          <div v-if="!evidenceImageUrl || imageError" class="evidence-placeholder">
            <b>暂无证据图</b>
            <p>该视频源还没有可用的证据帧，请先在实时监控里打开它</p>
          </div>
        </div>

        <!-- 决策 Agent 不产出图像，用同一份数值画风险刻度，绝不伪造画面 -->
        <div v-else class="risk-panel">
          <div class="risk-head">
            <span class="risk-value">{{ decisionRisk }}</span>
            <span class="risk-status" :class="`is-${decisionTone}`">{{ decisionStatus }}</span>
          </div>
          <div class="risk-track" role="img" :aria-label="`风险分 ${decisionRisk}，预警线 45，告警线 80`">
            <span class="risk-zone zone-low" />
            <span class="risk-zone zone-mid" />
            <span class="risk-zone zone-high" />
            <span class="risk-mark" style="left: 45%"><i />45</span>
            <span class="risk-mark" style="left: 80%"><i />80</span>
            <span class="risk-pointer" :style="{ left: `${decisionRisk}%` }"><i /></span>
          </div>
          <div class="risk-axis">
            <span>0 正常</span>
            <span>45 预警</span>
            <span>80 告警</span>
            <span>100</span>
          </div>
          <p class="risk-note">决策 Agent 只输出风险数值，不产图像；指针来自 meta.decision.risk，每 2 秒刷新。</p>
        </div>

        <div class="evidence-stats">
          <div v-for="item in evidenceNumbers" :key="item.label" class="evidence-stat">
            <strong>{{ item.value }}</strong>
            <span>{{ item.label }}</span>
          </div>
        </div>

        <p v-if="evidenceMetaError" class="evidence-warn">
          数值面板暂时取不到（视频源可能未运行或正在重启），画面每 2 秒仍会自动重试。
        </p>

        <div class="evidence-hint">
          <span class="hint-label">怎么现场验证</span>
          <p>{{ evidenceHint }}</p>
        </div>

        <div class="evidence-footer">
          <span>画面与数值每 2 秒自动刷新 · 均来自该视频源实拍帧</span>
          <el-button type="primary" @click="goMonitor">打开实时监控</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.agents-page { position: relative; min-height: 480px; }
.agents-page :deep(.el-row) { align-items: stretch; }
.agents-page :deep(.el-col) { display: flex; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.head-left { display: flex; align-items: center; gap: 10px; }
.toolbar-hint { color: #8b93a1; font-size: 0.9375rem; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.sub { color: #9aa2b0; font-size: 0.9375rem; }

/* ── 智能体概览：值班摘要 + 五张独立状态卡 ───────────────── */
.agent-overview { margin-bottom: 16px; }
.agent-summary {
  display: flex; align-items: center; gap: 8px; margin-bottom: 10px; padding: 9px 12px;
  background: #fff; border: 1px solid #e5e7eb; border-left: 3px solid #1f4d78;
  border-radius: 6px; color: #606776; font-size: 0.9375rem; line-height: 1.4;
}
.summary-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; }
.summary-copy { min-width: 0; }
.summary-copy b { color: #1f2d3d; }
.summary-meta { margin-left: auto; color: #9aa2b0; font-size: 0.8125rem; white-space: nowrap; }
.agent-grid { display: grid; gap: 1rem; grid-template-columns: repeat(5, minmax(0, 1fr)); }
@media (max-width: 1500px) { .agent-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1000px) { .agent-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .agent-grid { grid-template-columns: minmax(0, 1fr); } }
.agent-card {
  --state-color: #c0c4cc;
  --state-ink: #7b8494;
  display: flex; flex-direction: column; min-width: 0; overflow: hidden;
  background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  box-shadow: 0 1px 2px rgba(31, 45, 61, .04);
  cursor: pointer;
  transition: border-color .2s, box-shadow .2s, transform .2s;
}
.agent-card:hover { transform: translateY(-1px); box-shadow: 0 8px 24px rgba(31, 45, 61, .1); }
.agent-card:hover, .agent-card:focus-visible {
  border-color: color-mix(in srgb, var(--state-color) 34%, #e5e7eb);
}
.agent-card:focus-visible { outline: 2px solid color-mix(in srgb, var(--state-color) 55%, #fff); outline-offset: 2px; }
.agent-card.is-active {
  border-color: color-mix(in srgb, var(--state-color) 42%, #e5e7eb);
  box-shadow: 0 6px 20px rgba(31, 77, 120, .11);
}
.agent-bar { display: block; height: 4px; flex: 0 0 4px; background: var(--state-color); }
.agent-bar.is-live { animation: agent-bar-pulse 1.6s ease-in-out infinite; }
@keyframes agent-bar-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .28; } }
.agent-card-body { display: flex; flex: 1; flex-direction: column; gap: 12px; padding: 14px 14px 16px; }
.agent-head { display: flex; align-items: center; gap: 6px; min-width: 0; }
.agent-index {
  width: 1.5rem; height: 1.5rem; flex: 0 0 1.5rem; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%; background: color-mix(in srgb, var(--state-color) 13%, #fff);
  color: var(--state-ink); font-size: 0.8125rem; font-weight: 700;
}
.agent-name { flex: 1; min-width: 0; margin: 0; color: #1f2d3d; font-size: 1.125rem; font-weight: 700; line-height: 1.25; }
.agent-status {
  display: inline-flex; align-items: center; flex: 0 0 auto; padding: 2px 6px;
  border: 1px solid color-mix(in srgb, var(--state-color) 28%, #fff); border-radius: 999px;
  background: color-mix(in srgb, var(--state-color) 10%, #fff);
  color: var(--state-ink); font-size: 0.75rem; font-weight: 600; line-height: 1.5; white-space: nowrap;
}
.agent-role { display: flex; align-items: baseline; gap: 6px; color: #303133; font-size: 0.9375rem; line-height: 1.45; }
.role-label { flex: 0 0 auto; color: #8b93a1; font-size: 0.75rem; font-weight: 600; letter-spacing: .02em; }
.agent-doing {
  padding: 9px 10px; border-left: 3px solid var(--state-color); border-radius: 0 6px 6px 0;
  background: color-mix(in srgb, var(--state-color) 8%, #fff);
}
.doing-label { display: block; margin-bottom: 3px; color: #8b93a1; font-size: 0.75rem; font-weight: 600; letter-spacing: .02em; }
.agent-doing p { margin: 0; color: #303133; font-size: 0.875rem; font-weight: 600; line-height: 1.45; }
.agent-metric {
  display: flex; align-items: baseline; gap: 8px; min-width: 0; margin-top: auto;
  padding-top: 12px; border-top: 1px dashed #e5e7eb;
}
.agent-metric strong {
  color: var(--state-ink); font-size: 1.75rem; font-weight: 700; line-height: 1.05;
  letter-spacing: -.02em; font-variant-numeric: tabular-nums;
}
.agent-metric span { color: #8b93a1; font-size: 0.75rem; line-height: 1.35; }
.agent-evidence-hint {
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  margin-top: -0.25rem; color: #a0a8b6; font-size: 0.75rem; font-weight: 600; letter-spacing: .02em;
  transition: color .2s;
}
.agent-evidence-hint span { font-size: 0.875rem; }
.agent-card:hover .agent-evidence-hint, .agent-card:focus-visible .agent-evidence-hint { color: var(--state-ink); }

/* ── 最新决策轨迹 / 当前决策 ─────────────────────────────── */
.trajectory-panel, .decision-panel { height: 100%; flex: 1; }
.evidence { padding-top: 2px; }
.evidence-title { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; font-weight: 600; font-size: 1rem; }
.evidence-title span { color: #9aa2b0; font-weight: 400; font-size: 0.875rem; }
.evidence-row { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; color: #606776; font-size: 0.9375rem; }
.evidence-row b { flex: 0 0 auto; min-width: 88px; white-space: nowrap; color: #303133; }
.evidence-dot { width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; background: #1f4d78; }
.empty { padding: 10px 0; color: #9aa2b0; font-size: 0.875rem; }
.gauge { display: flex; justify-content: center; padding: 4px 0 2px; }
.gauge-value { color: #1f2d3d; font-size: 1.75rem; font-weight: 700; }
.gauge-label { color: #9aa2b0; font-size: 0.875rem; }
.decision-meta { display: flex; justify-content: space-around; margin: 4px 0 12px; color: #8b93a1; font-size: 0.9375rem; }
.decision-rows { display: grid; gap: 8px; }
.decision-rows div { display: flex; justify-content: space-between; padding: 8px 10px; background: #fafbfc; border-radius: 6px; font-size: 1rem; }
.decision-rows span { color: #8b93a1; }
.decision-rows b { color: #303133; }

/* ── 指标带 / 最近轨迹表 ───────────────────────────────── */
.metric-band {
  display: flex; gap: 0; margin-top: 16px; background: #fff; border: 1px solid #e5e7eb;
  border-radius: 8px; overflow: hidden;
}
.metric-block { flex: 1; padding: 12px 16px; border-right: 1px solid #eef0f4; }
.metric-block:last-child { border-right: none; }
.metric-block span { display: block; color: #8b93a1; font-size: 0.875rem; }
.metric-block strong { display: block; margin: 4px 0 2px; color: #1f2d3d; font-size: 1.25rem; }
.metric-block small { color: #a8b0bd; font-size: 0.875rem; }
.recent-panel { margin-top: 16px; }
.recent-panel :deep(.el-table) { font-size: 0.9375rem; }

@media (max-width: 1200px) {
  .summary-meta { margin-left: 0; }
  .metric-band { flex-wrap: wrap; }
  .metric-block { flex: 1 1 30%; border-bottom: 1px solid #eef0f4; }
}

/* ── 证据抽屉 ───────────────────────────────────────────── */
.evidence-drawer :deep(.el-drawer__header) { margin-bottom: 0.75rem; }
.evidence-drawer :deep(.el-drawer__body) { padding: 0.5rem 1.25rem 1.25rem; }
.evidence-body { display: flex; flex-direction: column; gap: 1rem; color: #303133; }
.evidence-headline { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
.evidence-role { color: #1f2d3d; font-size: 1.0625rem; font-weight: 600; }
.evidence-source { color: #8b93a1; font-size: 0.875rem; }
.evidence-frame {
  display: flex; align-items: center; justify-content: center; min-height: 15rem;
  padding: 0.5rem; background: #0f141b; border: 1px solid #232a35; border-radius: 8px;
}
.evidence-frame img { display: block; width: 100%; max-height: 22rem; object-fit: contain; border-radius: 4px; }
.evidence-frame img.is-failed { display: none; }
.evidence-placeholder { padding: 2.5rem 1.5rem; text-align: center; }
.evidence-placeholder b { display: block; margin-bottom: 0.5rem; color: #e8edf3; font-size: 1.0625rem; }
.evidence-placeholder p { margin: 0; color: #9aa6b5; font-size: 0.875rem; line-height: 1.6; }
.evidence-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; }
.evidence-stat { padding: 0.75rem 0.875rem; background: #f7f9fb; border: 1px solid #e5e9f0; border-radius: 8px; }
.evidence-stat strong {
  display: block; color: #1f4d78; font-size: 1.75rem; font-weight: 700; line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.evidence-stat span { display: block; margin-top: 0.25rem; color: #7b8494; font-size: 0.8125rem; }
.evidence-warn {
  margin: 0; padding: 0.5rem 0.75rem; border-radius: 6px;
  background: #fdf6ec; color: #b9781d; font-size: 0.8125rem;
}
.evidence-hint { padding: 0.875rem 1rem; background: #f2f6fa; border-left: 3px solid #1f4d78; border-radius: 0 8px 8px 0; }
.hint-label {
  display: block; margin-bottom: 0.25rem; color: #1f4d78;
  font-size: 0.8125rem; font-weight: 700; letter-spacing: .02em;
}
.evidence-hint p { margin: 0; color: #3d4655; font-size: 0.9375rem; line-height: 1.6; }
.evidence-footer {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding-top: 0.875rem; border-top: 1px dashed #e5e9f0;
}
.evidence-footer span { color: #9aa2b0; font-size: 0.8125rem; }

/* 决策 Agent：纯 CSS 风险刻度，不生成图片 */
.risk-panel { padding: 1.5rem 0.25rem 0.5rem; }
.risk-head { display: flex; align-items: baseline; gap: 0.75rem; margin-bottom: 0.5rem; }
.risk-value {
  color: #1f2d3d; font-size: 3rem; font-weight: 700; line-height: 1;
  font-variant-numeric: tabular-nums;
}
.risk-status { color: #6b7482; font-size: 1.0625rem; font-weight: 600; }
.risk-status.is-normal { color: #1b7d53; }
.risk-status.is-warning { color: #b9781d; }
.risk-status.is-critical { color: #c52f34; }
.risk-track {
  position: relative; display: flex; height: 1rem; margin-top: 1.5rem;
  border-radius: 999px; background: #eef1f5;
}
.risk-zone { position: absolute; top: 0; height: 100%; }
.zone-low { left: 0; width: 45%; border-radius: 999px 0 0 999px; background: linear-gradient(90deg, #23a06b, #7cbf72); }
.zone-mid { left: 45%; width: 35%; background: linear-gradient(90deg, #e6c15c, #e6a23c); }
.zone-high { left: 80%; width: 20%; border-radius: 0 999px 999px 0; background: linear-gradient(90deg, #e5695c, #e5484d); }
.risk-mark {
  position: absolute; top: -1.5rem; transform: translateX(-50%);
  color: #8b93a1; font-size: 0.75rem; line-height: 1;
}
.risk-mark i {
  display: block; width: 2px; height: 2.5rem; margin: 0.2rem auto 0;
  background: #fff; box-shadow: 0 0 0 1px rgba(31, 45, 61, .3);
}
.risk-pointer {
  position: absolute; top: -0.35rem; width: 0.25rem; height: calc(1rem + 0.7rem);
  transform: translateX(-50%); border-radius: 999px; background: #1f2d3d;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, .85);
}
.risk-pointer i {
  position: absolute; top: -0.4rem; left: 50%; width: 0.6rem; height: 0.6rem;
  transform: translateX(-50%); border-radius: 50%; background: #1f2d3d;
}
.risk-axis { position: relative; height: 1.25rem; margin-top: 0.75rem; }
.risk-axis span { position: absolute; transform: translateX(-50%); color: #8b93a1; font-size: 0.8125rem; white-space: nowrap; }
.risk-axis span:nth-child(1) { left: 0; transform: none; }
.risk-axis span:nth-child(2) { left: 45%; }
.risk-axis span:nth-child(3) { left: 80%; }
.risk-axis span:nth-child(4) { right: 0; left: auto; transform: none; }
.risk-note { margin: 0.5rem 0 0; color: #9aa2b0; font-size: 0.8125rem; line-height: 1.6; }

@media (prefers-reduced-motion: reduce) {
  .agent-bar.is-live { animation: none; }
  .agent-card { transition: none; }
  .agent-card:hover { transform: none; }
}
</style>
