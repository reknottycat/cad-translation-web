import React, { useEffect, useMemo, useRef, useState } from 'react'
import { MessagePlugin } from 'tdesign-react'
import {
  apiService,
  getApiErrorMessage,
  resolveApiUrl,
  setAdminToken,
} from '../services/api'
import {
  BackendCadTask,
  MAX_BATCH_SIZE,
  MAX_MAX_TOKENS,
  MAX_PARALLEL_COUNT,
  MAX_RETRY_COUNT,
  MAX_RPM,
  MAX_TEMPERATURE,
  MAX_TIMEOUT_SECONDS,
  MIN_MAX_TOKENS,
  MIN_PARALLEL_COUNT,
  MIN_RETRY_COUNT,
  MIN_RPM,
  MIN_TEMPERATURE,
  MIN_TIMEOUT_SECONDS,
  ProcessResult,
  QueueTask,
  TaskStatus,
  buildBackendQueueTask,
  buildBackendTaskResult,
  clamp,
  fileAccept,
  getBackendStageLabel,
  getBackendTaskProgress,
  getFileKind,
  insertionModes,
  normalizeNumber,
  resolveBackendTaskStatus,
  thinkingModes,
  toTitle,
  unique,
  workflowOptions,
} from './workbench/model'
import { WorkbenchSidebar } from './workbench/WorkbenchSidebar'
import { WorkbenchWorkspace } from './workbench/WorkbenchWorkspace'
import { useModelConfiguration } from './workbench/useModelConfiguration'
import { useTaskHistory } from './workbench/useTaskHistory'

const TranslationWorkbenchPage: React.FC = () => {
  const { insertionMode, setInsertionMode, provider, baseUrl, setBaseUrl, apiFormat, setApiFormat, apiKey, setApiKey, setApiKeyDirty, clearApiKey, setClearApiKey, showApiKey, setShowApiKey, modelId, setModelId, useSystemProxy, setUseSystemProxy, forceJson, setForceJson, targetLang, setTargetLang, thinkingMode, setThinkingMode, customPrompt, setCustomPrompt, batchSize, setBatchSize, timeoutSeconds, setTimeoutSeconds, maxTokens, setMaxTokens, parallelCount, setParallelCount, temperature, setTemperature, retryCount, setRetryCount, rpm, setRpm, tpm, setTpm, extraBody, setExtraBody, glossaryFile, setGlossaryFile, glossaryCleared, setGlossaryCleared, runtime, cadDefaults, providerPresets, customProviderName, setCustomProviderName, providerProfiles, providerCredentials, fallbackModels, setFallbackModels, adminTokenDraft, setAdminTokenDraft, configLoadErrors, languageOptions, loadingConfig, savingConfig, testingConnection, savingCustomProvider, deletingProviderId, configMessage, glossaryInputRef, loadConfigResource, loadWorkflowPreset, isCustomProvider, saveCustomProviderPreset, deleteCustomProviderPreset, saveRuntimeConfig, testRuntimeConnection } = useModelConfiguration()
  const [workflow, setWorkflow] = useState<'cad' | 'sheet'>('cad')
  const [autoSelectWorkflow, setAutoSelectWorkflow] = useState(true)
  const [translationRegion, setTranslationRegion] = useState('')
  const [skipTranslation, setSkipTranslation] = useState(false)
  const [files, setFiles] = useState<QueueTask[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [processing, setProcessing] = useState(false)
  const [stoppingTasks, setStoppingTasks] = useState(false)
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null)
  const [downloadingPackage, setDownloadingPackage] = useState(false)
  const [globalMessage, setGlobalMessage] = useState<string>('')
  const { backendTasks, backendTasksLoading, selectedBackendTaskId, setSelectedBackendTaskId, taskLogs, logsLoading, refreshBackendTasks } = useTaskHistory(setGlobalMessage)
  const [isMainDropActive, setIsMainDropActive] = useState(false)
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    workflow: false,
    cadOptions: false,
    model: false,
    config: false,
    glossary: false,
  })

  const mainFileInputRef = useRef<HTMLInputElement | null>(null)
  const locallyCancelledTaskIdsRef = useRef<Set<string>>(new Set())

  const selectedTask = files.find((item) => item.id === selectedTaskId) || files[0] || null
  const selectedBackendTask =
    backendTasks.find((item) => item.task_id === selectedBackendTaskId) || backendTasks[0] || null

  const backendTaskStats = useMemo(() => {
    const total = backendTasks.length
    const done = backendTasks.filter((item) => (item.status || '').toLowerCase() === 'done').length
    const translated = backendTasks.filter((item) => Boolean(item.files?.translated_cad_file)).length
    const excelReady = backendTasks.filter(
      (item) => Boolean(item.files?.excel_file) && (item.status || '').toLowerCase() === 'done',
    ).length
    const active = backendTasks.filter((item) => (item.status || '').toLowerCase() === 'processing').length
    return { total, done, translated, excelReady, active }
  }, [backendTasks])



  useEffect(() => {
    if (!globalMessage) return
    const timer = window.setTimeout(() => setGlobalMessage(''), 6000)
    return () => window.clearTimeout(timer)
  }, [globalMessage])


  useEffect(() => {
    setFiles((current) => {
      const hasLocalTasks = current.some((task) => task.source !== 'backend')
      if (hasLocalTasks) return current

      const hydratedTasks = backendTasks.map((task) => buildBackendQueueTask(task))
      const unchanged =
        current.length === hydratedTasks.length &&
        current.every((task, index) => {
          const nextTask = hydratedTasks[index]
          return (
            nextTask &&
            task.id === nextTask.id &&
            task.status === nextTask.status &&
            task.progress === nextTask.progress &&
            task.message === nextTask.message
          )
        })

      return unchanged ? current : hydratedTasks
    })
  }, [backendTasks])

  useEffect(() => {
    if (!backendTasks.length) return

    setFiles((current) => {
      const claimedTaskIds = new Set(
        current
          .map((task) => task.result?.taskId)
          .filter((taskId): taskId is string => Boolean(taskId)),
      )
      let changed = false

      const nextTasks = current.map((task) => {
        if (task.kind !== 'cad') return task

        const currentTaskId = task.result?.taskId
        const matchedBackendTask =
          backendTasks.find((item) => item.task_id === currentTaskId) ||
          backendTasks.find(
            (item) =>
              item.original_filename === task.file.name &&
              (!claimedTaskIds.has(item.task_id) || item.task_id === currentTaskId),
          )

        if (!matchedBackendTask) return task

        claimedTaskIds.add(matchedBackendTask.task_id)

        const nextResult = {
          ...task.result,
          ...buildBackendTaskResult(matchedBackendTask),
        }

        const hasTranslatedCad = Boolean(matchedBackendTask.files?.translated_cad_file)
        const hasExtractedExcel = Boolean(matchedBackendTask.files?.excel_file)
        const backendStatus = getBackendTaskStatus(matchedBackendTask)
        const shouldMarkDone = hasTranslatedCad || (Boolean(matchedBackendTask.extract_only) && hasExtractedExcel)

        const nextTask: QueueTask = {
          ...task,
          result: nextResult,
        }

        if (locallyCancelledTaskIdsRef.current.has(task.id)) {
          if (
            task.status !== 'cancelled' ||
            nextTask.progress !== 100 ||
            nextTask.message !== '任务已停止'
          ) {
            nextTask.status = 'cancelled'
            nextTask.progress = 100
            nextTask.message = '任务已停止'
            changed = true
          }
          return nextTask
        }

        if (!task.result?.taskId || task.result.taskId !== matchedBackendTask.task_id) {
          nextTask.progress = Math.max(task.progress, shouldMarkDone ? 100 : 55)
          nextTask.message = shouldMarkDone
            ? hasTranslatedCad
              ? 'Translated CAD ready'
              : 'Excel ready'
            : 'Backend task linked'
          changed = true
        }

        if (shouldMarkDone && task.status !== 'done' && task.status !== 'processing') {
          nextTask.status = 'done'
          nextTask.progress = 100
          nextTask.message = hasTranslatedCad ? 'Translated CAD ready' : 'Excel ready'
          changed = true
        }

        if (backendStatus === 'cancelled' && task.status !== 'cancelled') {
          nextTask.status = 'cancelled'
          nextTask.progress = 100
          nextTask.message = '任务已停止'
          changed = true
        }

        return nextTask
      })

      return changed ? nextTasks : current
    })
  }, [backendTasks])

  useEffect(() => {
    if (!autoSelectWorkflow) return
    const hasCad = files.some((item) => item.kind === 'cad')
    const nextWorkflow = hasCad ? 'cad' : 'sheet'
    if (nextWorkflow !== workflow) setWorkflow(nextWorkflow)
  }, [autoSelectWorkflow, files, workflow])

  const updateQueueTask = (taskId: string, patch: Partial<QueueTask>) => {
    setFiles((current) => current.map((task) => (task.id === taskId ? { ...task, ...patch } : task)))
  }

  const appendFiles = (incomingFiles: FileList | File[] | null) => {
    if (!incomingFiles?.length) return

    const nextTasks = Array.from(incomingFiles).map((file) => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
      source: 'local' as const,
      file,
      kind: getFileKind(file),
      status: 'idle' as TaskStatus,
      progress: 0,
      message: '待开始',
    }))

    setFiles((current) => [...current, ...nextTasks])
    setSelectedTaskId((current) => current || nextTasks[0]?.id || null)
      setGlobalMessage(`已添加 ${nextTasks.length} 个文件`)
  }

  const handleMainDragOver = (event: React.DragEvent<HTMLElement>) => {
    event.preventDefault()
    event.stopPropagation()
    if (!isMainDropActive) {
      setIsMainDropActive(true)
    }
  }

  const handleMainDragLeave = (event: React.DragEvent<HTMLElement>) => {
    event.preventDefault()
    event.stopPropagation()
    setIsMainDropActive(false)
  }

  const handleMainDrop = (event: React.DragEvent<HTMLElement>) => {
    event.preventDefault()
    event.stopPropagation()
    setIsMainDropActive(false)
    appendFiles(event.dataTransfer.files)
  }

  const removeTask = (taskId: string) => {
    const removedTask = files.find((task) => task.id === taskId) || null
    setFiles((current) => current.filter((task) => task.id !== taskId))
    setSelectedTaskId((current) => (current === taskId ? null : current))
    if (removedTask?.result?.taskId) {
      setSelectedBackendTaskId((current) => (current === removedTask.result?.taskId ? null : current))
    }
  }

  const toggleSection = (section: keyof typeof collapsedSections) => {
    setCollapsedSections((current) => ({
      ...current,
      [section]: !current[section],
    }))
  }



  const resumeBackendTask = async (taskId: string) => {
    setProcessing(true)
    try {
      const payload: Record<string, unknown> = {
        background: true,
      }
      await apiService.cad.resumeTask(taskId, payload)
      MessagePlugin.success('任务恢复中')
      await refreshBackendTasks()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, '恢复任务失败'))
    } finally {
      setProcessing(false)
    }
  }

  const restartBackendTask = async (task: BackendCadTask) => {
    // Restart means delete the backend task and let user re-upload
    // For now, we just delete the old task and inform the user
    try {
      await apiService.cad.deleteTask(task.task_id)
      MessagePlugin.success('旧任务已清除，请重新上传文件')
      await refreshBackendTasks()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, '清除旧任务失败'))
    }
  }

  const getBackendTaskStatus = (task: BackendCadTask) => {
    return resolveBackendTaskStatus(task)
  }

  const hasActiveLocalTasks = files.some((task) => task.status === 'processing')
  const hasActiveBackendTasks = backendTasks.some((task) => {
    const status = getBackendTaskStatus(task)
    return status === 'processing' || status === 'queued'
  })
  const hasStoppableTasks = hasActiveLocalTasks || hasActiveBackendTasks

  const getBackendTaskStatusLabel = (task: BackendCadTask) => {
    return toTitle(getBackendTaskStatus(task))
  }

  const getQueueTaskBackendTask = (task: QueueTask) => {
    if (task.kind !== 'cad') return null
    if (task.result?.taskId) {
      return backendTasks.find((item) => item.task_id === task.result?.taskId) || null
    }
    return backendTasks.find((item) => item.original_filename === task.file.name) || null
  }

  const getQueueTaskExcelUrl = (task: QueueTask) =>
    resolveApiUrl(task.kind === 'cad' ? task.result?.excelUrl || '' : task.result?.downloadUrl || '')

  const getQueueTaskCadUrl = (task: QueueTask) => resolveApiUrl(task.result?.translatedCadUrl || '')
  const hasLocalTasks = files.length > 0

  const processSpreadsheet = async (task: QueueTask): Promise<ProcessResult> => {
    const formData = new FormData()
    formData.append('file', task.file)
    formData.append('source_lang', 'auto')
    formData.append('target_lang', targetLang)
    formData.append('translation_mode', insertionMode)
    if (translationRegion.trim()) formData.append('translation_region', translationRegion.trim())
    if (customPrompt.trim()) formData.append('custom_prompt', customPrompt.trim())
    if (extraBody.trim()) formData.append('extra_body', extraBody.trim())

    const result: any = await apiService.translation.translateExcel(formData)
    return {
      downloadUrl: resolveApiUrl(result?.download_url || result?.file_url || ''),
      raw: result,
    }
  }

  const processCad = async (task: QueueTask): Promise<ProcessResult> => {
    const formData = new FormData()
    formData.append('file', task.file)
    formData.append('converter_backend', cadDefaults.converter_backend || 'auto')
    formData.append('target_language', targetLang)
    formData.append('extract_only', skipTranslation ? 'true' : 'false')
    formData.append('translation_mode', insertionMode === 'append' ? 'add' : 'replace')
    formData.append('font_name', cadDefaults.font_name || 'Times New Roman')
    formData.append('font_size_reduction', String(cadDefaults.font_size_reduction ?? 4))

    const accepted: any = await apiService.cad.upload(formData, true)
    const taskId = accepted?.task_id || accepted?.data?.task_id || ''
    if (!taskId) throw new Error('后台已接收上传，但响应缺少 task_id')

    let result: any = accepted?.data || accepted
    let polling = true
    while (polling) {
      if (locallyCancelledTaskIdsRef.current.has(task.id)) {
        throw new Error('cancelled by user')
      }
      const response: any = await apiService.cad.getTask(taskId)
      result = response?.data || response
      const status = resolveBackendTaskStatus(result)
      updateQueueTask(task.id, {
        progress: getBackendTaskProgress(result),
        message: getBackendStageLabel(result.stage),
        result: { taskId, raw: result },
      })
      if (status === 'done' || status === 'partial') {
        polling = false
        continue
      }
      if (status === 'error' || status === 'cancelled') {
        throw new Error(result?.last_error || `任务${status === 'cancelled' ? '已停止' : '失败'}`)
      }
      await new Promise((resolve) => window.setTimeout(resolve, document.visibilityState === 'hidden' ? 8000 : 1500))
    }
    return {
      taskId,
      excelUrl: resolveApiUrl(result?.excel_file || result?.data?.excel_file || ''),
      translatedCadUrl:
        resolveApiUrl(
          result?.translated_cad_file ||
            result?.data?.translated_cad_file ||
            '',
        ),
      raw: result,
    }
  }

  const processTask = async (task: QueueTask) => {
    locallyCancelledTaskIdsRef.current.delete(task.id)
    updateQueueTask(task.id, { status: 'processing', progress: 20, message: '处理中' })
    try {
      const result = task.kind === 'cad' ? await processCad(task) : await processSpreadsheet(task)
      if (locallyCancelledTaskIdsRef.current.has(task.id)) {
        updateQueueTask(task.id, {
          status: 'cancelled',
          progress: 100,
          message: '任务已停止',
          result: {
            taskId: result.taskId,
            downloadUrl: result.downloadUrl,
            translatedCadUrl: result.translatedCadUrl,
            excelUrl: result.excelUrl,
            raw: result.raw,
          },
        })
        if (task.kind === 'cad') {
          void refreshBackendTasks(true)
        }
        setGlobalMessage(`${task.file.name} 已停止`)
        return
      }
      const finalStatus = task.kind === 'cad' && resolveBackendTaskStatus(result.raw) === 'partial' ? 'partial' : 'done'
      updateQueueTask(task.id, {
        status: finalStatus,
        progress: 100,
        message: finalStatus === 'partial'
          ? `部分完成 (${result.raw?.failed_count || 0} 条失败)`
          : result.translatedCadUrl || result.downloadUrl || result.excelUrl ? '已完成' : '处理完成',
        result: {
          taskId: result.taskId,
          downloadUrl: result.downloadUrl,
          translatedCadUrl: result.translatedCadUrl,
          excelUrl: result.excelUrl,
          raw: result.raw,
        },
      })
      if (task.kind === 'cad') {
        void refreshBackendTasks(true)
      }
      setGlobalMessage(`${task.file.name} 已完成`)
    } catch (error) {
      const message = getApiErrorMessage(error, `Failed to process ${task.file.name}`)
      const cancelled = locallyCancelledTaskIdsRef.current.has(task.id) || /cancelled|stopped by user/i.test(message)
      updateQueueTask(task.id, {
        status: cancelled ? 'cancelled' : 'error',
        progress: 100,
        message: cancelled ? '任务已停止' : message,
      })
      if (task.kind === 'cad') {
        void refreshBackendTasks(true)
      }
      setGlobalMessage(message)
    }
  }

  const startTask = async (task: QueueTask) => {
    if (task.source === 'backend') return
    if (processing) return
    if (!['idle', 'queued', 'error', 'cancelled'].includes(task.status)) return

    setProcessing(true)
    setSelectedTaskId(task.id)
    updateQueueTask(task.id, {
      status: 'idle',
      progress: 0,
      message: '准备开始',
    })
    setGlobalMessage(`正在处理 ${task.file.name}...`)
    try {
      await processTask(task)
    } finally {
      setProcessing(false)
    }
  }

  const rerunTask = async (task: QueueTask) => {
    if (task.source === 'backend') return
    if (processing) return

    locallyCancelledTaskIdsRef.current.delete(task.id)
    setSelectedBackendTaskId((current) => (current === task.result?.taskId ? null : current))

    const nextTask: QueueTask = {
      ...task,
      status: 'idle',
      progress: 0,
      message: '待开始',
      result: undefined,
    }

    await startTask(nextTask)
  }

  const openOutput = (task: QueueTask) => {
    void downloadOutput(task)
  }

  const downloadOutput = async (task: QueueTask) => {
    const url = task.kind === 'cad' ? getQueueTaskCadUrl(task) : getQueueTaskExcelUrl(task)
    const taskId = task.result?.taskId
    if (!taskId && !url) return
    try {
      const blob = taskId && task.kind === 'cad'
        ? await apiService.cad.download(taskId, 'translated_cad')
        : await apiService.downloadBlob(url)
      const blobUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = task.file.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(blobUrl)
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Download failed'))
    }
  }

  const downloadOutputExcel = async (task: QueueTask) => {
    const url = getQueueTaskExcelUrl(task)
    if (!url && (task.kind !== 'cad' || !task.result?.taskId)) return
    try {
      const blob = task.kind === 'cad' && task.result?.taskId
        ? await apiService.cad.download(task.result.taskId, 'excel')
        : await apiService.downloadBlob(url)
      const blobUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = `${task.file.name.replace(/\.[^.]+$/, '')}.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(blobUrl)
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Excel download failed'))
    }
  }

  const downloadPackage = async (taskIds: string[]) => {
    if (!taskIds.length || downloadingPackage) return
    setDownloadingPackage(true)
    try {
      const blob = await apiService.cad.downloadPackage(taskIds)
      const blobUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = `cad-output-package-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(blobUrl)
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Package download failed'))
    } finally {
      setDownloadingPackage(false)
    }
  }

  const openBackendTaskFile = (task: BackendCadTask, fileType: 'excel' | 'cad' | 'log' | 'translated_cad') => {
    void (async () => {
      try {
        const blob = await apiService.cad.download(task.task_id, fileType)
        const blobUrl = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = blobUrl
        const suffix = fileType === 'excel' ? '.xlsx' : fileType === 'log' ? '.log' : '.dxf'
        link.download = `${task.original_filename.replace(/\.[^.]+$/, '')}${suffix}`
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(blobUrl)
      } catch (error) {
        MessagePlugin.error(getApiErrorMessage(error, '下载失败'))
      }
    })()
  }

  const downloadBackendTaskOutput = (task: BackendCadTask, preferred: 'excel' | 'translated_cad' = 'translated_cad') => {
    const preferredFileType =
      preferred === 'translated_cad' && task.files?.translated_cad_file
        ? 'translated_cad'
        : task.files?.excel_file
          ? 'excel'
          : preferred
    openBackendTaskFile(task, preferredFileType)
  }

  const deleteBackendTask = async (taskId: string) => {
    if (deletingTaskId) return
    setDeletingTaskId(taskId)
    try {
      await apiService.cad.deleteTask(taskId)
      setGlobalMessage(`Task ${taskId} deleted`)
      await refreshBackendTasks()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Delete task failed'))
    } finally {
      setDeletingTaskId(null)
    }
  }

  const stopAllTasks = async () => {
    const cancellableLocalTaskIds = files
      .filter((task) => task.status === 'queued' || task.status === 'processing')
      .map((task) => task.id)

    cancellableLocalTaskIds.forEach((taskId) => {
      locallyCancelledTaskIdsRef.current.add(taskId)
    })

    setFiles((current) =>
      current.map((task) =>
        task.status === 'queued' || task.status === 'processing'
          ? {
              ...task,
              status: 'cancelled',
              progress: 100,
              message: '任务已停止',
            }
          : task,
      ),
    )
    setProcessing(false)
    setStoppingTasks(true)
    try {
      const result: any = await apiService.cad.stopAllTasks()
      setGlobalMessage(result?.message || '已停止所有活动任务')
      MessagePlugin.success(result?.message || '已停止所有活动任务')
      await refreshBackendTasks()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Stop tasks failed'))
    } finally {
      setStoppingTasks(false)
    }
  }

  const contentTask = selectedTask || files[0] || null
  const linkedBackendTask =
    contentTask?.kind === 'cad' && contentTask.result?.taskId
      ? backendTasks.find((task) => task.task_id === contentTask.result?.taskId) || null
      : null
  const detailBackendTask = linkedBackendTask || selectedBackendTask || null
  const detailTaskName = contentTask?.file.name || detailBackendTask?.original_filename || '暂未选择任务'
  const detailTaskStatus = contentTask ? toTitle(contentTask.status) : detailBackendTask ? getBackendTaskStatusLabel(detailBackendTask) : '-'
  const detailTaskProgress = contentTask?.progress ?? (detailBackendTask ? getBackendTaskProgress(detailBackendTask) : 0)
  const detailTaskType = contentTask?.kind.toUpperCase() || (detailBackendTask ? 'CAD' : '-')
  const detailTaskId = contentTask?.result?.taskId || detailBackendTask?.task_id || '-'
  const detailBackendStatus = detailBackendTask ? getBackendTaskStatus(detailBackendTask) : null
  const detailTaskStage = detailBackendTask
    ? detailBackendStatus === 'cancelled'
      ? '已停止'
      : detailBackendTask.stage
      ? getBackendStageLabel(detailBackendTask.stage)
      : getBackendTaskStatusLabel(detailBackendTask)
    : contentTask
      ? contentTask.message
      : '-'
  const outputSourceTask = contentTask?.result?.translatedCadUrl || contentTask?.result?.excelUrl || contentTask?.result?.downloadUrl || contentTask?.result?.taskId ? contentTask : null
  const outputBackendTask = linkedBackendTask || selectedBackendTask || null
  const outputBackendTaskCompleted = outputBackendTask ? ['done', 'partial'].includes(getBackendTaskStatus(outputBackendTask)) : false
  const outputExcelReady = Boolean(
    outputSourceTask?.kind === 'cad'
      ? outputSourceTask.result?.excelUrl || (outputBackendTask?.files?.excel_file && outputBackendTaskCompleted)
      : outputSourceTask?.result?.downloadUrl,
  )
  const outputCadReady = Boolean(
    outputSourceTask?.kind === 'cad'
      ? outputSourceTask.result?.translatedCadUrl || (outputBackendTask?.files?.translated_cad_file && outputBackendTaskCompleted)
      : outputSourceTask?.result?.translatedCadUrl,
  )
  const packageTaskIds = useMemo(() => {
    const queueTaskIds = unique(
      files
        .filter((task) => (task.status === 'done' || task.status === 'partial') && task.kind === 'cad')
        .map((task) => task.result?.taskId || getQueueTaskBackendTask(task)?.task_id || '')
        .filter(Boolean),
    )
    if (queueTaskIds.length) return queueTaskIds
    if (outputBackendTask && (outputBackendTask.files?.excel_file || outputBackendTask.files?.translated_cad_file)) {
      return [outputBackendTask.task_id]
    }
    return []
    // getQueueTaskBackendTask 为内联函数，其数据依赖（files / backendTasks）
    // 均已包含在依赖数组中；将其加入数组会导致 memo 每次渲染都失效。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, outputBackendTask, backendTasks])
  const pendingLocalTasks = files.filter(
    (task) => task.source !== 'backend' && ['idle', 'queued', 'error', 'cancelled'].includes(task.status),
  )
  const selectedLocalActionableTask =
    contentTask && contentTask.source !== 'backend' && ['idle', 'queued', 'error', 'cancelled', 'done'].includes(contentTask.status)
      ? contentTask
      : null
  const nextStartableTask =
    selectedLocalActionableTask && selectedLocalActionableTask.status !== 'done'
      ? selectedLocalActionableTask
      : pendingLocalTasks[0] || null
  const startActionLabel = processing
    ? '运行中...'
    : selectedLocalActionableTask
      ? selectedLocalActionableTask.status === 'done'
        ? '重新执行'
        : selectedLocalActionableTask.status === 'error' || selectedLocalActionableTask.status === 'cancelled'
        ? '重新开始'
        : '开始任务'
      : pendingLocalTasks.length
        ? '开始下一个'
        : '开始任务'
  const startActionDisabled = processing || (!selectedLocalActionableTask && !nextStartableTask)
  const primaryActionLabel = '下载结果包 (.zip)'
  const currentActionLabel = primaryActionLabel
  const selectedBackendOutputCount = selectedBackendTask
    ? [selectedBackendTask.files?.excel_file, selectedBackendTask.files?.translated_cad_file, selectedBackendTask.files?.log_file].filter(Boolean).length
    : 0

  const viewModel = { MAX_BATCH_SIZE, MAX_MAX_TOKENS, MAX_PARALLEL_COUNT, MAX_RETRY_COUNT, MAX_RPM, MAX_TEMPERATURE, MAX_TIMEOUT_SECONDS, MIN_MAX_TOKENS, MIN_PARALLEL_COUNT, MIN_RETRY_COUNT, MIN_RPM, MIN_TEMPERATURE, MIN_TIMEOUT_SECONDS, adminTokenDraft, apiFormat, apiKey, appendFiles, autoSelectWorkflow, backendTaskStats, backendTasks, backendTasksLoading, baseUrl, batchSize, clamp, clearApiKey, collapsedSections, configLoadErrors, configMessage, contentTask, currentActionLabel, customPrompt, customProviderName, deleteBackendTask, deleteCustomProviderPreset, deletingProviderId, deletingTaskId, detailBackendTask, detailTaskId, detailTaskName, detailTaskProgress, detailTaskStage, detailTaskStatus, detailTaskType, downloadBackendTaskOutput, downloadOutput, downloadOutputExcel, downloadPackage, downloadingPackage, extraBody, fallbackModels, fileAccept, files, forceJson, getBackendStageLabel, getBackendTaskStatus, getBackendTaskStatusLabel, glossaryCleared, glossaryFile, glossaryInputRef, handleMainDragLeave, handleMainDragOver, handleMainDrop, hasLocalTasks, hasStoppableTasks, insertionMode, insertionModes, isCustomProvider, isMainDropActive, languageOptions, loadConfigResource, loadWorkflowPreset, loadingConfig, logsLoading, mainFileInputRef, maxTokens, modelId, nextStartableTask, normalizeNumber, openBackendTaskFile, openOutput, outputBackendTask, outputCadReady, outputExcelReady, outputSourceTask, packageTaskIds, parallelCount, processing, provider, providerCredentials, providerPresets, providerProfiles, refreshBackendTasks, removeTask, rerunTask, restartBackendTask, resumeBackendTask, retryCount, rpm, runtime, saveCustomProviderPreset, saveRuntimeConfig, savingConfig, savingCustomProvider, selectedBackendOutputCount, selectedBackendTask, selectedBackendTaskId, selectedLocalActionableTask, selectedTaskId, setAdminToken, setAdminTokenDraft, setApiFormat, setApiKey, setApiKeyDirty, setAutoSelectWorkflow, setBaseUrl, setBatchSize, setClearApiKey, setCustomPrompt, setCustomProviderName, setExtraBody, setFallbackModels, setForceJson, setGlossaryCleared, setGlossaryFile, setInsertionMode, setMaxTokens, setModelId, setParallelCount, setRetryCount, setRpm, setSelectedBackendTaskId, setSelectedTaskId, setShowApiKey, setSkipTranslation, setTargetLang, setTemperature, setThinkingMode, setTimeoutSeconds, setTpm, setTranslationRegion, setUseSystemProxy, setWorkflow, showApiKey, skipTranslation, startActionDisabled, startActionLabel, startTask, stopAllTasks, stoppingTasks, targetLang, taskLogs, temperature, testRuntimeConnection, testingConnection, thinkingMode, thinkingModes, timeoutSeconds, toggleSection, tpm, translationRegion, useSystemProxy, workflow, workflowOptions }

  return (
    <div className="workbench-app">
      <nav className="topbar">
        <div className="topbar-brand">
          <div className="brand-icon">
            <span className="brand-icon-mark">T</span>
          </div>
          <div>
            <div className="brand-name">CAD Translate</div>
            <div className="brand-subtitle">Translation Console</div>
          </div>
          <div className="topbar-pills">
            <a href="#" className="topbar-pill topbar-pill-active">Translation</a>
          </div>
        </div>

        <div className="topbar-right">
          <button className="icon-button" type="button" aria-label="Help">
            ?
          </button>
          <div className="avatar-circle">U</div>
        </div>
      </nav>

      <div className="main-layout">
        <WorkbenchSidebar vm={viewModel} />

        <WorkbenchWorkspace vm={viewModel} />
      </div>

      {globalMessage ? (
        <div className="toast-note" role="status">
          <span>{globalMessage}</span>
          <button type="button" className="toast-close" aria-label="关闭提示" onClick={() => setGlobalMessage('')}>
            ×
          </button>
        </div>
      ) : null}
    </div>
  )
}

export default TranslationWorkbenchPage
