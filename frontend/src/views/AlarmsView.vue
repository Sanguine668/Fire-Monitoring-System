<script setup>
const alarmRows = [
  { created_at: '2026-09-09 10:00:12', camera_name: '仓库东区-01', alarm_type: 'fire', level: 'critical', confidence: 0.92, status: 'unhandled' }
]
</script>

<template>
  <el-card shadow="never">
    <el-table :data="alarmRows" stripe empty-text="暂无告警记录">
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="camera_name" label="视频源" width="160" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.alarm_type === 'fire' ? 'danger' : 'warning'">
            {{ row.alarm_type === 'fire' ? '明火' : '烟雾' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="级别" width="120">
        <template #default="{ row }">
          <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" effect="plain">
            {{ row.level === 'critical' ? '严重' : '预警' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="置信度">
        <template #default="{ row }">{{ (row.confidence * 100).toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.status === 'handled' ? 'success' : 'info'" effect="plain">
            {{ row.status === 'handled' ? '已处理' : '待处理' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>
