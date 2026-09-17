<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { api, streamUrl } from '../api'

const cameras = ref([])
const loading = ref(false)
const uploadVisible = ref(false)
const addVisible = ref(false)
const previewVisible = ref(false)
const previewCamera = ref(null)
const previewAnnotated = ref(true)
const keyword = ref('')
const busyId = ref(null)
const form = reactive({ name: '', location: '', source_type: 'http', source: '', loop: true })

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
  try {
    await api.uploadVideo(file)
    ElMessage.success('上传成功，已加入视频源列表')
    uploadVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`上传失败：${error.message}（请确认后端已启动）`)
  }
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
  <div v-loading="loading">
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
      <el-table-column prop="name" label="名称" width="180" />
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
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button size="small" @click="preview(row)">预览</el-button>
          <el-button size="small" :loading="busyId === row.id" @click="toggle(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
          <el-button size="small" type="danger" :loading="busyId === row.id" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="uploadVisible" title="上传本地视频（自动循环检测）" width="520px">
      <el-upload drag :auto-upload="false" :show-file-list="true" accept=".mp4,.mov" :http-request="uploadFile">
        <el-icon size="36"><Upload /></el-icon>
        <div>将 MP4/MOV 拖到此处，或点击选择文件</div>
      </el-upload>
      <template #footer>
        <span class="hint">上传后系统会自动创建视频源并开始检测</span>
        <el-button @click="uploadVisible = false">关闭</el-button>
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
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.hint { color: #9aa2b0; font-size: 12px; }
.preview-tools { margin-bottom: 10px; }
</style>
