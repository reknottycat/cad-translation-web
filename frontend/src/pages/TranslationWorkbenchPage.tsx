import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Button, MessagePlugin } from 'tdesign-react'
import { CloudUploadIcon, DeleteIcon, DownloadIcon, RefreshIcon } from 'tdesign-icons-react'
import { apiService, getApiErrorMessage, resolveApiUrl } from '../services/api'

type FileKind = 'cad' | 'excel' | 'csv' | 'other'
type TaskStatus = 'idle' | 'queued' | 'processing' | 'done' | 'partial' | 'error' | 'cancelled'
type ThinkingMode = 'enabled' | 'disabled' | 'default'

interface LanguageOption {
  label: string
  value: string
}

interface ProviderPreset {
  id: string
  name: string
  api_format?: string
  base_url: string
  default_model: string
  notes: string
}

interface RuntimeSummary {
  provider?: string
  format?: string
  base_url?: string
  model?: string
  api_key_configured?: boolean
  api_key_source?: 'config' | 'none'
  masked_api_key?: string
  reasoning_enabled?: boolean
  system_prompt_mode?: string
  custom_system_prompt?: string
  custom_system_prompt_configured?: boolean
  glossary_file?: string
  timeout_seconds?: number
  temperature?: number
  max_tokens?: number
  batch_size?: number
  batch_json?: boolean
  parallel_count?: number
  retry_count?: number
  rpm?: number
  tpm?: string
  extra_body?: string
  use_system_proxy?: boolean
  fallback_models?: Array<Record<string, unknown>>
}

interface CadDefaultsSummary {
  target_language?: string
  translation_mode?: string
  font_name?: string
  font_size_reduction?: number
  default_output_dir?: string
  converter_backend?: string
}

interface QueueTask {
  id: string
  source?: 'local' | 'backend'
  file: File
  kind: FileKind
  status: TaskStatus
  progress: number
  message: string
  result?: {
    downloadUrl?: string
    translatedCadUrl?: string
    excelUrl?: string
    taskId?: string
    raw?: any
  }
}

interface ProcessResult {
  downloadUrl?: string
  translatedCadUrl?: string
  excelUrl?: string
  taskId?: string
  raw?: any
}

interface BackendCadTask {
  task_id: string
  original_filename: string
  target_language?: string
  extract_only?: boolean
  status?: string
  stage?: string
  processing_time?: string
  text_count?: number
  translatable_count?: number
  translation_count?: number
  translated_count?: number
  failed_count?: number
  total_chunks?: number
  completed_chunks?: number
  current_chunk?: number
  provider?: string
  model?: string
  batch_size?: number
  retry_count?: number
  last_error?: string
  last_activity_at?: number
  created_at?: number
  files?: {
    excel_file?: string | null
    translated_cad_file?: string | null
    log_file?: string | null
  }
}

const buildBackendTaskResult = (task: BackendCadTask) => ({
  taskId: task.task_id,
  downloadUrl: '',
  translatedCadUrl: resolveApiUrl(task.files?.translated_cad_file || ''),
  excelUrl: resolveApiUrl(task.files?.excel_file || ''),
  raw: task,
})

const resolveBackendTaskStatus = (task: BackendCadTask): TaskStatus => {
  const explicitStatus = (task.status || '').toLowerCase()
  const lastError = (task.last_error || '').toLowerCase()
  if (lastError.includes('cancelled by user') || lastError.includes('stopped by user')) {
    return 'cancelled'
  }
  if (explicitStatus === 'done' || explicitStatus === 'partial' || explicitStatus === 'processing' || explicitStatus === 'error' || explicitStatus === 'queued' || explicitStatus === 'cancelled') {
    const rawTc = task.translated_count
    const tc = typeof rawTc === 'number' ? rawTc : (task.translation_count ?? 0)
    const total = task.text_count ?? 0
    if (explicitStatus === 'done' && total > 0 && tc < total) {
      return 'partial'
    }
    return explicitStatus as TaskStatus
  }
  if (task.files?.translated_cad_file) return 'done'
  if (task.extract_only && task.files?.excel_file) return 'done'
  if (task.files?.excel_file) return 'processing'
  return 'queued'
}

const buildBackendQueueTask = (task: BackendCadTask): QueueTask => {
  const status = resolveBackendTaskStatus(task)
  const hasTranslatedCad = Boolean(task.files?.translated_cad_file)
  const hasExcel = Boolean(task.files?.excel_file)
  const message =
    status === 'done'
      ? hasTranslatedCad
        ? 'Translated CAD ready'
        : hasExcel
          ? 'Excel ready'
          : 'Completed'
      : status === 'partial'
        ? `部分完成 (${task.failed_count || 0} 条失败)`
        : status === 'cancelled'
          ? '任务已停止'
          : status === 'error'
            ? task.last_error || 'Task failed'
            : getBackendStageLabel(task.stage)

  return {
    id: `backend-${task.task_id}`,
    source: 'backend',
    file: new File([], task.original_filename || `${task.task_id}.dwg`, { type: 'application/octet-stream' }),
    kind: 'cad',
    status,
    progress: getBackendTaskProgress(task),
    message,
    result: buildBackendTaskResult(task),
  }
}

const getBackendTaskProgress = (task: BackendCadTask) => {
  const explicitStatus = (task.status || '').toLowerCase()
  const lastError = (task.last_error || '').toLowerCase()
  const status =
    lastError.includes('cancelled by user') || lastError.includes('stopped by user')
      ? 'cancelled'
      : explicitStatus
  // Terminal states always report 100% so the progress bar can settle.
  if (status === 'cancelled' || status === 'error' || status === 'done') {
    return 100
  }
  // Truthy guard avoids divide-by-zero when total_chunks is 0/undefined.
  if (task.total_chunks) {
    // Use ?? so a legitimate 0 from the backend is preserved (no fallback to 0 via ||).
    const completed = task.completed_chunks ?? 0
    // Real chunk progress, floored at 20% so the UI never regresses to 0
    // while a translation task is alive (was the source of the "0/7 stuck at 20%" bug).
    return Math.min(100, Math.max(20, Math.round((completed / task.total_chunks) * 100)))
  }
  if (task.files?.translated_cad_file) return 100
  if (task.extract_only && task.files?.excel_file) return 100
  if (task.files?.excel_file) return 55
  return 20
}

const getBackendStageLabel = (stage?: string) => {
  switch (stage) {
    case 'extracting':
      return '正在提取 CAD 文本'
    case 'extracted':
      return '文本提取完成'
    case 'translating':
      return 'LLM 翻译中'
    case 'applying':
      return '正在回写翻译'
    case 'completed':
      return '已完成'
    case 'cancelled':
      return '已停止'
    case 'failed':
      return '失败'
    default:
      return '排队中'
  }
}

const getOutputLabel = (options: { translatedCadUrl?: string; excelUrl?: string }) => {
  if (options.translatedCadUrl) return '下载 CAD'
  if (options.excelUrl) return '下载 Excel'
  return '下载结果'
}

const unique = <T,>(items: T[]) => Array.from(new Set(items))

const defaultLanguageOptions: LanguageOption[] = [
  { label: 'Auto Detect', value: 'auto' },
  { label: 'Chinese', value: 'zh' },
  { label: 'English', value: 'en' },
  { label: 'Japanese', value: 'ja' },
  { label: 'Korean', value: 'ko' },
  { label: 'Deutsch', value: 'de' },
  { label: 'French', value: 'fr' },
  { label: 'Russian', value: 'ru' },
]

const workflowOptions = [
  { label: 'CAD translation (.dwg/.dxf)', value: 'cad' },
  { label: 'Spreadsheet translation', value: 'sheet' },
]

const MAX_BATCH_SIZE = 2000
const MIN_TIMEOUT_SECONDS = 1
const MAX_TIMEOUT_SECONDS = 600
const MIN_MAX_TOKENS = 1
const MAX_MAX_TOKENS = 32000
const DEFAULT_MAX_TOKENS = 16384
const MIN_PARALLEL_COUNT = 1
const MAX_PARALLEL_COUNT = 32
const MIN_RETRY_COUNT = 0
const MAX_RETRY_COUNT = 10
const MIN_RPM = 1
const MAX_RPM = 20000
const MIN_TEMPERATURE = 0
const MAX_TEMPERATURE = 2
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
const normalizeNumber = (value: unknown, fallback: number, min: number, max: number) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return clamp(numeric, min, max)
}

const insertionModes = [
  { label: '替换原文', value: 'replace' },
  { label: '追加到下方', value: 'append' },
  { label: '原文后换行', value: 'newline' },
]

const thinkingModes: { label: string; value: ThinkingMode }[] = [
  { label: 'Enable', value: 'enabled' },
  { label: 'Disable (Recommended)', value: 'disabled' },
  { label: 'Default', value: 'default' },
]

const toUiInsertionMode = (value?: string) => {
  const v = String(value || '').trim().toLowerCase()
  if (v === 'add') return 'append'
  if (v === 'newline') return 'newline'
  return 'replace'
}
const toConfigTranslationMode = (value?: string) => {
  const v = String(value || '').trim().toLowerCase()
  if (v === 'append') return 'add'
  if (v === 'newline') return 'newline'
  return 'replace'
}

const defaultProviderPresets: ProviderPreset[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    api_format: 'openai_compatible',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4.1-mini',
    notes: 'Official OpenAI endpoint',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    api_format: 'openai_compatible',
    base_url: 'https://openrouter.ai/api/v1',
    default_model: 'stepfun/step-3.5-flash:free',
    notes: 'Multi-vendor gateway, often has free/community models',
  },
  {
    id: 'nvidia',
    name: 'NVIDIA API Catalog',
    api_format: 'openai_compatible',
    base_url: 'https://integrate.api.nvidia.com/v1',
    default_model: 'moonshotai/kimi-k2.5',
    notes: 'Direct NVIDIA chat completions endpoint',
  },
  {
    id: 'dashscope',
    name: 'Alibaba DashScope',
    api_format: 'openai_compatible',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    default_model: 'qwen-max',
    notes: 'Qwen models via OpenAI-compatible endpoint',
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    api_format: 'openai_compatible',
    base_url: 'https://api.deepseek.com/v1',
    default_model: 'deepseek-chat',
    notes: 'DeepSeek official endpoint',
  },
  {
    id: 'groq',
    name: 'Groq',
    api_format: 'openai_compatible',
    base_url: 'https://api.groq.com/openai/v1',
    default_model: 'llama-3.3-70b-versatile',
    notes: 'High-speed inference provider',
  },
  {
    id: 'minimax',
    name: 'MiniMax',
    api_format: 'openai_compatible',
    base_url: 'https://api.minimax.chat/v1',
    default_model: 'MiniMax-Text-01',
    notes: 'MiniMax open platform',
  },
  {
    id: 'minimax-cn',
    name: 'MiniMax 国内版',
    api_format: 'openai_compatible',
    base_url: 'https://api.minimaxi.com/v1',
    default_model: 'MiniMax-M2.5',
    notes: 'MiniMax 中国国内官方端点',
  },
  {
    id: 'zhipu',
    name: 'Zhipu GLM',
    api_format: 'openai_compatible',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    default_model: 'glm-4-plus',
    notes: 'GLM models',
  },
  {
    id: 'moonshot',
    name: 'Moonshot',
    api_format: 'openai_compatible',
    base_url: 'https://api.moonshot.cn/v1',
    default_model: 'moonshot-v1-8k',
    notes: 'Kimi models',
  },
  {
    id: 'siliconflow',
    name: 'SiliconFlow',
    api_format: 'openai_compatible',
    base_url: 'https://api.siliconflow.cn/v1',
    default_model: 'Qwen/Qwen2.5-7B-Instruct',
    notes: 'Open-model hosting platform',
  },
  {
    id: 'together',
    name: 'Together AI',
    api_format: 'openai_compatible',
    base_url: 'https://api.together.xyz/v1',
    default_model: 'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo',
    notes: 'Open-model inference provider',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    api_format: 'anthropic',
    base_url: 'https://api.anthropic.com/v1',
    default_model: 'claude-3-5-haiku-latest',
    notes: 'Claude Messages API',
  },
  {
    id: 'google',
    name: 'Google Gemini',
    api_format: 'google',
    base_url: 'https://generativelanguage.googleapis.com/v1beta',
    default_model: 'gemini-2.0-flash',
    notes: 'Gemini API / AI Studio',
  },
  {
    id: 'ollama',
    name: 'Ollama',
    api_format: 'ollama',
    base_url: 'http://127.0.0.1:11434',
    default_model: 'qwen2.5:7b',
    notes: 'Local Ollama server',
  },
  {
    id: 'lmstudio',
    name: 'LM Studio',
    api_format: 'lmstudio',
    base_url: 'http://127.0.0.1:1234/v1',
    default_model: 'local-model',
    notes: 'Local LM Studio OpenAI-compatible server',
  },
  {
    id: 'custom',
    name: 'Custom OpenAI-Compatible',
    api_format: 'openai_compatible',
    base_url: 'https://your-endpoint/v1',
    default_model: 'your-model',
    notes: 'Bring your own OpenAI-compatible endpoint',
  },
]

const fileAccept = '.xlsx,.xls,.csv,.dwg,.dxf'

const isCadFile = (file: File) => /\.(dwg|dxf)$/i.test(file.name)
const getFileKind = (file: File): FileKind => {
  if (isCadFile(file)) return 'cad'
  if (/\.csv$/i.test(file.name)) return 'csv'
  if (/\.(xlsx|xls)$/i.test(file.name)) return 'excel'
  return 'other'
}

const toTitle = (value: string) => {
  const normalized = String(value || '').toLowerCase()
  const labels: Record<string, string> = {
    idle: '待开始',
    queued: '排队中',
    processing: '处理中',
    done: '已完成',
    partial: '部分完成',
    error: '失败',
    cancelled: '已停止',
  }
  return labels[normalized] || value
}

const TranslationWorkbenchPage: React.FC = () => {
  const [workflow, setWorkflow] = useState<'cad' | 'sheet'>('cad')
  const [autoSelectWorkflow, setAutoSelectWorkflow] = useState(true)
  const [insertionMode, setInsertionMode] = useState('replace')
  const [translationRegion, setTranslationRegion] = useState('')
  const [skipTranslation, setSkipTranslation] = useState(false)
  const [provider, setProvider] = useState('custom')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [modelId, setModelId] = useState('')
  const [useSystemProxy, setUseSystemProxy] = useState(false)
  const [forceJson, setForceJson] = useState(true)
  const [targetLang, setTargetLang] = useState('zh')
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>('disabled')
  const [customPrompt, setCustomPrompt] = useState('')
  const [batchSize, setBatchSize] = useState(MAX_BATCH_SIZE)
  const [timeoutSeconds, setTimeoutSeconds] = useState(300)
  const [maxTokens, setMaxTokens] = useState(DEFAULT_MAX_TOKENS)
  const [parallelCount, setParallelCount] = useState(1)
  const [temperature, setTemperature] = useState(0.7)
  const [retryCount, setRetryCount] = useState(2)
  const [rpm, setRpm] = useState(40)
  const [tpm, setTpm] = useState('')
  const [extraBody, setExtraBody] = useState('')
  const [glossaryFile, setGlossaryFile] = useState<File | null>(null)
  const [glossaryCleared, setGlossaryCleared] = useState(false)
  const [files, setFiles] = useState<QueueTask[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [backendTasks, setBackendTasks] = useState<BackendCadTask[]>([])
  const [backendTasksLoading, setBackendTasksLoading] = useState(false)
  const [selectedBackendTaskId, setSelectedBackendTaskId] = useState<string | null>(null)
  const [runtime, setRuntime] = useState<RuntimeSummary>({})
  const [cadDefaults, setCadDefaults] = useState<CadDefaultsSummary>({})
  const [providerPresets, setProviderPresets] = useState<ProviderPreset[]>([])
  const [customProviderName, setCustomProviderName] = useState('')
  const [providerApiKeys, setProviderApiKeys] = useState<Record<string, string>>({})
  const [providerModels, setProviderModels] = useState<Record<string, string>>({})
  const [languageOptions, setLanguageOptions] = useState<LanguageOption[]>(defaultLanguageOptions)
  const [loadingConfig, setLoadingConfig] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [stoppingTasks, setStoppingTasks] = useState(false)
  const [savingCustomProvider, setSavingCustomProvider] = useState(false)
  const [deletingProviderId, setDeletingProviderId] = useState<string | null>(null)
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null)
  const [downloadingPackage, setDownloadingPackage] = useState(false)
  const [configMessage, setConfigMessage] = useState<string>('')
  const [globalMessage, setGlobalMessage] = useState<string>('')
  const [isMainDropActive, setIsMainDropActive] = useState(false)
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    workflow: false,
    cadOptions: false,
    model: false,
    config: false,
    glossary: false,
  })
  const [taskLogs, setTaskLogs] = useState<string>('')
  const [logsLoading, setLogsLoading] = useState(false)

  const mainFileInputRef = useRef<HTMLInputElement | null>(null)
  const glossaryInputRef = useRef<HTMLInputElement | null>(null)
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
    const loadConfig = async () => {
      setLoadingConfig(true)
      try {
        const [configData, providersData, languagesData]: any = await Promise.all([
          apiService.translation.getConfig(),
          apiService.translation.getProviders(),
          apiService.translation.getLanguages(),
        ])

        const runtimeSummary = configData?.runtime || {}
        const cadDefaultsSummary = configData?.cad_defaults || {}
        const resolvedProviderPresets =
          (Array.isArray(providersData?.presets) && providersData.presets.length
            ? providersData.presets
            : Array.isArray(configData?.provider_presets) && configData.provider_presets.length
              ? configData.provider_presets
              : defaultProviderPresets)
        setRuntime(runtimeSummary)
        setCadDefaults(cadDefaultsSummary)
        setProviderPresets(resolvedProviderPresets)
        setLanguageOptions(
          languagesData?.languages
            ? [
                { label: 'Auto Detect', value: 'auto' },
                ...Object.entries(languagesData.languages).map(([value, label]) => ({
                  value,
                  label: String(label),
                })),
              ]
            : defaultLanguageOptions,
        )

        const loadedProvider = runtimeSummary.provider || resolvedProviderPresets[0]?.id || 'custom'
        setProvider(loadedProvider)
        setBaseUrl(runtimeSummary.base_url || '')
        const savedModel = runtimeSummary.model || ''
        setModelId(savedModel)
        setProviderModels((prev) => ({ ...prev, [loadedProvider]: savedModel }))
        setProviderApiKeys(runtimeSummary.provider_api_keys || {})
        // Initialize apiKey from provider-specific keys so the input shows the saved key
        setApiKey(runtimeSummary.provider_api_keys?.[loadedProvider] || '')
        setCustomPrompt(runtimeSummary.custom_system_prompt || '')
        setThinkingMode(
          runtimeSummary.reasoning_enabled
            ? 'enabled'
            : 'disabled',
        )
        setTemperature(normalizeNumber(runtimeSummary.temperature, 0.7, MIN_TEMPERATURE, MAX_TEMPERATURE))
        setTimeoutSeconds(normalizeNumber(runtimeSummary.timeout_seconds, 60, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS))
        setMaxTokens(normalizeNumber(runtimeSummary.max_tokens, DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS, MAX_MAX_TOKENS))
        setBatchSize(normalizeNumber(runtimeSummary.batch_size, MAX_BATCH_SIZE, 1, MAX_BATCH_SIZE))
        setParallelCount(normalizeNumber(runtimeSummary.parallel_count, 1, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT))
        setRetryCount(normalizeNumber(runtimeSummary.retry_count, 2, MIN_RETRY_COUNT, MAX_RETRY_COUNT))
        setRpm(normalizeNumber(runtimeSummary.rpm, 40, MIN_RPM, MAX_RPM))
        setTpm(runtimeSummary.tpm || '')
        setExtraBody(runtimeSummary.extra_body || '')
        setUseSystemProxy(Boolean(runtimeSummary.use_system_proxy ?? false))
        setForceJson(Boolean(runtimeSummary.batch_json ?? true))
        setGlossaryFile(null)
        setGlossaryCleared(false)
        setTargetLang(
          String(
            cadDefaultsSummary.target_language ||
              runtimeSummary.target_language ||
              'zh',
          ).trim() || 'zh',
        )
        setInsertionMode(
          toUiInsertionMode(
            cadDefaultsSummary.translation_mode ||
              runtimeSummary.translation_mode ||
              'replace',
          ),
        )
      } catch (error) {
        setGlobalMessage(getApiErrorMessage(error, 'Config load failed'))
      } finally {
        setLoadingConfig(false)
      }
    }

    void loadConfig()
  }, [])

  useEffect(() => {
    const loadBackendTasks = async () => {
      setBackendTasksLoading(true)
      try {
        const response: any = await apiService.cad.listTasks()
        const tasks = Array.isArray(response?.data) ? response.data : Array.isArray(response) ? response : []
        setBackendTasks(tasks)
        setSelectedBackendTaskId((current) => current || tasks[0]?.task_id || null)
      } catch (error) {
        setGlobalMessage(getApiErrorMessage(error, 'Task list load failed'))
      } finally {
        setBackendTasksLoading(false)
      }
    }

    void loadBackendTasks()
  }, [])

  useEffect(() => {
    if (!backendTasks.length) {
      setSelectedBackendTaskId(null)
      return
    }
    if (!backendTasks.some((item) => item.task_id === selectedBackendTaskId)) {
      setSelectedBackendTaskId(backendTasks[0].task_id)
    }
  }, [backendTasks, selectedBackendTaskId])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshBackendTasks(true)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!globalMessage) return
    const timer = window.setTimeout(() => setGlobalMessage(''), 6000)
    return () => window.clearTimeout(timer)
  }, [globalMessage])

  useEffect(() => {
    if (selectedBackendTaskId) {
      void fetchTaskLogs(selectedBackendTaskId)
    } else {
      setTaskLogs('')
    }
  }, [selectedBackendTaskId])

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

  const builtinProviderIds = useMemo(() => new Set([
    'openai', 'openrouter', 'nvidia', 'dashscope', 'deepseek', 'groq',
    'minimax', 'minimax-cn', 'zhipu', 'moonshot', 'siliconflow',
    'together', 'anthropic', 'google', 'ollama', 'lmstudio', 'custom',
  ]), [])

  const isCustomProvider = (presetId: string) => !builtinProviderIds.has(presetId)

  const loadWorkflowPreset = (nextProvider: string) => {
    setProvider(nextProvider)
    if (nextProvider === 'custom') {
      return
    }
    const preset = providerPresets.find((item) => item.id === nextProvider)
    if (!preset) return
    setBaseUrl(preset.base_url)
    // Prefer user-edited model for this provider, fallback to preset default
    const savedModel = providerModels[nextProvider]
    setModelId(savedModel || preset.default_model)
    // Load provider-specific api key if available; otherwise clear to avoid stale key
    const key = providerApiKeys[nextProvider]
    setApiKey(key || '')
  }

  const saveCustomProviderPreset = async () => {
    const name = customProviderName.trim()
    const url = baseUrl.trim()
    const model = modelId.trim()
    if (!name) {
      MessagePlugin.error('请输入服务商名称')
      return
    }
    if (!url) {
      MessagePlugin.error('请输入基础 URL')
      return
    }
    if (!model) {
      MessagePlugin.error('请输入模型 ID')
      return
    }

    const providerId = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    if (!providerId) {
      MessagePlugin.error('服务商名称无效')
      return
    }
    if (savingCustomProvider) return
    setSavingCustomProvider(true)

    try {
      await apiService.translation.saveCustomProvider({
        id: providerId,
        name,
        base_url: url,
        default_model: model,
        notes: 'Custom provider',
      })
      const providersData: any = await apiService.translation.getProviders()
      const newPresets = providersData?.presets || []
      setProviderPresets(newPresets)
      setProvider(providerId)
      setCustomProviderName('')
      MessagePlugin.success(`已添加自定义服务商: ${name}`)
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, '添加自定义服务商失败'))
    } finally {
      setSavingCustomProvider(false)
    }
  }

  const deleteCustomProviderPreset = async (presetId: string) => {
    if (deletingProviderId) return
    setDeletingProviderId(presetId)
    try {
      await apiService.translation.deleteCustomProvider(presetId)
      const providersData: any = await apiService.translation.getProviders()
      const newPresets = providersData?.presets || []
      setProviderPresets(newPresets)
      if (provider === presetId) {
        setProvider('custom')
      }
      MessagePlugin.success('已删除自定义服务商')
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, '删除自定义服务商失败'))
    } finally {
      setDeletingProviderId(null)
    }
  }

  const getSelectedProviderPreset = () => providerPresets.find((item) => item.id === provider)

  const resolveRuntimeFormat = () => {
    return getSelectedProviderPreset()?.api_format || runtime.format || 'openai_compatible'
  }

  const resolveSystemPromptMode = () => {
    if (customPrompt.trim()) return 'custom'
    return runtime.system_prompt_mode === 'custom' ? 'default' : runtime.system_prompt_mode || 'default'
  }

  const resolveReasoningEnabled = () => {
    if (thinkingMode === 'enabled') return true
    if (thinkingMode === 'disabled') return false
    return Boolean(runtime.reasoning_enabled ?? false)
  }

  const buildRuntimePayload = () => {
    const payload: Record<string, unknown> = {
      provider,
      format: resolveRuntimeFormat(),
      base_url: baseUrl.trim(),
      model: modelId.trim(),
      system_prompt_mode: resolveSystemPromptMode(),
      custom_system_prompt: customPrompt.trim(),
      reasoning_enabled: resolveReasoningEnabled(),
      temperature: normalizeNumber(temperature, 0.7, MIN_TEMPERATURE, MAX_TEMPERATURE),
      timeout_seconds: normalizeNumber(timeoutSeconds, 60, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS),
      max_tokens: normalizeNumber(maxTokens, DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS, MAX_MAX_TOKENS),
      batch_size: clamp(batchSize, 1, MAX_BATCH_SIZE),
      batch_json: forceJson,
      parallel_count: normalizeNumber(parallelCount, 1, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT),
      retry_count: normalizeNumber(retryCount, 2, MIN_RETRY_COUNT, MAX_RETRY_COUNT),
      rpm: normalizeNumber(rpm, 40, MIN_RPM, MAX_RPM),
      tpm: tpm.trim(),
      extra_body: extraBody.trim(),
      use_system_proxy: useSystemProxy,
      target_language: targetLang,
      translation_mode: toConfigTranslationMode(insertionMode),
      font_name: cadDefaults.font_name || 'Times New Roman',
      font_size_reduction: cadDefaults.font_size_reduction ?? 4,
      default_output_dir: cadDefaults.default_output_dir || '',
      converter_backend: cadDefaults.converter_backend || 'auto',
      fallback_models: runtime.fallback_models || [],
    }

    if (glossaryCleared) {
      payload.glossary_file = ''
    } else if (!glossaryFile) {
      payload.glossary_file = runtime.glossary_file || ''
    }

    // Always send api_key (including empty string) so backend can clear stale keys
    payload.api_key = apiKey.trim()

    // Include provider-specific api keys
    const allProviderKeys = { ...providerApiKeys }
    allProviderKeys[provider] = apiKey.trim()
    payload.provider_api_keys = allProviderKeys

    return payload
  }

  const saveRuntimeConfig = async () => {
    setSavingConfig(true)
    try {
      let glossaryPath: string | undefined
      if (glossaryFile) {
        const glossaryForm = new FormData()
        glossaryForm.append('file', glossaryFile)
        const glossaryUploadResult: any = await apiService.translation.uploadGlossary(glossaryForm)
        glossaryPath = String(glossaryUploadResult?.saved_path || '').trim()
      }

      const payload = buildRuntimePayload()
      if (glossaryPath) {
        payload.glossary_file = glossaryPath
      }

      const result: any = await apiService.translation.saveConfig(payload)
      const runtimeSummary = result?.runtime || result || {}
      const cadSummary = result?.cad_defaults || {}
      setRuntime(runtimeSummary)
      setCadDefaults(cadSummary)
      const savedProvider = runtimeSummary.provider || provider
      setProvider(savedProvider)
      setBaseUrl(runtimeSummary.base_url || baseUrl)
      const savedModel = runtimeSummary.model || modelId
      setModelId(savedModel)
      setProviderModels((prev) => ({ ...prev, [savedProvider]: savedModel }))
      setProviderApiKeys(runtimeSummary.provider_api_keys || {})
      setCustomPrompt(runtimeSummary.custom_system_prompt || customPrompt)
      setThinkingMode(runtimeSummary.reasoning_enabled ? 'enabled' : 'disabled')
      setTemperature(normalizeNumber(runtimeSummary.temperature, temperature, MIN_TEMPERATURE, MAX_TEMPERATURE))
      setTimeoutSeconds(normalizeNumber(runtimeSummary.timeout_seconds, timeoutSeconds, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS))
      setMaxTokens(normalizeNumber(runtimeSummary.max_tokens, maxTokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS))
      setBatchSize(normalizeNumber(runtimeSummary.batch_size, batchSize, 1, MAX_BATCH_SIZE))
      setParallelCount(normalizeNumber(runtimeSummary.parallel_count, parallelCount, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT))
      setRetryCount(normalizeNumber(runtimeSummary.retry_count, retryCount, MIN_RETRY_COUNT, MAX_RETRY_COUNT))
      setRpm(normalizeNumber(runtimeSummary.rpm, rpm, MIN_RPM, MAX_RPM))
      setTpm(runtimeSummary.tpm || tpm)
      setExtraBody(runtimeSummary.extra_body || extraBody)
      setUseSystemProxy(Boolean(runtimeSummary.use_system_proxy ?? useSystemProxy))
      setForceJson(Boolean(runtimeSummary.batch_json ?? forceJson))
      setTargetLang(String(cadSummary.target_language || targetLang).trim() || targetLang)
      setInsertionMode(toUiInsertionMode(cadSummary.translation_mode || insertionMode))
      setGlossaryFile(null)
      setGlossaryCleared(false)
      setConfigMessage(result?.message || 'Configuration saved')
      MessagePlugin.success(result?.message || 'Configuration saved')
      void refreshBackendTasks(true)
    } catch (error) {
      const apiError = error as any
      const validationErrors = apiError?.response?.data?.detail
      const batchSizeInvalid =
        Array.isArray(validationErrors) &&
        validationErrors.some((item: any) => String(item?.loc || '').includes('batch_size'))
      const message = batchSizeInvalid
        ? `分块大小最大只能设置为 ${MAX_BATCH_SIZE}`
        : getApiErrorMessage(error, 'Save config failed')
      setConfigMessage(message)
      MessagePlugin.error(message)
    } finally {
      setSavingConfig(false)
    }
  }

  const testRuntimeConnection = async () => {
    setTestingConnection(true)
    try {
      const result: any = await apiService.translation.testConnection(buildRuntimePayload())
      const message = `${result?.message || 'Connection test completed'} (${result?.provider || provider})`
      setConfigMessage(message)
      MessagePlugin.success(message)
    } catch (error) {
      const message = getApiErrorMessage(error, 'Connection test failed')
      setConfigMessage(message)
      MessagePlugin.error(message)
    } finally {
      setTestingConnection(false)
    }
  }

  const refreshBackendTasks = async (silent = false) => {
    if (!silent && backendTasksLoading) return
    if (!silent) setBackendTasksLoading(true)
    try {
      const response: any = await apiService.cad.listTasks()
      const tasks = Array.isArray(response?.data) ? response.data : Array.isArray(response) ? response : []
      setBackendTasks(tasks)
      setSelectedBackendTaskId((current) => current || tasks[0]?.task_id || null)
    } catch (error) {
      if (!silent) {
        setGlobalMessage(getApiErrorMessage(error, 'Task list load failed'))
      }
    } finally {
      if (!silent) setBackendTasksLoading(false)
    }
  }

  const fetchTaskLogs = async (taskId: string) => {
    if (!taskId) return
    setLogsLoading(true)
    try {
      const response: any = await apiService.cad.getTaskLogs(taskId)
      setTaskLogs(response?.data?.logs || response?.logs || '暂无日志')
    } catch (error) {
      setTaskLogs(`获取日志失败: ${getApiErrorMessage(error, 'Unknown error')}`)
    } finally {
      setLogsLoading(false)
    }
  }

  const resumeBackendTask = async (taskId: string) => {
    setProcessing(true)
    try {
      const payload: Record<string, unknown> = {
        target_language: targetLang,
        translation_mode: insertionMode === 'append' ? 'add' : 'replace',
        font_name: cadDefaults.font_name || 'Times New Roman',
        font_size_reduction: cadDefaults.font_size_reduction ?? 4,
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

  const getCadDownloadUrl = (taskId: string, fileType: 'excel' | 'cad' | 'log' | 'translated_cad') =>
    resolveApiUrl(`/api/cad/download/${taskId}/${fileType}`)

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

    const result: any = await apiService.cad.upload(formData)
    const taskId = result?.task_id || result?.data?.task_id || ''

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
      updateQueueTask(task.id, {
        status: 'done',
        progress: 100,
        message: result.translatedCadUrl || result.downloadUrl || result.excelUrl ? '已完成' : '处理完成',
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
    const url = task.kind === 'cad' ? getQueueTaskCadUrl(task) : getQueueTaskExcelUrl(task)
    if (!url) return
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  const downloadOutput = async (task: QueueTask) => {
    const url = task.kind === 'cad' ? getQueueTaskCadUrl(task) : getQueueTaskExcelUrl(task)
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
      return
    }

    const taskId = task.result?.taskId
    if (!taskId) return
    try {
      const blob = await apiService.cad.download(taskId, task.kind === 'cad' ? 'translated_cad' : 'excel')
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
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
      return
    }
    if (task.kind !== 'cad' || !task.result?.taskId) return
    try {
      const blob = await apiService.cad.download(task.result.taskId, 'excel')
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
    window.open(getCadDownloadUrl(task.task_id, fileType), '_blank', 'noopener,noreferrer')
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
        <aside className="sidebar">
          <section className="side-section">
            <button
              className="side-section-header"
              type="button"
              onClick={() => toggleSection('workflow')}
              aria-expanded={!collapsedSections.workflow}
            >
              <span className="side-step">
                <span>1</span>
                <span className="side-icon">▣</span>
              </span>
              <span>选择工作流</span>
              <span className={`side-chevron ${collapsedSections.workflow ? 'side-chevron-collapsed' : ''}`}>▾</span>
            </button>
            <div className={`side-section-body ${collapsedSections.workflow ? 'side-section-body-collapsed' : ''}`}>
              <select className="field field-select" value={workflow} onChange={(e) => setWorkflow(e.target.value as 'cad' | 'sheet')}>
                {workflowOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <label className="toggle-row">
                <span className={`toggle ${autoSelectWorkflow ? 'toggle-on' : ''}`} onClick={() => setAutoSelectWorkflow((v) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">自动选择工作流</span>
              </label>
            </div>
          </section>

          <section className="side-section">
            <button
              className="side-section-header"
              type="button"
              onClick={() => toggleSection('cadOptions')}
              aria-expanded={!collapsedSections.cadOptions}
            >
              <span className="side-step">
                <span>2</span>
                <span className="side-icon">▤</span>
              </span>
              <span>CAD 翻译选项</span>
              <span className={`side-chevron ${collapsedSections.cadOptions ? 'side-chevron-collapsed' : ''}`}>▾</span>
            </button>
            <div className={`side-section-body ${collapsedSections.cadOptions ? 'side-section-body-collapsed' : ''}`}>
              <label className="field-group">
                <span className="field-label">插入模式</span>
                <select className="field field-select" value={insertionMode} onChange={(e) => setInsertionMode(e.target.value)}>
                  {insertionModes.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="helper-copy">选择如何把翻译后的文本插入回表格或单元格中。</p>
              </label>

              {workflow === 'sheet' ? (
                <label className="field-group">
                  <span className="field-label">翻译区域 (可选)</span>
                  <textarea
                    className="field field-textarea"
                    rows={3}
                    placeholder="每行一个区域，例如: Sheet1!A1:B10"
                    value={translationRegion}
                    onChange={(e) => setTranslationRegion(e.target.value)}
                  />
                  <p className="helper-copy">仅 Spreadsheet 翻译会使用这个参数；CAD 流程不会使用。</p>
                </label>
              ) : null}
            </div>
          </section>

          <section className="side-section">
            <button
              className="side-section-header"
              type="button"
              onClick={() => toggleSection('model')}
              aria-expanded={!collapsedSections.model}
            >
              <span className="side-step">
                <span>3</span>
                <span className="side-icon">◉</span>
              </span>
              <span>翻译模型</span>
              <span className={`side-chevron ${collapsedSections.model ? 'side-chevron-collapsed' : ''}`}>▾</span>
            </button>
            <div className={`side-section-body ${collapsedSections.model ? 'side-section-body-collapsed' : ''}`}>
              <label className="toggle-row">
                <span className={`toggle ${skipTranslation ? 'toggle-on' : ''}`} onClick={() => setSkipTranslation((v) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">跳过翻译</span>
              </label>

              <label className="field-group">
                <span className="field-label">选择平台</span>
                <select className="field field-select" value={provider} onChange={(e) => loadWorkflowPreset(e.target.value)} disabled={loadingConfig}>
                  {providerPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                  <option value="custom">Custom (添加新服务商)</option>
                </select>

                {providerPresets.filter((p) => isCustomProvider(p.id)).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <span className="field-label" style={{ fontSize: 12 }}>已添加的自定义</span>
                    {providerPresets.filter((p) => isCustomProvider(p.id)).map((preset) => (
                      <div
                        key={preset.id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 8,
                          marginTop: 4,
                          padding: '4px 8px',
                          background: '#f5f5f5',
                          borderRadius: 4,
                          fontSize: 13,
                        }}
                      >
                        <span style={{ color: '#333' }}>{preset.name}</span>
                        <button
                          type="button"
                          className="small-link-button"
                          disabled={deletingProviderId === preset.id}
                          onClick={() => void deleteCustomProviderPreset(preset.id)}
                          style={{ color: '#d32f2f', fontSize: 12 }}
                        >
                          {deletingProviderId === preset.id ? '删除中...' : '删除'}
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {provider === 'custom' ? (
                  <>
                    <span className="field-label" style={{ marginTop: 8, display: 'block' }}>服务商名称</span>
                    <input
                      className="field field-input"
                      type="text"
                      value={customProviderName}
                      placeholder="例如：My API"
                      onChange={(e) => setCustomProviderName(e.target.value)}
                    />
                    <span className="field-label" style={{ marginTop: 8, display: 'block' }}>基础 URL</span>
                    <input
                      className="field field-input mono"
                      type="text"
                      value={baseUrl}
                      placeholder="https://your-endpoint/v1"
                      onChange={(e) => setBaseUrl(e.target.value)}
                    />
                    <span className="field-label" style={{ marginTop: 8, display: 'block' }}>模型 ID</span>
                    <input
                      className="field field-input"
                      type="text"
                      value={modelId}
                      placeholder="例如：gpt-4o"
                      onChange={(e) => {
                        const v = e.target.value
                        setModelId(v)
                        setProviderModels((prev) => ({ ...prev, [provider]: v }))
                      }}
                    />
                    <button
                      type="button"
                      className="small-link-button"
                      style={{ marginTop: 10, fontSize: 13 }}
                      disabled={savingCustomProvider}
                      onClick={() => void saveCustomProviderPreset()}
                    >
                      {savingCustomProvider ? '添加中...' : '+ 添加为预设'}
                    </button>
                  </>
                ) : (
                  <p className="helper-copy">
                    Base URL: <span className="accent-text">{baseUrl || 'not configured'}</span>
                  </p>
                )}
              </label>

              <label className="field-group">
                <span className="field-label row-label">
                  API Key
                  <button type="button" className="small-link-button" onClick={() => setShowApiKey((v) => !v)}>
                    {showApiKey ? 'Hide' : 'Show'}
                  </button>
                </span>
                <input
                  className="field field-input mono"
                  type={showApiKey ? 'text' : 'password'}
                  value={apiKey}
                  placeholder={
                    providerApiKeys[provider]
                      ? `已配置 (${providerApiKeys[provider].slice(0, 4)}...)`
                      : runtime.api_key_configured
                        ? runtime.masked_api_key || 'configured'
                        : '********'
                  }
                  onChange={(e) => {
                    const newKey = e.target.value
                    setApiKey(newKey)
                    setProviderApiKeys((prev) => ({ ...prev, [provider]: newKey }))
                  }}
                />
              </label>

              {provider !== 'custom' && (
                <label className="field-group">
                  <span className="field-label">模型 ID</span>
                  <input
                    className="field field-input"
                    type="text"
                    value={modelId}
                    onChange={(e) => {
                      const v = e.target.value
                      setModelId(v)
                      setProviderModels((prev) => ({ ...prev, [provider]: v }))
                    }}
                  />
                </label>
              )}

              <label className="toggle-row">
                <span className={`toggle ${useSystemProxy ? 'toggle-on' : ''}`} onClick={() => setUseSystemProxy((v) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">启用系统代理</span>
              </label>

              <label className="toggle-row">
                <span className={`toggle ${forceJson ? 'toggle-on' : ''}`} onClick={() => setForceJson((v) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">强制 JSON 输出</span>
                <button type="button" className="help-dot" aria-label="help">
                  ?
                </button>
              </label>
            </div>
          </section>

          <section className="side-section">
            <button
              className="side-section-header"
              type="button"
              onClick={() => toggleSection('config')}
              aria-expanded={!collapsedSections.config}
            >
              <span className="side-step">
                <span>4</span>
                <span className="side-icon">☰</span>
              </span>
              <span>翻译配置</span>
              <span className={`side-chevron ${collapsedSections.config ? 'side-chevron-collapsed' : ''}`}>▾</span>
            </button>
            <div className={`side-section-body ${collapsedSections.config ? 'side-section-body-collapsed' : ''}`}>
              <label className="field-group">
                <span className="field-label">目标语言</span>
                <select className="field field-select" value={targetLang} onChange={(e) => setTargetLang(e.target.value)}>
                  {languageOptions
                    .filter((option) => option.value !== 'auto')
                    .map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                </select>
              </label>

              <label className="field-group">
                <span className="field-label row-label">
                  <span>思考模式</span>
                  <button type="button" className="help-dot" aria-label="help">
                    ?
                  </button>
                </span>
                <div className="segmented">
                  {thinkingModes.map((mode) => (
                    <button
                      key={mode.value}
                      type="button"
                      className={`segment-button ${thinkingMode === mode.value ? 'segment-active' : ''}`}
                      onClick={() => setThinkingMode(mode.value)}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </label>

              <label className="field-group">
                <span className="field-label">自定义 Prompt</span>
                <textarea
                  className="field field-textarea"
                  rows={3}
                  placeholder="例如：人名保留原文不翻译"
                  value={customPrompt}
                  onChange={(e) => setCustomPrompt(e.target.value)}
                />
              </label>

              <div className="slider-group">
                <div className="slider-head">
                  <span>分块大小: {batchSize}</span>
                  <button type="button" className="mini-button" onClick={() => setBatchSize(MAX_BATCH_SIZE)}>
                    重置
                  </button>
                </div>
                <input className="range-input" type="range" min="1" max={MAX_BATCH_SIZE} value={batchSize} onChange={(e) => setBatchSize(clamp(Number(e.target.value), 1, MAX_BATCH_SIZE))} />
              </div>

              <div className="numeric-grid">
                <label className="field-group">
                  <span className="field-label">
                    Timeout <small className="field-note">(秒)</small>
                  </span>
                  <input className="field field-input" type="number" min={MIN_TIMEOUT_SECONDS} max={MAX_TIMEOUT_SECONDS} value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(normalizeNumber(e.target.value, timeoutSeconds, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS))} />
                </label>
                <label className="field-group">
                  <span className="field-label">
                    Max Tokens <small className="field-note">(输出上限)</small>
                  </span>
                  <input className="field field-input" type="number" min={MIN_MAX_TOKENS} max={MAX_MAX_TOKENS} value={maxTokens} onChange={(e) => setMaxTokens(normalizeNumber(e.target.value, maxTokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS))} />
                </label>
              </div>

              <div className="slider-group">
                <div className="slider-head">
                  <span>并发数: {parallelCount}</span>
                  <button type="button" className="mini-button" onClick={() => setParallelCount(MIN_PARALLEL_COUNT)}>
                    重置
                  </button>
                </div>
                <input className="range-input" type="range" min={MIN_PARALLEL_COUNT} max={MAX_PARALLEL_COUNT} value={parallelCount} onChange={(e) => setParallelCount(normalizeNumber(e.target.value, parallelCount, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT))} />
              </div>

              <div className="slider-group">
                <div className="slider-head">
                  <span>Temperature: {temperature.toFixed(1)}</span>
                </div>
                <input className="range-input" type="range" min={MIN_TEMPERATURE} max={MAX_TEMPERATURE} step="0.1" value={temperature} onChange={(e) => setTemperature(normalizeNumber(e.target.value, temperature, MIN_TEMPERATURE, MAX_TEMPERATURE))} />
              </div>

              <div className="slider-group">
                <div className="slider-head">
                  <span>重试次数: {retryCount}</span>
                </div>
                <input className="range-input" type="range" min={MIN_RETRY_COUNT} max={MAX_RETRY_COUNT} value={retryCount} onChange={(e) => setRetryCount(normalizeNumber(e.target.value, retryCount, MIN_RETRY_COUNT, MAX_RETRY_COUNT))} />
              </div>

              <div className="numeric-grid">
                <label className="field-group">
                  <span className="field-label">
                    RPM <small className="field-note">(每分钟请求数)</small>
                  </span>
                  <input className="field field-input" type="number" min={MIN_RPM} max={MAX_RPM} value={rpm} onChange={(e) => setRpm(normalizeNumber(e.target.value, rpm, MIN_RPM, MAX_RPM))} />
                </label>
                <label className="field-group">
                  <span className="field-label">
                    TPM <small className="field-note">(每分钟 Token)</small>
                  </span>
                  <input className="field field-input" type="text" placeholder="留空为无限制" value={tpm} onChange={(e) => setTpm(e.target.value)} />
                </label>
              </div>

              <label className="field-group">
                <span className="field-label row-label">
                  <span>Extra Body</span>
                  <small className="field-note">(JSON)</small>
                  <button type="button" className="help-dot" aria-label="help">
                    ?
                  </button>
                </span>
                <textarea
                  className="field field-textarea mono small-textarea"
                  rows={2}
                  placeholder='例如: {"enable_thinking": true}'
                  value={extraBody}
                  onChange={(e) => setExtraBody(e.target.value)}
                />
              </label>

              <div className="action-row config-actions">
                <Button
                  type="button"
                  theme="primary"
                  size="small"
                  loading={savingConfig}
                  disabled={savingConfig || testingConnection || loadingConfig}
                  onClick={() => void saveRuntimeConfig()}
                >
                  {savingConfig ? '保存中...' : '保存配置'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="small"
                  loading={testingConnection}
                  disabled={testingConnection || savingConfig || loadingConfig}
                  onClick={() => void testRuntimeConnection()}
                >
                  {testingConnection ? '测试中...' : '测试连接'}
                </Button>
              </div>

              <p className="tiny-note">
                这里的参数都会同步到后端配置文件，并在下次打开时回填。保存后会更新当前运行配置。
              </p>
            </div>
          </section>

          <section className="side-section">
            <button
              className="side-section-header"
              type="button"
              onClick={() => toggleSection('glossary')}
              aria-expanded={!collapsedSections.glossary}
            >
              <span className="side-step">
                <span>5</span>
                <span className="side-icon">▸</span>
              </span>
              <span>术语表</span>
              <span className={`side-chevron ${collapsedSections.glossary ? 'side-chevron-collapsed' : ''}`}>▾</span>
            </button>
            <div className={`side-section-body ${collapsedSections.glossary ? 'side-section-body-collapsed' : ''}`}>
              <label className="glossary-dropzone">
                <input
                  ref={glossaryInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden-input"
                  onChange={(event) => {
                    setGlossaryFile(event.target.files?.[0] || null)
                    setGlossaryCleared(false)
                  }}
                />
                <CloudUploadIcon size="32px" />
                <p>{glossaryFile ? glossaryFile.name : runtime.glossary_file ? runtime.glossary_file.split(/[\\/]/).pop() : '点击上传或拖拽术语表文件'}</p>
              </label>

              <div className="action-row">
                <Button theme="primary" size="small" onClick={() => glossaryInputRef.current?.click()}>
                  <DownloadIcon className="btn-icon" />
                  选择文件
                </Button>
                <Button size="small" variant="outline" disabled={!glossaryFile} onClick={() => glossaryFile ? window.open(URL.createObjectURL(glossaryFile), '_blank') : undefined}>
                  <span className="btn-icon">⌕</span>
                  查看
                </Button>
                <button
                  type="button"
                  className="text-button danger"
                  disabled={!glossaryFile && (!runtime.glossary_file || glossaryCleared)}
                  onClick={() => { setGlossaryFile(null); setGlossaryCleared(true) }}
                >
                  清空
                </button>
              </div>

              <p className="tiny-note">可选项。支持 .csv / .xlsx / .xls，保存配置后会上传并写入统一配置。</p>
            </div>
          </section>
        </aside>

        <main className="workspace">
          <section className="workspace-hero">
            <div className="workspace-intro">
              <h1>上传文件</h1>
              <p>上传 XLSX、CSV、DWG 或 DXF 文件，自动完成翻译处理。</p>
            </div>

            <input
              id="main-upload-input"
              ref={mainFileInputRef}
              type="file"
              accept={fileAccept}
              multiple
              className="hidden-input"
              onChange={(event) => {
                appendFiles(event.target.files)
                event.currentTarget.value = ''
              }}
            />
            <label
              htmlFor="main-upload-input"
              className={`drop-panel ${isMainDropActive ? 'drop-panel-active' : ''}`}
              onDragEnter={handleMainDragOver}
              onDragOver={handleMainDragOver}
              onDragLeave={handleMainDragLeave}
              onDrop={handleMainDrop}
            >
              <CloudUploadIcon size="52px" />
              <div className="drop-copy">
                <span className="drop-click">点击上传</span>
                <span>或拖拽到这里</span>
              </div>
              <p className="tiny-note">支持 .xlsx、.xls、.csv、.dwg、.dxf，单文件最大 50MB</p>
            </label>

            <div className="action-row">
              <label htmlFor="main-upload-input" className="upload-action">
                <CloudUploadIcon className="btn-icon" />
                选择文件
              </label>
            </div>

            <div className="pending-block">
              <div className="section-subtitle">待处理任务</div>
              {hasLocalTasks ? (
                <div className="task-list">
                  {files.map((task) => (
                    <div
                      key={task.id}
                      className={`task-row ${selectedTaskId === task.id ? 'task-row-active' : ''}`}
                      onClick={() => {
                        setSelectedTaskId(task.id)
                        if (task.result?.taskId) {
                          setSelectedBackendTaskId(task.result.taskId)
                        }
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="task-main">
                        <strong>{task.file.name}</strong>
                        <small>
                          {task.source === 'backend'
                            ? `CAD · ${task.result?.taskId || '-'}`
                            : `${task.kind.toUpperCase()} · ${Math.round(task.file.size / 1024)} KB`}
                        </small>
                      </div>
                      <div className="task-row-actions">
                        <span className={`status-pill status-${task.status}`}>{toTitle(task.status)}</span>
                        {task.status === 'done' ? (
                          <>
                            <button
                              type="button"
                              className="small-link-button"
                              disabled={processing || task.source === 'backend'}
                              onClick={(event) => {
                                event.stopPropagation()
                                if (task.source !== 'backend') {
                                  void rerunTask(task)
                                }
                              }}
                            >
                              重新执行
                            </button>
                            <button
                              type="button"
                              className="small-link-button"
                              disabled={!task.result?.downloadUrl && !task.result?.translatedCadUrl && !task.result?.excelUrl && !task.result?.taskId}
                              onClick={(event) => {
                                event.stopPropagation()
                                void downloadOutput(task)
                              }}
                            >
                              下载
                            </button>
                          </>
                        ) : task.status === 'idle' ? (
                          <button
                            type="button"
                            className="small-link-button"
                            disabled={processing}
                            onClick={(event) => {
                              event.stopPropagation()
                              void startTask(task)
                            }}
                          >
                            开始任务
                          </button>
                        ) : task.status === 'cancelled' || task.status === 'error' ? (
                          <button
                            type="button"
                            className="small-link-button"
                            disabled={processing}
                            onClick={(event) => {
                              event.stopPropagation()
                              if (task.source === 'backend' && task.result?.taskId) {
                                void resumeBackendTask(task.result.taskId)
                              } else {
                                void startTask(task)
                              }
                            }}
                          >
                            {task.source === 'backend' ? '继续' : '重新开始'}
                          </button>
                        ) : task.source === 'backend' ? (
                          <button type="button" className="small-link-button" disabled>
                            {task.message}
                          </button>
                        ) : null}
                        {task.source !== 'backend' ? (
                          <button
                            type="button"
                            className="inline-delete"
                            onClick={(event) => {
                              event.stopPropagation()
                              removeTask(task.id)
                            }}
                            disabled={task.status === 'processing'}
                            aria-label={`删除 ${task.file.name}`}
                          >
                            <DeleteIcon />
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              ) : backendTasks.length ? (
                <div className="task-list">
                  {backendTasks.map((task) => {
                    const status = getBackendTaskStatus(task)
                    const selected = selectedBackendTaskId === task.task_id
                    const isCompleteLike = status === 'done' || status === 'partial'
                    const canDownloadCad = Boolean(task.files?.translated_cad_file && isCompleteLike)
                    const canDownloadExcel = Boolean(task.files?.excel_file && isCompleteLike)

                    return (
                      <div
                        key={task.task_id}
                        className={`task-row ${selected ? 'task-row-active' : ''}`}
                        onClick={() => setSelectedBackendTaskId(task.task_id)}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="task-main">
                          <strong>{task.original_filename}</strong>
                          <small>
                            CAD · {task.task_id} · {task.translatable_count ?? task.text_count ?? 0} 条待译
                          </small>
                        </div>
                        <div className="task-row-actions">
                          <span className={`status-pill status-${status}`}>{getBackendTaskStatusLabel(task)}</span>
                          {canDownloadCad ? (
                            <button
                              type="button"
                              className="small-link-button"
                              onClick={(event) => {
                                event.stopPropagation()
                                downloadBackendTaskOutput(task, 'translated_cad')
                              }}
                            >
                              下载 CAD
                            </button>
                          ) : canDownloadExcel ? (
                            <button
                              type="button"
                              className="small-link-button"
                              onClick={(event) => {
                                event.stopPropagation()
                                downloadBackendTaskOutput(task, 'excel')
                              }}
                            >
                              下载 Excel
                            </button>
                          ) : null}
                          {status === 'partial' ? (
                            <button
                              type="button"
                              className="small-link-button"
                              disabled={processing}
                              onClick={(event) => {
                                event.stopPropagation()
                                void resumeBackendTask(task.task_id)
                              }}
                            >
                              继续翻译
                            </button>
                          ) : status === 'cancelled' || status === 'error' ? (
                            <>
                              <button
                                type="button"
                                className="small-link-button"
                                disabled={processing}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void resumeBackendTask(task.task_id)
                                }}
                              >
                                继续
                              </button>
                              <button
                                type="button"
                                className="small-link-button"
                                disabled={processing}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void restartBackendTask(task)
                                }}
                              >
                                重新开始
                              </button>
                            </>
                          ) : !canDownloadCad && !canDownloadExcel ? (
                            <button type="button" className="small-link-button" disabled>
                              {getBackendStageLabel(task.stage)}
                            </button>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="empty-card">暂时还没有选择文件。</div>
              )}
            </div>

            {/* Terminal Log Panel */}
            <div className="terminal-block" style={{ marginTop: 16 }}>
              <div className="section-subtitle" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>进程日志</span>
                {logsLoading && <span style={{ fontSize: 12, color: '#888' }}>加载中...</span>}
              </div>
              <pre
                className="terminal-pre"
                style={{
                  background: '#1e1e1e',
                  color: '#d4d4d4',
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 12,
                  fontFamily: 'Consolas, "Courier New", monospace',
                  maxHeight: 240,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  marginTop: 8,
                }}
              >
                {taskLogs || '暂无日志'}
              </pre>
            </div>

            <div className="workspace-actions">
              <Button
                theme="primary"
                icon={<DownloadIcon />}
                disabled={!packageTaskIds.length || downloadingPackage}
                loading={downloadingPackage}
                onClick={() => {
                  if (!packageTaskIds.length || downloadingPackage) return
                  void downloadPackage(packageTaskIds)
                }}
              >
                {downloadingPackage ? '打包下载中...' : currentActionLabel}
              </Button>
            </div>
          </section>

          <section className="detail-stack">
            <article className="detail-card">
              <div className="detail-head">
                <div>
                  <div className="detail-label">当前任务</div>
                  <h2>{detailTaskName}</h2>
                </div>
                <div className="detail-actions-top">
                  <Button
                    size="small"
                    theme="primary"
                    disabled={startActionDisabled}
                    loading={processing}
                    onClick={() => {
                      if (selectedLocalActionableTask?.status === 'done') {
                        void rerunTask(selectedLocalActionableTask)
                        return
                      }
                      if (!nextStartableTask) return
                      void startTask(nextStartableTask)
                    }}
                  >
                    {startActionLabel}
                  </Button>
                  <Button
                    size="small"
                    variant="outline"
                    disabled={!hasStoppableTasks}
                    loading={stoppingTasks}
                    onClick={() => void stopAllTasks()}
                  >
                    停止全部任务
                  </Button>
                  <button
                    type="button"
                    className={`icon-button ${backendTasksLoading ? 'icon-button-loading' : ''}`}
                    onClick={() => void refreshBackendTasks()}
                    disabled={backendTasksLoading}
                    aria-label="刷新任务列表"
                    aria-busy={backendTasksLoading}
                  >
                    <RefreshIcon />
                  </button>
                </div>
              </div>

              {contentTask ? (
                <div className="detail-grid">
                  <div className="detail-item">
                    <span>状态</span>
                    <strong>{toTitle(contentTask.status)}</strong>
                  </div>
                  <div className="detail-item">
                    <span>进度</span>
                    <strong>{contentTask.progress}%</strong>
                  </div>
                  <div className="detail-item">
                    <span>类型</span>
                    <strong>{contentTask.kind.toUpperCase()}</strong>
                  </div>
                  <div className="detail-item">
                    <span>任务 ID</span>
                    <strong>{contentTask.result?.taskId || '-'}</strong>
                  </div>
                </div>
              ) : detailBackendTask ? (
                <div className="detail-grid">
                  <div className="detail-item">
                    <span>状态</span>
                    <strong>{detailTaskStatus}</strong>
                  </div>
                  <div className="detail-item">
                    <span>进度</span>
                    <strong>{detailTaskProgress}%</strong>
                  </div>
                  <div className="detail-item">
                    <span>类型</span>
                    <strong>{detailTaskType}</strong>
                  </div>
                  <div className="detail-item">
                    <span>任务 ID</span>
                    <strong>{detailTaskId}</strong>
                  </div>
                </div>
              ) : (
                <div className="empty-card">选择一个任务后，可以查看状态、日志和输出文件。</div>
              )}
            </article>

            <article className="detail-card">
              <div className="detail-head">
                <div>
                  <div className="detail-label">LLM 监控</div>
                  <h2>翻译进度</h2>
                </div>
              </div>

              {detailBackendTask ? (
                <>
                  <div className="detail-grid">
                    <div className="detail-item">
                      <span>阶段</span>
                      <strong>{detailTaskStage}</strong>
                    </div>
                    <div className="detail-item">
                      <span>分块进度</span>
                      <strong>
                        {detailBackendTask.completed_chunks ?? 0} / {detailBackendTask.total_chunks ?? 0}
                      </strong>
                    </div>
                    <div className="detail-item">
                      <span>文本进度</span>
                      <strong>
                        {(() => {
                          const tc = detailBackendTask.translated_count
                          const safeTc = typeof tc === 'number' ? tc : (detailBackendTask.translation_count ?? 0)
                          const total = detailBackendTask.translatable_count ?? detailBackendTask.text_count ?? 0
                          return `${safeTc} / ${total}`
                        })()}
                      </strong>
                    </div>
                    <div className="detail-item">
                      <span>模型</span>
                      <strong>{detailBackendTask.provider ? `${detailBackendTask.provider} / ${detailBackendTask.model || '-'}` : '-'}</strong>
                    </div>
                  </div>
                  <div className="monitor-progress">
                    <div className="monitor-progress-bar">
                      <div className="monitor-progress-fill" style={{ width: `${detailTaskProgress}%` }} />
                    </div>
                    <div className="monitor-progress-meta">
                      <span>{detailTaskProgress}%</span>
                      <span>批大小 {detailBackendTask.batch_size || '-'}</span>
                      <span>重试 {detailBackendTask.retry_count ?? '-'}</span>
                    </div>
                  </div>
                  {detailBackendTask.last_error ? <div className="monitor-error">{detailBackendTask.last_error}</div> : null}
                </>
              ) : (
                <div className="empty-card">上传 CAD 文件后，这里会显示提取、分块翻译和回写进度。</div>
              )}
            </article>

            <article className="detail-card">
              <div className="detail-label">连接结果</div>
              <div className={`result-banner ${configMessage ? 'result-banner-active' : ''}`}>
                {configMessage || '填写平台、接口地址和 API Key 后，可在这里查看测试结果。'}
              </div>
            </article>

            <article className="detail-card">
              <div className="detail-head">
                <div>
                  <div className="detail-label">下载</div>
                  <h2>输出结果</h2>
                </div>
              </div>

              <div className="download-grid">
                <div className="download-card">
                  <div className="download-title">Excel / 表格输出</div>
                  <div className="download-meta">{outputExcelReady ? '已就绪' : '等待处理完成'}</div>
                  <Button
                    theme="primary"
                    disabled={!outputExcelReady}
                    onClick={() => {
                      if (outputSourceTask) {
                        void downloadOutputExcel(outputSourceTask)
                        return
                      }
                      if (outputBackendTask) {
                        downloadBackendTaskOutput(outputBackendTask, 'excel')
                      }
                    }}
                  >
                    <DownloadIcon className="btn-icon" />
                    下载 Excel
                  </Button>
                </div>

                <div className="download-card">
                  <div className="download-title">翻译后 CAD</div>
                  <div className="download-meta">{outputCadReady ? '已就绪' : '等待回写完成'}</div>
                  <Button
                    variant="outline"
                    disabled={!outputCadReady}
                    onClick={() => {
                      if (outputSourceTask?.result?.translatedCadUrl) {
                        void openOutput(outputSourceTask)
                        return
                      }
                      if (outputBackendTask?.files?.translated_cad_file) {
                        openBackendTaskFile(outputBackendTask, 'translated_cad')
                      }
                    }}
                  >
                    <DownloadIcon className="btn-icon" />
                    打开 CAD
                  </Button>
                </div>
              </div>
            </article>

            <article className="detail-card">
              <div className="detail-head">
                <div>
                  <div className="detail-label">统计</div>
                  <h2>最近任务</h2>
                </div>
              </div>

              <div className="summary-grid">
                <div className="summary-card">
                  <span>总数</span>
                  <strong>{backendTaskStats.total}</strong>
                </div>
                <div className="summary-card">
                  <span>完成</span>
                  <strong>{backendTaskStats.done}</strong>
                </div>
                <div className="summary-card">
                  <span>进行中</span>
                  <strong>{backendTaskStats.active}</strong>
                </div>
                <div className="summary-card">
                  <span>Excel 就绪</span>
                  <strong>{backendTaskStats.excelReady}</strong>
                </div>
                <div className="summary-card">
                  <span>CAD 就绪</span>
                  <strong>{backendTaskStats.translated}</strong>
                </div>
              </div>
            </article>

            <article className="detail-card">
              <div className="detail-head">
                <div>
                  <div className="detail-label">任务历史</div>
                  <h2>后端 CAD 任务</h2>
                </div>
                <div className="detail-actions-top">
                  <button
                    type="button"
                    className={`icon-button ${backendTasksLoading ? 'icon-button-loading' : ''}`}
                    onClick={() => void refreshBackendTasks()}
                    disabled={backendTasksLoading}
                    aria-label="刷新后端任务"
                    aria-busy={backendTasksLoading}
                  >
                    <RefreshIcon />
                  </button>
                </div>
              </div>

              {backendTasksLoading ? (
                <div className="empty-card">正在加载后端任务...</div>
              ) : backendTasks.length ? (
                <div className="backend-task-list">
                  {backendTasks.map((task) => {
                    const status = getBackendTaskStatus(task)
                    const selected = selectedBackendTaskId === task.task_id
                    return (
                      <div
                        key={task.task_id}
                        className={`task-row backend-task-row ${selected ? 'task-row-active' : ''}`}
                        onClick={() => setSelectedBackendTaskId(task.task_id)}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="task-main">
                          <strong>{task.original_filename}</strong>
                          <small>
                            {task.task_id} · {task.translatable_count ?? task.text_count ?? 0} 条待译 · {task.translation_count ?? 0} 条翻译
                          </small>
                        </div>
                        <span className={`status-pill status-${status}`}>{getBackendTaskStatusLabel(task)}</span>
                        <div className="backend-task-actions">
                          <button
                            type="button"
                            className="text-button"
                            onClick={(event) => {
                              event.stopPropagation()
                              openBackendTaskFile(task, 'excel')
                            }}
                            disabled={!(task.files?.excel_file && (status === 'done' || status === 'partial'))}
                          >
                            下载翻译 Excel
                          </button>
                          <button
                            type="button"
                            className="text-button"
                            onClick={(event) => {
                              event.stopPropagation()
                              openBackendTaskFile(task, 'translated_cad')
                            }}
                            disabled={!task.files?.translated_cad_file}
                          >
                            打开 CAD
                          </button>
                          {status === 'partial' || status === 'error' || status === 'cancelled' ? (
                            <button
                              type="button"
                              className="text-button"
                              disabled={processing}
                              onClick={(event) => {
                                event.stopPropagation()
                                void resumeBackendTask(task.task_id)
                              }}
                            >
                              {processing ? '恢复中...' : status === 'partial' ? '继续翻译' : '继续'}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="text-button"
                            onClick={(event) => {
                              event.stopPropagation()
                              openBackendTaskFile(task, 'log')
                            }}
                            disabled={!task.files?.log_file}
                          >
                            查看日志
                          </button>
                          <button
                            type="button"
                            className="text-button danger"
                            disabled={deletingTaskId === task.task_id}
                            onClick={(event) => {
                              event.stopPropagation()
                              void deleteBackendTask(task.task_id)
                            }}
                          >
                            {deletingTaskId === task.task_id ? '删除中...' : '删除'}
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="empty-card">暂时还没有后端 CAD 任务。</div>
              )}

              {selectedBackendTask ? (
                <div className="backend-task-detail">
                  {(() => {
                    const status = getBackendTaskStatus(selectedBackendTask)
                    const isCompleteLike = status === 'done' || status === 'partial'
                    const translatedCadReady = Boolean(selectedBackendTask.files?.translated_cad_file && isCompleteLike)
                    const translatedExcelReady = Boolean(selectedBackendTask.files?.excel_file && isCompleteLike)

                    return (
                      <>
                  <div className="detail-grid">
                    <div className="detail-item">
                      <span>已选任务</span>
                      <strong>{selectedBackendTask.original_filename}</strong>
                    </div>
                    <div className="detail-item">
                      <span>任务 ID</span>
                      <strong>{selectedBackendTask.task_id}</strong>
                    </div>
                    <div className="detail-item">
                      <span>状态</span>
                      <strong>{getBackendTaskStatusLabel(selectedBackendTask)}</strong>
                    </div>
                    <div className="detail-item">
                      <span>输出文件</span>
                      <strong>{selectedBackendOutputCount}</strong>
                    </div>
                  </div>
                  <div className="action-row backend-detail-actions">
                    <Button
                      size="small"
                      theme="primary"
                      disabled={!translatedCadReady}
                      onClick={() => downloadBackendTaskOutput(selectedBackendTask, 'translated_cad')}
                    >
                      下载 CAD
                    </Button>
                    <Button
                      size="small"
                      variant="outline"
                      disabled={!translatedExcelReady}
                      onClick={() => downloadBackendTaskOutput(selectedBackendTask, 'excel')}
                    >
                      下载翻译 Excel
                    </Button>
                    {status === 'partial' || status === 'error' || status === 'cancelled' ? (
                      <Button
                        size="small"
                        variant="outline"
                        disabled={processing}
                        loading={processing}
                        onClick={() => void resumeBackendTask(selectedBackendTask.task_id)}
                      >
                        {status === 'partial' ? '继续翻译' : '继续'}
                      </Button>
                    ) : null}
                    <Button
                      size="small"
                      variant="outline"
                      disabled={!selectedBackendTask.files?.log_file}
                      onClick={() => openBackendTaskFile(selectedBackendTask, 'log')}
                    >
                      查看日志
                    </Button>
                  </div>
                      </>
                    )
                  })()}
                </div>
              ) : null}
            </article>
          </section>
        </main>
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
