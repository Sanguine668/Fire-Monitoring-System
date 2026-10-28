<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, snapshotUrl, streamUrl } from '../api'
import { useRealtime } from '../composables/useRealtime'

/**
 * 全局火情弹窗：任意页面收到 WebSocket 告警后立即置顶弹出，
 * 展示该视频源的实时画面，并按告警类型播放不同的警报音。
 *
 * 去重规则：同一「视频源 + 告警类型」在确认处理之前只弹一次；
 * 该组告警被确认（status 变为 handled）后释放去重标记，后续新告警可再次弹出。
 */

const { realtime, markHandled } = useRealtime()

const lastId = ref(0)
const ready = ref(false)
const queue = ref([])
const current = ref(null)
const acking = ref(false)
const ackError = ref('')
const streamBroken = ref(false)
const snapshotSrc = ref('')

// 已弹过的「视频源:告警类型」；确认处理后移除
const notified = new Set()

let snapshotTimer = null
let scrollLocked = false
let previousOverflow = ''

/* ── 警报音（Web Audio，无音频文件） ─────────────────────────── */

let audioContext = null

const ALARM_TONES = {
  // 明火：880Hz 三短声，急促
  fire: { frequency: 880, beeps: 3, duration: 0.13, gap: 0.09, type: 'square', gain: 0.16 },
  // 烟雾：520Hz 两声，间隔更长
  smoke: { frequency: 520, beeps: 2, duration: 0.38, gap: 0.34, type: 'triangle', gain: 0.24 }
}

function playAlarmSound(alarmType) {
  try {
    const AudioCtor = window.AudioContext || window.webkitAudioContext
    if (!AudioCtor) return
    if (!audioContext) audioContext = new AudioCtor()
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {})
    // 浏览器在用户交互前会拦截音频：静默跳过，不抛错也不打日志
    if (audioContext.state !== 'running') return

    const tone = ALARM_TONES[alarmType] || ALARM_TONES.fire
    const ctx = audioContext
    const startAt = ctx.currentTime + 0.03
    for (let i = 0; i < tone.beeps; i += 1) {
      const at = startAt + i * (tone.duration + tone.gap)
      const oscillator = ctx.createOscillator()
      const envelope = ctx.createGain()
      oscillator.type = tone.type
      oscillator.frequency.setValueAtTime(tone.frequency, at)
      envelope.gain.setValueAtTime(0.0001, at)
      envelope.gain.exponentialRampToValueAtTime(tone.gain, at + 0.015)
      envelope.gain.setValueAtTime(tone.gain, at + tone.duration - 0.03)
      envelope.gain.exponentialRampToValueAtTime(0.0001, at + tone.duration)
      oscillator.connect(envelope).connect(ctx.destination)
      oscillator.start(at)
      oscillator.stop(at + tone.duration + 0.02)
    }
  } catch {
    // 无音频设备 / 浏览器策略限制时静默降级
  }
}

/* ── 告警识别与去重 ─────────────────────────────────────────── */

function groupKey(alarm) {
  return `${alarm.camera_id}:${alarm.alarm_type}`
}

function highestId(alarms) {
  return alarms.reduce((max, alarm) => {
    const id = Number(alarm.id)
    return Number.isFinite(id) && id > max ? id : max
  }, 0)
}

function syncFromAlarms(alarms) {
  if (!ready.value) return

  // 已确认（handled）的组释放去重标记，后续新告警可再次弹出
  const unhandledKeys = new Set()
  for (const alarm of alarms) {
    if (alarm.status === 'unhandled') unhandledKeys.add(groupKey(alarm))
  }
  for (const key of [...notified]) {
    if (!unhandledKeys.has(key)) notified.delete(key)
  }

  // 只认本次会话中比 lastId 更新的告警；合并更新（同一 id）不会重复弹
  const fresh = alarms
    .filter((alarm) => Number(alarm.id) > lastId.value && alarm.status === 'unhandled')
    .sort((a, b) => a.id - b.id)

  lastId.value = Math.max(lastId.value, highestId(alarms))

  for (const alarm of fresh) {
    const key = groupKey(alarm)
    if (notified.has(key)) continue
    notified.add(key)
    queue.value.push(alarm)
  }
  showNext()
}

/* ── 队列与展示 ─────────────────────────────────────────────── */

const isFire = computed(() => current.value?.alarm_type === 'fire')
const title = computed(() => (isFire.value ? '发现火情' : '疑似火情'))
const levelText = computed(() => (current.value?.level === 'critical' ? '严重' : '预警'))
const timeText = computed(() => current.value?.created_at || '—')
const confidenceText = computed(() => {
  const value = Number(current.value?.confidence)
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—'
})
const countText = computed(() => `${current.value?.count || 1} 次`)

function lockScroll() {
  if (scrollLocked) return
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  scrollLocked = true
}

function unlockScroll() {
  if (!scrollLocked) return
  document.body.style.overflow = previousOverflow
  scrollLocked = false
}

function stopSnapshotPolling() {
  if (snapshotTimer) {
    clearInterval(snapshotTimer)
    snapshotTimer = null
  }
}

function refreshSnapshot() {
  if (!current.value || !streamBroken.value) return
  snapshotSrc.value = `${snapshotUrl(current.value.camera_id, true)}&t=${Date.now()}`
}

function useSnapshotFallback() {
  if (streamBroken.value || !current.value) return
  streamBroken.value = true
  snapshotSrc.value = ''
  refreshSnapshot()
  stopSnapshotPolling()
  snapshotTimer = setInterval(refreshSnapshot, 1000)
}

function showNext() {
  if (current.value) return
  while (queue.value.length > 0) {
    const next = queue.value.shift()
    // 排队期间已被别处确认的告警直接跳过
    if (next.status !== 'unhandled') continue
    current.value = next
    ackError.value = ''
    streamBroken.value = false
    snapshotSrc.value = ''
    stopSnapshotPolling()
    lockScroll()
    playAlarmSound(next.alarm_type)
    return
  }
}

function finishCurrent() {
  stopSnapshotPolling()
  streamBroken.value = false
  snapshotSrc.value = ''
  ackError.value = ''
  current.value = null
  unlockScroll()
  showNext()
}

function dismiss() {
  if (!current.value || acking.value) return
  finishCurrent()
}

async function confirmHandle() {
  const target = current.value
  if (!target || acking.value) return
  acking.value = true
  ackError.value = ''
  try {
    await api.ackAlarmGroup({ camera_id: target.camera_id, alarm_type: target.alarm_type })
    markHandled({ camera_id: target.camera_id, alarm_type: target.alarm_type })
    ElMessage.success('已确认处理')
    if (current.value === target) finishCurrent()
  } catch (error) {
    ackError.value = `确认失败：${error.message || error}`
    ElMessage.error(ackError.value)
  } finally {
    acking.value = false
  }
}

function onKeydown(event) {
  if (event.key !== 'Escape' || !current.value || acking.value) return
  event.preventDefault()
  dismiss()
}

/* ── 生命周期 ───────────────────────────────────────────────── */

watch(() => realtime.alarms, syncFromAlarms, { deep: true })

onMounted(() => {
  // 挂载前已经存在的告警不补弹
  lastId.value = highestId(realtime.alarms)
  ready.value = true
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  stopSnapshotPolling()
  unlockScroll()
  ready.value = false
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fa-fade">
      <div
        v-if="current"
        class="fire-alert"
        :class="isFire ? 'is-fire' : 'is-smoke'"
        :data-alarm-id="current.id"
        :data-camera-id="current.camera_id"
        :data-alarm-type="current.alarm_type"
        role="alertdialog"
        aria-modal="true"
        :aria-label="`${title}：${current.camera_name}`"
      >
        <div class="fire-alert__backdrop" aria-hidden="true" />

        <section class="fire-alert__card">
          <header class="fire-alert__head">
            <span class="fire-alert__icon" aria-hidden="true">⚠</span>
            <div class="fire-alert__heading">
              <h1 class="fire-alert__title">
                {{ title }}
                <span class="fire-alert__camera">· {{ current.camera_name }}</span>
              </h1>
              <p class="fire-alert__sub">AI 视频分析实时告警，请立即核查现场</p>
            </div>
            <span class="fire-alert__badge">{{ levelText }}</span>
          </header>

          <dl class="fire-alert__meta">
            <div>
              <dt>时间</dt>
              <dd>{{ timeText }}</dd>
            </div>
            <div>
              <dt>置信度</dt>
              <dd>{{ confidenceText }}</dd>
            </div>
            <div>
              <dt>累计次数</dt>
              <dd>{{ countText }}</dd>
            </div>
          </dl>

          <div class="fire-alert__video">
            <img
              v-if="!streamBroken"
              :key="`stream-${current.id}`"
              :src="streamUrl(current.camera_id)"
              class="fire-alert__frame"
              alt="实时画面"
              @error="useSnapshotFallback"
            />
            <img
              v-else-if="snapshotSrc"
              :src="snapshotSrc"
              class="fire-alert__frame"
              alt="实时画面（快照轮询）"
            />
            <div v-else class="fire-alert__placeholder">画面加载中…</div>
            <span class="fire-alert__live">{{ streamBroken ? '快照刷新' : 'LIVE 实时画面' }}</span>
          </div>

          <footer class="fire-alert__foot">
            <span class="fire-alert__hint">按 Esc 稍后处理</span>
            <span v-if="ackError" class="fire-alert__error">{{ ackError }}</span>
            <div class="fire-alert__actions">
              <el-button class="fire-alert__later" :disabled="acking" @click="dismiss">
                稍后处理
              </el-button>
              <el-button
                type="primary"
                class="fire-alert__confirm"
                :loading="acking"
                @click="confirmHandle"
              >
                确认处理
              </el-button>
            </div>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fire-alert {
  position: fixed;
  inset: 0;
  z-index: 3100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  overflow-y: auto;
  isolation: isolate;
}

.fire-alert.is-fire {
  --fa-accent: #ff5a5f;
  --fa-accent-strong: #e5484d;
  --fa-soft: rgba(229, 72, 77, 0.18);
  --fa-glow: rgba(255, 68, 74, 0.55);
  --fa-badge-text: #fff;
  --fa-button-text: #fff;
  --fa-wash:
    radial-gradient(circle at 50% 42%, rgba(196, 28, 34, 0.52), rgba(52, 6, 9, 0.88) 68%),
    linear-gradient(180deg, rgba(30, 4, 6, 0.9), rgba(74, 8, 12, 0.82));
}

.fire-alert.is-smoke {
  --fa-accent: #ffb733;
  --fa-accent-strong: #e6a23c;
  --fa-soft: rgba(230, 162, 60, 0.18);
  --fa-glow: rgba(255, 168, 38, 0.5);
  --fa-badge-text: #241603;
  --fa-button-text: #241603;
  --fa-wash:
    radial-gradient(circle at 50% 42%, rgba(196, 125, 16, 0.5), rgba(43, 28, 4, 0.9) 68%),
    linear-gradient(180deg, rgba(26, 18, 3, 0.9), rgba(74, 50, 6, 0.82));
}

.fire-alert__backdrop {
  position: absolute;
  inset: 0;
  z-index: -1;
  background: var(--fa-wash);
  animation: fa-wash 2.6s ease-in-out infinite;
}

.fire-alert__card {
  position: relative;
  width: min(92vw, 900px);
  max-height: calc(100vh - 3rem);
  overflow: auto;
  padding: 1.5rem;
  border: 2px solid var(--fa-accent);
  border-radius: 18px;
  background: linear-gradient(165deg, #1c222c 0%, #10141b 62%, #0b0e13 100%);
  color: #f3f5f9;
  animation: fa-card-pulse 1.8s ease-in-out infinite;
}

.fire-alert__head {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.fire-alert__icon {
  flex: none;
  display: grid;
  place-items: center;
  width: 3.25rem;
  height: 3.25rem;
  border: 1px solid var(--fa-accent);
  border-radius: 50%;
  background: var(--fa-soft);
  color: var(--fa-accent);
  font-family: 'Segoe UI Symbol', 'Microsoft YaHei', sans-serif;
  font-size: 1.9rem;
  line-height: 1;
  text-shadow: 0 0 1rem var(--fa-glow);
  font-variant-emoji: text;
}

.fire-alert__heading {
  flex: 1;
  min-width: 0;
}

.fire-alert__title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem;
  margin: 0;
  color: var(--fa-accent);
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  line-height: 1.2;
}

.fire-alert__camera {
  color: #e7ebf2;
  font-size: 1.2rem;
  font-weight: 600;
  letter-spacing: 0;
  opacity: 0.9;
}

.fire-alert__sub {
  margin: 0.3rem 0 0;
  color: #a9b2c0;
  font-size: 0.9rem;
}

.fire-alert__badge {
  flex: none;
  align-self: center;
  padding: 0.2rem 0.9rem;
  border-radius: 999px;
  background: var(--fa-accent);
  color: var(--fa-badge-text);
  font-size: 0.9rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  box-shadow: 0 0 1.2rem var(--fa-glow);
}

.fire-alert__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 2rem;
  margin: 1.1rem 0 1rem;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.055);
}

.fire-alert__meta > div {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
}

.fire-alert__meta dt {
  color: #98a2b3;
  font-size: 0.8rem;
  letter-spacing: 0.06em;
}

.fire-alert__meta dd {
  margin: 0;
  color: #f5f7fa;
  font-size: 1rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.fire-alert__video {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 12px;
  background: #000;
}

.fire-alert__frame {
  display: block;
  width: 100%;
  height: 100%;
  background: #000;
  object-fit: contain;
}

.fire-alert__placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at 50% 50%, #141a22, #05070a);
  color: #77808f;
  font-size: 0.95rem;
}

.fire-alert__live {
  position: absolute;
  top: 0.7rem;
  left: 0.7rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.15rem 0.55rem;
  border: 1px solid var(--fa-accent);
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.fire-alert__live::before {
  content: '';
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: var(--fa-accent);
  box-shadow: 0 0 0.5rem var(--fa-accent);
  animation: fa-blink 1.2s steps(1, end) infinite;
}

.fire-alert__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1.1rem;
}

.fire-alert__hint {
  margin-right: auto;
  color: #8f99a8;
  font-size: 0.8rem;
}

.fire-alert__error {
  color: #ff9a9d;
  font-size: 0.85rem;
}

.fire-alert__actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-left: auto;
}

.fire-alert__actions :deep(.el-button) {
  min-height: 2.6rem;
  padding: 0 1.5rem;
  border-radius: 10px;
  font-size: 1rem;
  font-weight: 700;
}

.fire-alert__later {
  border: 1px solid rgba(255, 255, 255, 0.22);
  background: rgba(255, 255, 255, 0.06);
  color: #e9edf4;
}

.fire-alert__later:hover,
.fire-alert__later:focus {
  border-color: rgba(255, 255, 255, 0.38);
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
}

.fire-alert__confirm {
  --el-button-bg-color: var(--fa-accent-strong);
  --el-button-border-color: var(--fa-accent-strong);
  --el-button-text-color: var(--fa-button-text);
  --el-button-hover-bg-color: var(--fa-accent);
  --el-button-hover-border-color: var(--fa-accent);
  --el-button-hover-text-color: var(--fa-button-text);
  --el-button-active-bg-color: var(--fa-accent-strong);
  --el-button-active-border-color: var(--fa-accent-strong);
  --el-button-active-text-color: var(--fa-button-text);
  --el-button-disabled-bg-color: var(--fa-accent-strong);
  --el-button-disabled-border-color: var(--fa-accent-strong);
  --el-button-disabled-text-color: var(--fa-button-text);
}

@keyframes fa-card-pulse {
  0%,
  100% {
    box-shadow:
      0 0 26px 4px var(--fa-glow),
      0 30px 90px rgba(0, 0, 0, 0.6);
  }
  50% {
    box-shadow:
      0 0 0 2px var(--fa-accent),
      0 0 64px 14px var(--fa-glow),
      0 30px 90px rgba(0, 0, 0, 0.6);
  }
}

@keyframes fa-wash {
  0%,
  100% {
    opacity: 0.86;
  }
  50% {
    opacity: 1;
  }
}

@keyframes fa-blink {
  0%,
  60% {
    opacity: 1;
  }
  61%,
  100% {
    opacity: 0.25;
  }
}

.fa-fade-enter-active,
.fa-fade-leave-active {
  transition: opacity 0.18s ease;
}

.fa-fade-enter-from,
.fa-fade-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .fire-alert {
    padding: 0.75rem;
  }

  .fire-alert__card {
    width: 100%;
    padding: 1rem;
  }

  .fire-alert__icon {
    width: 2.6rem;
    height: 2.6rem;
    font-size: 1.5rem;
  }

  .fire-alert__title {
    font-size: 1.5rem;
  }

  .fire-alert__camera {
    font-size: 1rem;
  }

  .fire-alert__badge {
    font-size: 0.8rem;
  }

  .fire-alert__meta {
    gap: 0.4rem 1.2rem;
  }

  .fire-alert__hint {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .fire-alert__backdrop,
  .fire-alert__card,
  .fire-alert__live::before {
    animation: none;
  }

  .fire-alert__card {
    box-shadow:
      0 0 40px 6px var(--fa-glow),
      0 30px 90px rgba(0, 0, 0, 0.6);
  }

  .fa-fade-enter-active,
  .fa-fade-leave-active {
    transition: none;
  }
}
</style>
