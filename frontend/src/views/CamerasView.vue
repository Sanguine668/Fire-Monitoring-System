<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { api, streamUrl } from '../api'

const cameras = ref([])
const loading = ref(false)
const uploadVisible = ref(false)
const uploading = ref(false)
const addVisible = ref(false)
const previewVisible = ref(false)
const previewCamera = ref(null)
const previewAnnotated = ref(true)
const geometryVisible = ref(false)
const geometryCamera = ref(null)
const geometrySaving = ref(false)
const keyword = ref('')
const busyId = ref(null)
const alertsBusyId = ref(null)
const form = reactive({ name: '', location: '', source_type: 'http', source: '', loop: true })
const geometryForm = reactive({
  preset: 'phone_handheld',
  install_height_m: null,
  pitch_deg: null,
  hfov_deg: null
})

// 设备预设：(安装高度 m, 俯角 °, 视场角 °)。custom 表示只认输入框里的数值。
const GEOMETRY_PRESETS = {
  phone_handheld: { label: '手机手持', values: { install_height_m: 1.5, pitch_deg: 12, hfov_deg: 66 } },
  phone_mounted: { label: '手机固定', values: { install_height_m: 1.5, pitch_deg: 5, hfov_deg: 66 } },
  tower_telephoto: { label: '塔杆长焦', values: { install_height_m: 20, pitch_deg: 5, hfov_deg: 20 } },
  custom: { label: '自定义', values: null }
}
const geometryPresetOptions = Object.entries(GEOMETRY_PRESETS).map(([value, item]) => ({
  value,
  label: item.label
}))

function presetLabel(preset) {
  return GEOMETRY_PRESETS[preset]?.label || ''
}

function hasGeometry(camera) {
  return Boolean(camera.geometry_preset) || (
    camera.install_height_m !== null && camera.install_height_m !== undefined
  ) || (
    camera.pitch_deg !== null && camera.pitch_deg !== undefined
  ) || (
    camera.hfov_deg !== null && camera.hfov_deg !== undefined
  )
}

function geometrySummary(camera) {
  if (!hasGeometry(camera)) return ''
  const height = camera.install_height_m === null || camera.install_height_m === undefined
    ? '高度默认'
    : `${camera.install_height_m} m`
  const pitch = camera.pitch_deg === null || camera.pitch_deg === undefined
    ? '俯角默认'
    : `${camera.pitch_deg}°`
  const hfov = camera.hfov_deg === null || camera.hfov_deg === undefined
    ? '视场角默认'
    : `${camera.hfov_deg}°`
  const preset = presetLabel(camera.geometry_preset)
  return `${preset ? `${preset} ` : ''}${height} / ${pitch} / ${hfov}`
}

function applyGeometryPreset(preset) {
  const values = GEOMETRY_PRESETS[preset]?.values
  if (!values) return
  Object.assign(geometryForm, values)
}

function openGeometry(camera) {
  geometryCamera.value = camera
  geometryForm.preset = camera.geometry_preset || (hasGeometry(camera) ? 'custom' : 'phone_handheld')
  geometryForm.install_height_m = camera.install_height_m ?? null
  geometryForm.pitch_deg = camera.pitch_deg ?? null
  geometryForm.hfov_deg = camera.hfov_deg ?? null
  if (!hasGeometry(camera)) applyGeometryPreset('phone_handheld')
  geometryVisible.value = true
}

async function putGeometry(payload) {
  const cameraId = geometryCamera.value?.id
  if (!cameraId) return null
  const response = await fetch(`/api/cameras/${cameraId}/geometry`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const data = await response.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      /* 保留默认错误信息 */
    }
    throw new Error(detail)
  }
  return response.json()
}

function geometryPayload() {
  const value = (input) => (input === null || input === undefined ? null : Number(input))
  return {
    preset: geometryForm.preset || null,
    install_height_m: value(geometryForm.install_height_m),
    pitch_deg: value(geometryForm.pitch_deg),
    hfov_deg: value(geometryForm.hfov_deg)
  }
}

function geometryValid(payload) {
  const limits = [
    ['安装高度', payload.install_height_m, 0.5, 100],
    ['俯角', payload.pitch_deg, 0, 89],
    ['视场角', payload.hfov_deg, 10, 120]
  ]
  for (const [label, value, min, max] of limits) {
    if (value === null) continue
    if (!Number.isFinite(value) || value < min || value > max) {
      ElMessage.warning(`${label}需在 ${min}–${max} 之间（留空则使用默认值）`)
      return false
    }
  }
  return true
}

async function saveGeometry() {
  if (geometrySaving.value || !geometryCamera.value) return
  const payload = geometryPayload()
  if (!geometryValid(payload)) return
  geometrySaving.value = true
  try {
    await putGeometry(payload)
    ElMessage.success('安装参数已保存，后续检测将按新参数估算距离')
    geometryVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`保存安装参数失败：${error.message}`)
  } finally {
    geometrySaving.value = false
  }
}

async function clearGeometry() {
  if (geometrySaving.value || !geometryCamera.value) return
  geometrySaving.value = true
  try {
    await putGeometry({ preset: null, install_height_m: null, pitch_deg: null, hfov_deg: null })
    Object.assign(geometryForm, {
      preset: null,
      install_height_m: null,
      pitch_deg: null,
      hfov_deg: null
    })
    ElMessage.success('已清除安装参数，将按手机手持默认参数估算')
    geometryVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`清除安装参数失败：${error.message}`)
  } finally {
    geometrySaving.value = false
  }
}

const filteredCameras = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  if (!key) return cameras.value
  return cameras.value.filter(
    (c) =>
      (c.name || '').toLowerCase().includes(key) ||
      (c.location || '').toLowerCase().includes(key) ||
      (c.source || '').toLowerCase().includes(key)
  )
})

async function load() {
  loading.value = true
  try {
    cameras.value = await api.cameras()
  } catch (error) {
    ElMessage.error(`加载视频源失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

async function uploadFile({ file }) {
  if (!file) return
  if (!/\.(mp4|mov)$/i.test(file.name || '')) {
    ElMessage.error('仅支持 MP4 / MOV 格式')
    return
  }
  uploading.value = true
  try {
    await api.uploadVideo(file)
    ElMessage.success(`上传成功：${file.name}，已加入视频源列表`)
    uploadVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`上传失败：${error.message}`)
  } finally {
    uploading.value = false
  }
}

function onExceed(files) {
  // 只允许一次传一个：替换掉已选文件后立即上传
  if (!files || !files.length) return
  uploadFile({ file: files[0] })
}

async function submitCamera() {
  if (!form.name || !form.source) {
    ElMessage.warning('请填写名称与视频地址')
    return
  }
  try {
    await api.addCamera({ ...form })
    ElMessage.success('视频源已添加')
    addVisible.value = false
    Object.assign(form, { name: '', location: '', source_type: 'http', source: '', loop: true })
    await load()
  } catch (error) {
    ElMessage.error(`添加失败：${error.message}`)
  }
}

async function toggle(camera) {
  busyId.value = camera.id
  try {
    await api.toggleCamera(camera.id)
    ElMessage.success(camera.enabled ? `已停用「${camera.name}」` : `已启用「${camera.name}」`)
    await load()
  } catch (error) {
    ElMessage.error(`操作失败：${error.message}`)
  } finally {
    busyId.value = null
  }
}

async function toggleAlerts(camera) {
  if (alertsBusyId.value !== null) return
  alertsBusyId.value = camera.id
  try {
    const result = await api.toggleCameraAlerts(camera.id)
    ElMessage.success(
      result.alerts_enabled
        ? `已开启「${camera.name}」的全屏告警`
        : `已关闭「${camera.name}」的全屏告警`
    )
    await load()
  } catch (error) {
    ElMessage.error(`操作失败：${error.message}`)
  } finally {
    alertsBusyId.value = null
  }
}

async function remove(camera) {
  busyId.value = camera.id
  try {
    await ElMessageBox.confirm(`确定删除视频源「${camera.name}」？`, '删除确认', { type: 'warning' })
    await api.deleteCamera(camera.id)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`删除失败：${error.message}`)
  } finally {
    busyId.value = null
  }
}

function preview(camera) {
  previewCamera.value = camera
  previewVisible.value = true
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="cameras">
    <div class="toolbar">
      <el-button type="primary" @click="uploadVisible = true">上传本地视频</el-button>
      <el-button @click="addVisible = true">添加手机 / RTSP 视频源</el-button>
      <el-button @click="load">刷新</el-button>
      <el-input v-model="keyword" placeholder="按名称 / 位置 / 地址搜索" clearable style="width: 240px" />
      <span class="hint">手机推流地址示例：http://192.168.43.1:8080/video（IP Webcam）</span>
    </div>

    <el-empty v-if="filteredCameras.length === 0" :description="cameras.length === 0 ? '暂无视频源' : '没有匹配的视频源'" />
    <el-table v-else :data="filteredCameras" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" width="200" show-overflow-tooltip />
      <el-table-column prop="location" label="位置" width="160" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag effect="plain">{{ row.source_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="地址" min-width="240" show-overflow-tooltip />
      <el-table-column label="在线" width="90">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'info'" size="small">{{ row.online ? '在线' : '离线' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'warning'" size="small" effect="plain">
            {{ row.enabled ? '已启用' : '已停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="全屏告警" width="110" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="row.alerts_enabled === 1"
            :loading="alertsBusyId === row.id"
            @change="toggleAlerts(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="安装参数" width="260">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openGeometry(row)">
            {{ hasGeometry(row) ? geometrySummary(row) : '未设置（手机手持默认）' }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button size="small" @click="preview(row)">预览</el-button>
          <el-button size="small" :loading="busyId === row.id" @click="toggle(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
          <el-button size="small" type="danger" :loading="busyId === row.id" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="uploadVisible" title="上传本地视频（自动循环检测）" width="520px">
      <el-upload
        drag
        :show-file-list="true"
        :limit="1"
        accept=".mp4,.mov"
        :disabled="uploading"
        :http-request="uploadFile"
        :on-exceed="onExceed"
      >
        <el-icon size="36"><Upload /></el-icon>
        <div>{{ uploading ? '正在上传，请稍候…' : '将 MP4/MOV 拖到此处，或点击选择文件' }}</div>
      </el-upload>
      <template #footer>
        <span class="hint">{{ uploading ? '上传中，请勿关闭…' : '选择文件后立即上传，系统会自动创建视频源并开始检测' }}</span>
        <el-button :disabled="uploading" @click="uploadVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addVisible" title="添加视频源" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="例如：手机摄像头-01" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="form.location" placeholder="例如：实验室 A 区" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.source_type">
            <el-option label="http（手机 IP Webcam）" value="http" />
            <el-option label="rtsp（网络摄像头）" value="rtsp" />
            <el-option label="file（本地路径）" value="file" />
          </el-select>
        </el-form-item>
        <el-form-item label="视频地址">
          <el-input v-model="form.source" placeholder="http://192.168.43.1:8080/video 或 rtsp://..." />
        </el-form-item>
        <el-form-item label="循环播放"><el-switch v-model="form.loop" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCamera">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="geometryVisible"
      :title="geometryCamera ? `安装参数：${geometryCamera.name}` : '安装参数'"
      width="440px"
    >
      <el-form label-width="110px">
        <el-form-item label="设备预设">
          <el-select
            v-model="geometryForm.preset"
            placeholder="手机手持"
            style="width: 100%"
            @change="applyGeometryPreset"
          >
            <el-option
              v-for="item in geometryPresetOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="安装高度 (m)">
          <el-input-number
            v-model="geometryForm.install_height_m"
            :min="0.5"
            :max="100"
            :step="0.5"
            :precision="1"
            :value-on-clear="null"
            controls-position="right"
            placeholder="默认 1.5"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="俯角 (°)">
          <el-input-number
            v-model="geometryForm.pitch_deg"
            :min="0"
            :max="89"
            :step="1"
            :precision="1"
            :value-on-clear="null"
            controls-position="right"
            placeholder="默认 12"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="视场角 (°)">
          <el-input-number
            v-model="geometryForm.hfov_deg"
            :min="10"
            :max="120"
            :step="1"
            :precision="1"
            :value-on-clear="null"
            controls-position="right"
            placeholder="默认 66"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <p class="geometry-note">
        选择预设会自动填入典型参数；手机手持为 1.5 m 高 / 12° 俯角 / 66° 视场角。
        留空或点「清除」将按手机手持默认参数估算，误差约 ±40%。距离仅供参考，不代表实测值。
      </p>
      <template #footer>
        <el-button @click="geometryVisible = false">取消</el-button>
        <el-button :loading="geometrySaving" @click="clearGeometry">清除</el-button>
        <el-button type="primary" :loading="geometrySaving" @click="saveGeometry">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="previewCamera ? `预览：${previewCamera.name}` : '预览'" width="760px">
      <div class="preview-tools">
        <el-switch v-model="previewAnnotated" active-text="显示检测框" inactive-text="原始画面" />
      </div>
      <img
        v-if="previewCamera && previewCamera.enabled"
        :src="streamUrl(previewCamera.id, previewAnnotated)"
        style="width: 100%"
      />
      <el-empty v-else description="该视频源已停用" />
    </el-dialog>
  </div>
</template>

<style scoped>
.cameras { position: relative; min-height: 400px; }
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.hint { color: #9aa2b0; font-size: 0.875rem; }
.preview-tools { margin-bottom: 10px; }
.geometry-note { margin: 0; color: #9aa2b0; font-size: 0.75rem; line-height: 1.6; }
</style>
