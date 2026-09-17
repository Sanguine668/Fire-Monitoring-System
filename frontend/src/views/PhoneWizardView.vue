<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Connection, Plus, Refresh, VideoCamera } from '@element-plus/icons-vue'
import { api, streamUrl } from '../api'

const networkInfo = ref({ addresses: [], preferred: '', dashboard_url: '' })
const phoneUrl = ref('')
const probing = ref(false)
const probeResult = ref(null)
const saving = ref(false)
const savedCamera = ref(null)
const cameraOnline = ref(false)
let pollTimer = null

// 本地文件路径（如 E:/xx.mp4、./demo.mp4）不补 http://，仅用于试连验证
const isLocalPath = (value) => /^[a-z]:[\\/]/i.test(value) || /^\.{0,2}\//.test(value)

const normalizedUrl = computed(() => {
  const raw = phoneUrl.value.trim()
  if (!raw || isLocalPath(raw)) return raw
  if (/^\d+\.\d+\.\d+\.\d+$/.test(raw)) return `http://${raw}:8080/video`
  if (/^\d+\.\d+\.\d+\.\d+:\d+$/.test(raw)) return `http://${raw}/video`

  const value = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`
  try {
    const url = new URL(value)
    // 只填到主机端口时，IP Webcam 首页是网页而不是视频流，补上 /video
    if (!url.pathname || url.pathname === '/') url.pathname = '/video'
    return url.toString()
  } catch {
    return value
  }
})

const isPhoneUrl = computed(() => /^(https?|rtsp):\/\//i.test(normalizedUrl.value))

async function loadNetwork() {
  try {
    networkInfo.value = await api.network()
  } catch (error) {
    ElMessage.error(`获取本机地址失败：${error.message}`)
  }
}

async function copy(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

async function testConnection() {
  if (!normalizedUrl.value) {
    ElMessage.warning('请先填写手机地址')
    return
  }
  probing.value = true
  probeResult.value = null
  try {
    probeResult.value = await api.probe({ source: normalizedUrl.value })
  } catch (error) {
    probeResult.value = { ok: false, message: error.message }
  } finally {
    probing.value = false
  }
}

async function saveCamera() {
  if (!normalizedUrl.value) {
    ElMessage.warning('请先填写手机地址')
    return
  }
  saving.value = true
  try {
    const target = normalizedUrl.value
    savedCamera.value = await api.addCamera({
      name: `手机摄像头-${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`,
      location: '演示现场',
      source_type: /^rtsp:\/\//i.test(target) ? 'rtsp' : 'http',
      source: target,
      loop: false
    })
    ElMessage.success('已添加视频源，正在等待手机画面接入…')
    pollOnline()
  } catch (error) {
    ElMessage.error(`添加失败：${error.message}`)
  } finally {
    saving.value = false
  }
}

async function pollOnline() {
  clearInterval(pollTimer)
  let tries = 0
  pollTimer = setInterval(async () => {
    tries += 1
    try {
      const cameras = await api.cameras()
      const current = cameras.find((c) => c.id === savedCamera.value?.id)
      cameraOnline.value = Boolean(current && current.online)
      if (cameraOnline.value || tries > 10) clearInterval(pollTimer)
    } catch {
      if (tries > 10) clearInterval(pollTimer)
    }
  }, 2000)
}

function openMonitor() {
  window.open('/#/monitor', '_blank')
}

onMounted(loadNetwork)
onUnmounted(() => clearInterval(pollTimer))
</script>

<template>
  <div class="wizard">
    <el-alert
      type="info"
      :closable="false"
      title="目标：把安卓手机变成一路实时摄像头。推荐手机开热点、电脑连热点，最省事也最稳。"
      class="tip"
    />

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" class="step-card">
          <template #header><b>第 1 步　网络准备</b></template>
          <p class="line">本机（电脑）当前局域网地址（手机热点下请用标「推荐」的那一项）：</p>
          <div v-if="networkInfo.addresses.length === 0" class="muted">未检测到局域网地址，请先连接 WiFi 或手机热点。</div>
          <div v-for="item in networkInfo.addresses" :key="item.ip" class="addr">
            <el-tag effect="plain">{{ item.interface }}</el-tag>
            <span class="ip">{{ item.ip }}</span>
            <el-tag v-if="item.ip === networkInfo.preferred" type="success" size="small" effect="light">推荐</el-tag>
            <el-button size="small" text :icon="CopyDocument" @click="copy(item.ip)">复制</el-button>
          </div>
          <p class="line">
            手机与电脑需在同一网络：<b>手机开热点 → 电脑连入该热点</b>，或两者连同一个 WiFi。
          </p>
          <p class="line">
            如果要在手机上打开本系统页面，访问地址：
            <b>{{ networkInfo.dashboard_url || '（未检测到）' }}</b>
            <el-button size="small" text :icon="CopyDocument" @click="copy(networkInfo.dashboard_url)">复制</el-button>
          </p>
          <el-button :icon="Refresh" @click="loadNetwork">重新检测</el-button>
        </el-card>

        <el-card shadow="never" class="step-card">
          <template #header><b>第 2 步　手机端推流</b></template>
          <ol class="line">
            <li>安卓手机安装 <b>IP Webcam</b>（酷安 / APKMirror 可下载 APK）。</li>
            <li>打开 App：分辨率建议 <b>640×480</b>，视频格式选 <b>MJPEG</b>，关闭音频。</li>
            <li>滑到底部点 <b>Start server</b>，屏幕会显示形如 <code>http://192.168.43.1:8080</code> 的地址。</li>
            <li>若手机锁屏会断流，请在 App 里开启保持唤醒。</li>
          </ol>
        </el-card>

        <el-card shadow="never" class="step-card">
          <template #header><b>第 3 步　填写并测试地址</b></template>
          <el-input v-model="phoneUrl" placeholder="手机 IP 或完整地址，例如 192.168.43.1 或 http://192.168.43.1:8080/video">
            <template #append>
              <el-button :icon="Connection" :loading="probing" @click="testConnection">测试连接</el-button>
            </template>
          </el-input>
          <p class="muted">
            只填 IP 会自动补全为 http://IP:8080/video；只填「IP:端口」会补上 /video；也可以直接粘贴 App 显示的完整地址。
            填本地视频路径（如 E:/demo.mp4）只会试连、不会保存成摄像头。
          </p>
          <el-alert
            v-if="probeResult"
            :type="probeResult.ok ? 'success' : 'error'"
            :closable="false"
            :title="probeResult.message"
            class="probe"
          />
          <el-button
            type="primary"
            :icon="Plus"
            :loading="saving"
            :disabled="!isPhoneUrl"
            @click="saveCamera"
          >
            保存为视频源
          </el-button>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never">
          <template #header><b>第 4 步　查看画面</b></template>
          <div class="preview">
            <img v-if="savedCamera && cameraOnline" :src="streamUrl(savedCamera.id, false)" alt="手机画面预览" />
            <div v-else class="placeholder">
              <el-icon size="34"><VideoCamera /></el-icon>
              <p v-if="!savedCamera">尚未添加手机视频源</p>
              <p v-else>已添加，等待画面接入…（{{ cameraOnline ? '在线' : '离线' }}）</p>
            </div>
          </div>
          <div class="actions">
            <el-tag v-if="savedCamera" :type="cameraOnline ? 'success' : 'info'">
              {{ cameraOnline ? '在线' : '等待连接' }}
            </el-tag>
            <el-button v-if="savedCamera" size="small" @click="openMonitor">打开实时监控</el-button>
          </div>
        </el-card>

        <el-card shadow="never" class="step-card">
          <template #header><b>常见问题</b></template>
          <el-collapse>
            <el-collapse-item title="测试连接失败怎么办？" name="1">
              ① 用电脑浏览器打开手机地址，看能否显示画面；② 确认手机与电脑在同一网络（热点模式下电脑是否连的是手机热点）；
              ③ 确认 App 已 Start server；④ 关闭手机移动数据再试；⑤ 把分辨率降到 640×480。
            </el-collapse-item>
            <el-collapse-item title="添加后一直显示离线？" name="2">
              系统会自动重连，间隔从 2 秒逐步拉长、最长 10 秒；若手机重启了推流，地址可能变化，回到第 3 步重新测试并添加。
            </el-collapse-item>
            <el-collapse-item title="画面卡顿？" name="3">
              检测是抽帧的（默认 4 FPS），无需高分辨率。在 IP Webcam 中把分辨率和画质调低可明显改善。
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.tip { margin-bottom: 14px; }
.step-card { margin-bottom: 14px; }
.line { line-height: 1.9; color: #374151; margin: 6px 0; }
.muted { color: #9aa2b0; font-size: 12px; margin: 6px 0; }
.addr { display: flex; align-items: center; gap: 10px; margin: 6px 0; }
.addr .ip { font-family: Consolas, monospace; font-size: 14px; }
.probe { margin: 10px 0; }
.preview { height: 300px; background: #10131a; border-radius: 6px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.preview img { width: 100%; height: 100%; object-fit: contain; }
.placeholder { color: #aab2c0; text-align: center; }
.actions { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
</style>
