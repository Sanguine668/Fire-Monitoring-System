<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoCamera, Grid, Refresh, SwitchButton, FullScreen } from '@element-plus/icons-vue'
import { api, streamUrl } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const cameras = ref([])
const loading = ref(false)
const viewMode = ref('grid')
const selectedId = ref(null)
const togglingId = ref(null)
const maximized = ref(false)
let timer = null

const enabledCameras = computed(() => cameras.value.filter((c) => c.enabled))
const selected = computed(
  () => cameras.value.find((c) => c.id === selectedId.value) || enabledCameras.value[0] || null
)

async function load(showError = false) {
  try {
    cameras.value = await api.cameras()
    if (!selected.value) selectedId.value = null
    if (!enabledCameras.value.some((c) => c.id === selectedId.value)) {
      selectedId.value = enabledCameras.value.length ? enabledCameras.value[0].id : null
    }
  } catch (error) {
    if (showError) ElMessage.error(`加载视频源失败：${error.message}`)
  }
}

function select(camera) {
  selectedId.value = camera.id
}

async function toggle(camera) {
  togglingId.value = camera.id
  try {
    await api.toggleCamera(camera.id)
    ElMessage.success(camera.enabled ? `已停用「${camera.name}」` : `已启用「${camera.name}」`)
    await load(true)
  } catch (error) {
    ElMessage.error(`操作失败：${error.message}`)
  } finally {
    togglingId.value = null
  }
}

function detectionOf(id) {
  return realtime.detections[id] || null
}

onMounted(() => {
  loading.value = true
  load(true).finally(() => {
    loading.value = false
  })
  timer = setInterval(() => load(false), 10000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-radio-group v-model="viewMode" size="default">
        <el-radio-button value="grid"><el-icon><Grid /></el-icon>&nbsp;并列模式</el-radio-button>
        <el-radio-button value="focus"><el-icon><VideoCamera /></el-icon>&nbsp;焦点模式</el-radio-button>
      </el-radio-group>
      <span class="hint">焦点模式：主画面居中，点击下方缩略图切换</span>
      <el-button :icon="Refresh" @click="load(true)">刷新</el-button>
    </div>

    <el-empty v-if="cameras.length === 0" description="还没有视频源，请到“视频源管理”上传视频或添加手机推流地址" />

    <!-- 焦点模式 -->
    <template v-else-if="viewMode === 'focus'">
      <el-card shadow="never" :body-style="{ padding: '0' }" class="focus-card">
        <div class="stage focus-stage" :class="{ maximized }">
          <template v-if="selected && selected.enabled">
            <img :src="streamUrl(selected.id)" class="frame" :alt="selected.name" />
            <div class="overlay">
              <span>{{ selected.name }}</span>
              <span v-if="detectionOf(selected.id)">目标 {{ (detectionOf(selected.id).objects || []).length }}</span>
              <span v-if="detectionOf(selected.id)">风险 {{ detectionOf(selected.id).risk_score }}</span>
              <span v-if="detectionOf(selected.id)">{{ detectionOf(selected.id).fps }} FPS</span>
            </div>
          </template>
          <div v-else class="placeholder">暂无可用的启用视频源</div>
        </div>
        <div class="meta">
          <div>
            <b>{{ selected ? selected.name : '—' }}</b>
            <span class="location">{{ selected ? selected.location || selected.source_type : '' }}</span>
          </div>
          <el-button
            v-if="selected"
            :icon="SwitchButton"
            :loading="togglingId === selected.id"
            @click="toggle(selected)"
          >
            {{ selected.enabled ? '停用' : '启用' }}
          </el-button>
          <el-button :icon="FullScreen" @click="maximized = !maximized">
            {{ maximized ? '还原' : '放大' }}
          </el-button>
        </div>
      </el-card>

      <div class="thumbs">
        <div
          v-for="c in cameras"
          :key="c.id"
          class="thumb"
          :class="{ active: selected && c.id === selected.id, offline: !c.enabled }"
          @click="select(c)"
        >
          <img v-if="c.enabled" :src="streamUrl(c.id, false)" :alt="c.name" />
          <div v-else class="thumb-off">已停用</div>
          <p>{{ c.name }}</p>
        </div>
      </div>
    </template>

    <!-- 并列模式 -->
    <el-row v-else :gutter="16">
      <el-col v-for="c in cameras" :key="c.id" :span="12" class="cell">
        <el-card shadow="never" :body-style="{ padding: '0' }" :class="{ selected: selected && c.id === selected.id }">
          <div class="stage" @click="select(c)">
            <el-tag :type="c.online ? 'success' : 'info'" size="small" class="tag">
              {{ c.online ? '在线' : '离线' }}
            </el-tag>
            <el-tag v-if="!c.enabled" type="warning" size="small" class="tag-right">已停用</el-tag>
            <img v-if="c.enabled" :src="streamUrl(c.id)" class="frame" :alt="c.name" />
            <div v-else class="placeholder">视频源已停用</div>
            <div v-if="detectionOf(c.id)" class="overlay">
              <span>目标 {{ (detectionOf(c.id).objects || []).length }}</span>
              <span>风险 {{ detectionOf(c.id).risk_score }}</span>
              <span>{{ detectionOf(c.id).fps }} FPS</span>
            </div>
          </div>
          <div class="meta">
            <div>
              <b>{{ c.name }}</b>
              <span class="location">{{ c.location || c.source_type }}</span>
            </div>
            <el-button
              size="small"
              :icon="SwitchButton"
              :loading="togglingId === c.id"
              @click.stop="toggle(c)"
            >
              {{ c.enabled ? '停用' : '启用' }}
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.hint { color: #9aa2b0; font-size: 12px; margin-right: auto; }
.stage { height: 260px; background: #10131a; color: #fff; position: relative; overflow: hidden; cursor: pointer; }
.focus-stage { height: clamp(380px, calc(100vh - 380px), 780px); }
.focus-stage.maximized { height: calc(100vh - 150px); }
.frame { width: 100%; height: 100%; object-fit: contain; display: block; }
.tag { position: absolute; top: 8px; left: 8px; z-index: 2; }
.tag-right { position: absolute; top: 8px; right: 8px; z-index: 2; }
.placeholder { height: 100%; display: flex; align-items: center; justify-content: center; color: #aab2c0; }
.overlay {
  position: absolute; left: 8px; bottom: 8px; display: flex; gap: 10px; font-size: 12px;
  background: rgba(0, 0, 0, .55); padding: 4px 8px; border-radius: 4px; z-index: 2;
}
.meta { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; color: #4b5563; }
.location { margin-left: 8px; color: #9aa2b0; font-size: 12px; }
.cell { margin-bottom: 16px; }
.focus-card { margin-bottom: 14px; }
.thumbs { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 6px; }
.thumb {
  width: 168px; flex: 0 0 auto; border: 2px solid transparent; border-radius: 6px; overflow: hidden;
  background: #fff; cursor: pointer; box-shadow: 0 1px 3px rgba(0, 0, 0, .08);
}
.thumb.active { border-color: #1f4d78; }
.thumb.offline { opacity: .55; }
.thumb img { width: 100%; height: 100px; object-fit: cover; display: block; background: #10131a; }
.thumb p { margin: 0; padding: 6px 8px; font-size: 12px; color: #4b5563; }
.thumb-off { height: 100px; display: flex; align-items: center; justify-content: center; background: #eef0f4; color: #9aa2b0; font-size: 12px; }
.selected { box-shadow: 0 0 0 2px #1f4d78 inset; }
</style>
