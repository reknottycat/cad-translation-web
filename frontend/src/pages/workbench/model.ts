import { resolveApiUrl } from '../../services/api'

export type FileKind = 'cad' | 'excel' | 'csv' | 'other'
export type TaskStatus = 'idle' | 'queued' | 'processing' | 'done' | 'partial' | 'error' | 'cancelled'
export type ThinkingMode = 'enabled' | 'disabled' | 'default'
export interface LanguageOption { label: string; value: string }
export interface ProviderPreset { id: string; name: string; api_format?: string; base_url: string; default_model: string; notes: string }
export interface ProviderProfile { format?: string; base_url?: string; model?: string; reasoning_enabled?: boolean; timeout_seconds?: number; temperature?: number; max_tokens?: number }
export interface ProviderCredentialStatus { configured: boolean; source: string; masked?: string | null }
export interface FallbackModel { provider: string; format: string; base_url: string; model: string; reasoning_enabled?: boolean }
export interface RuntimeSummary {
  provider?: string; format?: string; base_url?: string; model?: string
  api_key_configured?: boolean; api_key_source?: string; masked_api_key?: string
  reasoning_enabled?: boolean; system_prompt_mode?: string; custom_system_prompt?: string
  custom_system_prompt_configured?: boolean; glossary_file?: string; timeout_seconds?: number
  temperature?: number; max_tokens?: number; batch_size?: number; batch_json?: boolean
  parallel_count?: number; retry_count?: number; rpm?: number; tpm?: string; extra_body?: string
  use_system_proxy?: boolean; target_language?: string; translation_mode?: string
  fallback_models?: Array<Record<string, unknown>>
  provider_profiles?: Record<string, ProviderProfile>
  provider_credentials?: Record<string, ProviderCredentialStatus>
}
export interface CadDefaultsSummary { target_language?: string; translation_mode?: string; font_name?: string; font_size_reduction?: number; default_output_dir?: string; converter_backend?: string }
export interface QueueTask {
  id: string; source?: 'local' | 'backend'; file: File; kind: FileKind; status: TaskStatus; progress: number; message: string
  result?: { downloadUrl?: string; translatedCadUrl?: string; excelUrl?: string; taskId?: string; raw?: any }
}
export interface ProcessResult { downloadUrl?: string; translatedCadUrl?: string; excelUrl?: string; taskId?: string; raw?: any }
export interface BackendCadTask {
  task_id: string; original_filename: string; target_language?: string; extract_only?: boolean
  status?: string; stage?: string; processing_time?: string; text_count?: number; translatable_count?: number
  translation_count?: number; translated_count?: number; failed_count?: number; total_chunks?: number
  completed_chunks?: number; current_chunk?: number; provider?: string; model?: string; batch_size?: number
  retry_count?: number; last_error?: string; last_activity_at?: number; created_at?: number
  files?: { excel_file?: string | null; translated_cad_file?: string | null; log_file?: string | null }
}

export const getBackendStageLabel = (stage?: string) => ({
  extracting: '正在提取 CAD 文本', extracted: '文本提取完成', translating: 'LLM 翻译中',
  applying: '正在回写翻译', completed: '已完成', cancelled: '已停止', failed: '失败',
}[stage || ''] || '排队中')

export const resolveBackendTaskStatus = (task: BackendCadTask): TaskStatus => {
  const explicitStatus = (task.status || '').toLowerCase()
  const lastError = (task.last_error || '').toLowerCase()
  if (lastError.includes('cancelled by user') || lastError.includes('stopped by user')) return 'cancelled'
  if (['done', 'partial', 'processing', 'error', 'queued', 'cancelled'].includes(explicitStatus)) {
    const translated = typeof task.translated_count === 'number' ? task.translated_count : (task.translation_count ?? 0)
    if (explicitStatus === 'done' && (task.text_count ?? 0) > 0 && translated < (task.text_count ?? 0)) return 'partial'
    return explicitStatus as TaskStatus
  }
  if (task.files?.translated_cad_file || (task.extract_only && task.files?.excel_file)) return 'done'
  return task.files?.excel_file ? 'processing' : 'queued'
}

export const getBackendTaskProgress = (task: BackendCadTask) => {
  const status = resolveBackendTaskStatus(task)
  if (['cancelled', 'error', 'done', 'partial'].includes(status)) return 100
  if (task.total_chunks) return Math.min(100, Math.max(20, Math.round(((task.completed_chunks ?? 0) / task.total_chunks) * 100)))
  if (task.files?.translated_cad_file || (task.extract_only && task.files?.excel_file)) return 100
  return task.files?.excel_file ? 55 : 20
}

export const buildBackendTaskResult = (task: BackendCadTask) => ({
  taskId: task.task_id, downloadUrl: '',
  translatedCadUrl: resolveApiUrl(task.files?.translated_cad_file || ''),
  excelUrl: resolveApiUrl(task.files?.excel_file || ''), raw: task,
})

export const buildBackendQueueTask = (task: BackendCadTask): QueueTask => {
  const status = resolveBackendTaskStatus(task)
  const message = status === 'done' ? (task.files?.translated_cad_file ? 'Translated CAD ready' : task.files?.excel_file ? 'Excel ready' : 'Completed')
    : status === 'partial' ? `部分完成 (${task.failed_count || 0} 条失败)`
      : status === 'cancelled' ? '任务已停止' : status === 'error' ? task.last_error || 'Task failed' : getBackendStageLabel(task.stage)
  return { id: `backend-${task.task_id}`, source: 'backend', file: new File([], task.original_filename || `${task.task_id}.dwg`, { type: 'application/octet-stream' }), kind: 'cad', status, progress: getBackendTaskProgress(task), message, result: buildBackendTaskResult(task) }
}

export const unique = <T,>(items: T[]) => Array.from(new Set(items))
export const MAX_BATCH_SIZE = 2000
export const MIN_TIMEOUT_SECONDS = 1
export const MAX_TIMEOUT_SECONDS = 600
export const MIN_MAX_TOKENS = 1
export const MAX_MAX_TOKENS = 32000
export const DEFAULT_MAX_TOKENS = 16384
export const MIN_PARALLEL_COUNT = 1
export const MAX_PARALLEL_COUNT = 32
export const MIN_RETRY_COUNT = 0
export const MAX_RETRY_COUNT = 10
export const MIN_RPM = 1
export const MAX_RPM = 20000
export const MIN_TEMPERATURE = 0
export const MAX_TEMPERATURE = 2
export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
export const normalizeNumber = (value: unknown, fallback: number, min: number, max: number) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? clamp(numeric, min, max) : fallback
}
export const defaultLanguageOptions: LanguageOption[] = [
  ['Auto Detect', 'auto'], ['Chinese', 'zh'], ['English', 'en'], ['Japanese', 'ja'],
  ['Korean', 'ko'], ['Deutsch', 'de'], ['French', 'fr'], ['Russian', 'ru'],
].map(([label, value]) => ({ label, value }))
export const workflowOptions = [{ label: 'CAD translation (.dwg/.dxf)', value: 'cad' }, { label: 'Spreadsheet translation', value: 'sheet' }]
export const insertionModes = [{ label: '替换原文', value: 'replace' }, { label: '追加到下方', value: 'append' }, { label: '原文后换行', value: 'newline' }]
export const thinkingModes: { label: string; value: ThinkingMode }[] = [{ label: 'Enable', value: 'enabled' }, { label: 'Disable (Recommended)', value: 'disabled' }, { label: 'Default', value: 'default' }]
export const toUiInsertionMode = (value?: string) => String(value || '').trim().toLowerCase() === 'add' ? 'append' : String(value || '').trim().toLowerCase() === 'newline' ? 'newline' : 'replace'
export const toConfigTranslationMode = (value?: string) => String(value || '').trim().toLowerCase() === 'append' ? 'add' : String(value || '').trim().toLowerCase() === 'newline' ? 'newline' : 'replace'
export const fileAccept = '.xlsx,.xls,.csv,.dwg,.dxf'
export const isCadFile = (file: File) => /\.(dwg|dxf)$/i.test(file.name)
export const getFileKind = (file: File): FileKind => isCadFile(file) ? 'cad' : /\.csv$/i.test(file.name) ? 'csv' : /\.(xlsx|xls)$/i.test(file.name) ? 'excel' : 'other'
export const toTitle = (value: string) => ({ idle: '待开始', queued: '排队中', processing: '处理中', done: '已完成', partial: '部分完成', error: '失败', cancelled: '已停止' }[String(value || '').toLowerCase()] || value)

const preset = (id: string, name: string, api_format: string, base_url: string, default_model: string, notes: string): ProviderPreset => ({ id, name, api_format, base_url, default_model, notes })
export const defaultProviderPresets: ProviderPreset[] = [
  preset('openai', 'OpenAI', 'openai_compatible', 'https://api.openai.com/v1', 'gpt-4.1-mini', 'Official OpenAI endpoint'),
  preset('openrouter', 'OpenRouter', 'openai_compatible', 'https://openrouter.ai/api/v1', 'stepfun/step-3.5-flash:free', 'Multi-vendor gateway'),
  preset('nvidia', 'NVIDIA API Catalog', 'openai_compatible', 'https://integrate.api.nvidia.com/v1', 'moonshotai/kimi-k2.5', 'NVIDIA endpoint'),
  preset('dashscope', 'Alibaba DashScope', 'openai_compatible', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-max', 'Qwen models'),
  preset('deepseek', 'DeepSeek', 'openai_compatible', 'https://api.deepseek.com/v1', 'deepseek-chat', 'DeepSeek endpoint'),
  preset('groq', 'Groq', 'openai_compatible', 'https://api.groq.com/openai/v1', 'llama-3.3-70b-versatile', 'Groq endpoint'),
  preset('minimax', 'MiniMax', 'openai_compatible', 'https://api.minimax.chat/v1', 'MiniMax-Text-01', 'MiniMax global'),
  preset('minimax-cn', 'MiniMax 国内版', 'openai_compatible', 'https://api.minimaxi.com/v1', 'MiniMax-M2.5', 'MiniMax China'),
  preset('zhipu', 'Zhipu GLM', 'openai_compatible', 'https://open.bigmodel.cn/api/paas/v4', 'glm-4-plus', 'GLM models'),
  preset('moonshot', 'Moonshot', 'openai_compatible', 'https://api.moonshot.cn/v1', 'moonshot-v1-8k', 'Kimi models'),
  preset('siliconflow', 'SiliconFlow', 'openai_compatible', 'https://api.siliconflow.cn/v1', 'Qwen/Qwen2.5-7B-Instruct', 'Open-model hosting'),
  preset('together', 'Together AI', 'openai_compatible', 'https://api.together.xyz/v1', 'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo', 'Together endpoint'),
  preset('anthropic', 'Anthropic', 'anthropic', 'https://api.anthropic.com/v1', 'claude-3-5-haiku-latest', 'Claude Messages API'),
  preset('google', 'Google Gemini', 'google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.0-flash', 'Gemini API'),
  preset('ollama', 'Ollama', 'ollama', 'http://127.0.0.1:11434', 'qwen2.5:7b', 'Local Ollama'),
  preset('lmstudio', 'LM Studio', 'lmstudio', 'http://127.0.0.1:1234/v1', 'local-model', 'Local LM Studio'),
  preset('custom', 'Custom', 'openai_compatible', '', '', 'Custom provider'),
]
