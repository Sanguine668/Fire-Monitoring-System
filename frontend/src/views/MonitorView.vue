<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, streamUrl } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const cameras = ref([])
const loading = ref(false)
let timer = null

async function load() {
  try {
    cameras.value = await api.cameras()
  } catch (error) {
    ElMessage.error(`加载视频源失败：${error.message}`)
  }
}

async function toggle(camera) {
  try {
    await api.toggleCamera(camera.id)
    ElMessage.success(camera.enabled ? '已停用该视频源' : '已启用该视频源')
    await load()
  } catch (error) {
    ElMessage.error(`操作失败：${error.message}`)
  }
}

function detectionOf(id) {
  return realtime.detections[id] || null
}

onMounted(() => {
  loading.value = true
  load().finally(() => { loading.value = false })
  timer = setInterval(load, 10000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div v-loading="loading">
    <el-empty v-if="cameras.length === 0" description="还没有视频源，请到“视频源管理”上传视频或添加手机推流地址" />
    <el-row v-else :gutter="16">
      <el-col v-for="c in cameras" :key="c.id" :span="12" class="cell">
        <el-card shadow="never" :body-style="{ padding: '0' }">
          <div class="stage">
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
            <el-button size="small" @click="toggle(c)">{{ c.enabled ? '停用' : '启用' }}</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.cell { margin-bottom: 16px; }
.stage { height: 260px; background: #10131a; color: #fff; position: relative; overflow: hidden; }
.frame { width: 100%; height: 100%; object-fit: contain; display: block; }
.tag { position: absolute; top: 8px; left: 8px; z-index: 2; }
.tag-right { position: absolute; top: 8px; right: 8px; z-index: 2; }
.placeholder { height: 100%; display: flex; align-items: center; justify-content: center; color: #aab2c0; }
.overlay { position: absolute; left: 8px; bottom: 8px; display: flex; gap: 10px; font-size: 12px;
           background: rgba(0, 0, 0, .55); padding: 4px 8px; border-radius: 4px; z-index: 2; }
.meta { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; color: #4b5563; }
.location { margin-left: 8px; color: #9aa2b0; font-size: 12px; }
</style>
