import { useEffect, useMemo, useRef, useState } from 'react'
import { MessagePlugin } from 'tdesign-react'
import { apiService, getAdminToken, getApiErrorMessage } from '../../services/api'
import {
  CadDefaultsSummary, DEFAULT_MAX_TOKENS, FallbackModel, MAX_BATCH_SIZE,
  MAX_MAX_TOKENS, MAX_PARALLEL_COUNT, MAX_RPM, MAX_TEMPERATURE,
  MAX_TIMEOUT_SECONDS, MIN_MAX_TOKENS, MIN_PARALLEL_COUNT, MIN_RETRY_COUNT,
  MIN_RPM, MIN_TEMPERATURE, MIN_TIMEOUT_SECONDS, ProviderCredentialStatus,
  ProviderPreset, ProviderProfile, RuntimeSummary, ThinkingMode,
  defaultLanguageOptions, defaultProviderPresets, normalizeNumber,
  toConfigTranslationMode, toUiInsertionMode,
} from './model'

export const useModelConfiguration = () => {
  const [insertionMode, setInsertionMode] = useState('replace')
  const [provider, setProvider] = useState('custom')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiFormat, setApiFormat] = useState('openai_compatible')
  const [apiKey, setApiKey] = useState('')
  const [apiKeyDirty, setApiKeyDirty] = useState(false)
  const [clearApiKey, setClearApiKey] = useState(false)
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
  const [runtime, setRuntime] = useState<RuntimeSummary>({})
  const [cadDefaults, setCadDefaults] = useState<CadDefaultsSummary>({})
  const [providerPresets, setProviderPresets] = useState<ProviderPreset[]>([])
  const [customProviderName, setCustomProviderName] = useState('')
  const [providerProfiles, setProviderProfiles] = useState<Record<string, ProviderProfile>>({})
  const [providerCredentials, setProviderCredentials] = useState<Record<string, ProviderCredentialStatus>>({})
  const [fallbackModels, setFallbackModels] = useState<FallbackModel[]>([])
  const [adminTokenDraft, setAdminTokenDraft] = useState(() => getAdminToken())
  const [configLoadErrors, setConfigLoadErrors] = useState<Record<string, string>>({})
  const [languageOptions, setLanguageOptions] = useState(defaultLanguageOptions)
  const [loadingConfig, setLoadingConfig] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [savingCustomProvider, setSavingCustomProvider] = useState(false)
  const [deletingProviderId, setDeletingProviderId] = useState<string | null>(null)
  const [configMessage, setConfigMessage] = useState('')
  const glossaryInputRef = useRef<HTMLInputElement | null>(null)
  const pendingConfigLoads = useRef(0)

  const applyRuntimeConfig = (configData: any) => {
    const summary: RuntimeSummary = configData?.runtime || {}
    const defaults = configData?.cad_defaults || {}
    const loadedProvider = summary.provider || providerPresets[0]?.id || 'custom'
    setRuntime(summary); setCadDefaults(defaults); setProvider(loadedProvider)
    setProviderProfiles(summary.provider_profiles || {}); setProviderCredentials(summary.provider_credentials || {})
    setApiFormat(summary.format || 'openai_compatible')
    setBaseUrl(summary.base_url || ''); setModelId(summary.model || '')
    setApiKey(''); setApiKeyDirty(false); setClearApiKey(false)
    setFallbackModels((summary.fallback_models || []) as unknown as FallbackModel[])
    setCustomPrompt(summary.custom_system_prompt || '')
    setThinkingMode(summary.reasoning_enabled ? 'enabled' : 'disabled')
    setTemperature(normalizeNumber(summary.temperature, 0.7, MIN_TEMPERATURE, MAX_TEMPERATURE))
    setTimeoutSeconds(normalizeNumber(summary.timeout_seconds, 60, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS))
    setMaxTokens(normalizeNumber(summary.max_tokens, DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS, MAX_MAX_TOKENS))
    setBatchSize(normalizeNumber(summary.batch_size, MAX_BATCH_SIZE, 1, MAX_BATCH_SIZE))
    setParallelCount(normalizeNumber(summary.parallel_count, 1, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT))
    setRetryCount(normalizeNumber(summary.retry_count, 2, MIN_RETRY_COUNT, 10))
    setRpm(normalizeNumber(summary.rpm, 40, MIN_RPM, MAX_RPM))
    setTpm(summary.tpm || ''); setExtraBody(summary.extra_body || '')
    setUseSystemProxy(Boolean(summary.use_system_proxy ?? false)); setForceJson(Boolean(summary.batch_json ?? true))
    setGlossaryFile(null); setGlossaryCleared(false)
    setTargetLang(String(defaults.target_language || 'zh').trim() || 'zh')
    setInsertionMode(toUiInsertionMode(defaults.translation_mode || 'replace'))
  }

  const loadConfigResource = async (resource: 'config' | 'providers' | 'languages') => {
    pendingConfigLoads.current += 1
    setLoadingConfig(true)
    try {
      if (resource === 'config') applyRuntimeConfig(await apiService.translation.getConfig())
      else if (resource === 'providers') {
        const data: any = await apiService.translation.getProviders()
        setProviderPresets(Array.isArray(data?.presets) && data.presets.length ? data.presets : defaultProviderPresets)
      } else {
        const data: any = await apiService.translation.getLanguages()
        setLanguageOptions(data?.languages ? [{ label: 'Auto Detect', value: 'auto' }, ...Object.entries(data.languages).map(([value, label]) => ({ value, label: String(label) }))] : defaultLanguageOptions)
      }
      setConfigLoadErrors((current) => { const next = { ...current }; delete next[resource]; return next })
    } catch (error) {
      setConfigLoadErrors((current) => ({ ...current, [resource]: getApiErrorMessage(error, `${resource} load failed`) }))
      if (resource === 'providers') setProviderPresets((current) => current.length ? current : defaultProviderPresets)
    } finally {
      pendingConfigLoads.current -= 1
      setLoadingConfig(pendingConfigLoads.current > 0)
    }
  }

  useEffect(() => {
    void Promise.allSettled([
      loadConfigResource('config'),
      loadConfigResource('providers'),
      loadConfigResource('languages'),
    ])
    // Each resource records and retries its own failure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const resolveReasoningEnabled = () => thinkingMode === 'enabled' || (thinkingMode === 'default' && Boolean(runtime.reasoning_enabled))
  const resolveRuntimeFormat = () => apiFormat || providerPresets.find((item) => item.id === provider)?.api_format || runtime.format || 'openai_compatible'
  const loadWorkflowPreset = (nextProvider: string) => {
    setProviderProfiles((current) => ({ ...current, [provider]: { format: apiFormat, base_url: baseUrl, model: modelId, reasoning_enabled: resolveReasoningEnabled(), timeout_seconds: timeoutSeconds, temperature, max_tokens: maxTokens } }))
    const preset = providerPresets.find((item) => item.id === nextProvider)
    const profile = providerProfiles[nextProvider]
    setProvider(nextProvider); setApiFormat(profile?.format || preset?.api_format || 'openai_compatible')
    setBaseUrl(profile?.base_url || preset?.base_url || ''); setModelId(profile?.model || preset?.default_model || '')
    setThinkingMode(profile?.reasoning_enabled ? 'enabled' : 'disabled')
    setTimeoutSeconds(normalizeNumber(profile?.timeout_seconds, timeoutSeconds, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS))
    setTemperature(normalizeNumber(profile?.temperature, temperature, MIN_TEMPERATURE, MAX_TEMPERATURE))
    setMaxTokens(normalizeNumber(profile?.max_tokens, maxTokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS))
    setApiKey(''); setApiKeyDirty(false); setClearApiKey(false)
  }

  const builtinProviderIds = useMemo(() => new Set(defaultProviderPresets.map((item) => item.id)), [])
  const isCustomProvider = (providerId: string) => !builtinProviderIds.has(providerId)
  const saveCustomProviderPreset = async () => {
    const name = customProviderName.trim(); const url = baseUrl.trim(); const model = modelId.trim()
    if (!name || !url || !model) { MessagePlugin.error('请填写服务商名称、基础 URL 和模型 ID'); return }
    if (savingCustomProvider) return
    setSavingCustomProvider(true)
    try {
      const saved: any = await apiService.translation.saveCustomProvider({ name, base_url: url, default_model: model, api_format: apiFormat, notes: 'Custom provider' })
      const providerId = saved?.preset?.id || saved?.id
      if (!providerId) throw new Error('服务商已保存，但响应缺少 provider id')
      const data: any = await apiService.translation.getProviders()
      setProviderPresets(data?.presets || []); setProvider(providerId); setCustomProviderName('')
      setProviderProfiles((current) => ({ ...current, [providerId]: { format: apiFormat, base_url: url, model } }))
      MessagePlugin.success(`已添加自定义服务商: ${name}`)
    } catch (error) { MessagePlugin.error(getApiErrorMessage(error, '添加自定义服务商失败')) }
    finally { setSavingCustomProvider(false) }
  }
  const deleteCustomProviderPreset = async (providerId: string) => {
    if (deletingProviderId) return
    setDeletingProviderId(providerId)
    try {
      await apiService.translation.deleteCustomProvider(providerId)
      const data: any = await apiService.translation.getProviders(); setProviderPresets(data?.presets || [])
      if (provider === providerId) loadWorkflowPreset('custom')
      MessagePlugin.success('已删除自定义服务商')
    } catch (error) { MessagePlugin.error(getApiErrorMessage(error, '删除自定义服务商失败')) }
    finally { setDeletingProviderId(null) }
  }

  const buildRuntimePayload = () => {
    const payload: Record<string, unknown> = {
      provider, format: resolveRuntimeFormat(), base_url: baseUrl.trim(), model: modelId.trim(),
      system_prompt_mode: customPrompt.trim() ? 'custom' : runtime.system_prompt_mode === 'custom' ? 'default' : runtime.system_prompt_mode || 'default',
      custom_system_prompt: customPrompt.trim(), reasoning_enabled: resolveReasoningEnabled(),
      temperature: normalizeNumber(temperature, 0.7, MIN_TEMPERATURE, MAX_TEMPERATURE),
      timeout_seconds: normalizeNumber(timeoutSeconds, 60, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS),
      max_tokens: normalizeNumber(maxTokens, DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS, MAX_MAX_TOKENS),
      batch_size: normalizeNumber(batchSize, MAX_BATCH_SIZE, 1, MAX_BATCH_SIZE), batch_json: forceJson,
      parallel_count: normalizeNumber(parallelCount, 1, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT),
      retry_count: normalizeNumber(retryCount, 2, MIN_RETRY_COUNT, 10), rpm: normalizeNumber(rpm, 40, MIN_RPM, MAX_RPM),
      tpm: tpm.trim(), extra_body: extraBody.trim(), use_system_proxy: useSystemProxy,
      target_language: targetLang, translation_mode: toConfigTranslationMode(insertionMode),
      font_name: cadDefaults.font_name || 'Times New Roman', font_size_reduction: cadDefaults.font_size_reduction ?? 4,
      default_output_dir: cadDefaults.default_output_dir || '', converter_backend: cadDefaults.converter_backend || 'auto',
      fallback_models: fallbackModels,
      provider_profiles: { ...providerProfiles, [provider]: { format: resolveRuntimeFormat(), base_url: baseUrl.trim(), model: modelId.trim(), reasoning_enabled: resolveReasoningEnabled(), timeout_seconds: timeoutSeconds, temperature, max_tokens: maxTokens } },
    }
    if (glossaryCleared) payload.glossary_file = ''; else if (!glossaryFile) payload.glossary_file = runtime.glossary_file || ''
    if (clearApiKey) payload.clear_api_key = true; else if (apiKeyDirty && apiKey.trim()) payload.api_key = apiKey.trim()
    return payload
  }

  const saveRuntimeConfig = async () => {
    setSavingConfig(true)
    try {
      const payload = buildRuntimePayload()
      if (glossaryFile) { const form = new FormData(); form.append('file', glossaryFile); const uploaded: any = await apiService.translation.uploadGlossary(form); payload.glossary_file = String(uploaded?.saved_path || '').trim() }
      const result: any = await apiService.translation.saveConfig(payload); applyRuntimeConfig(result)
      setConfigMessage(result?.message || 'Configuration saved'); MessagePlugin.success(result?.message || 'Configuration saved')
    } catch (error) { const message = getApiErrorMessage(error, 'Save config failed'); setConfigMessage(message); MessagePlugin.error(message) }
    finally { setSavingConfig(false) }
  }
  const testRuntimeConnection = async () => {
    setTestingConnection(true)
    try { const result: any = await apiService.translation.testConnection(buildRuntimePayload()); const message = `${result?.message || 'Connection test completed'} (${result?.provider || provider})`; setConfigMessage(message); MessagePlugin.success(message) }
    catch (error) { const message = getApiErrorMessage(error, 'Connection test failed'); setConfigMessage(message); MessagePlugin.error(message) }
    finally { setTestingConnection(false) }
  }

  return {
    insertionMode, setInsertionMode, provider, baseUrl, setBaseUrl, apiFormat, setApiFormat,
    apiKey, setApiKey, setApiKeyDirty, clearApiKey, setClearApiKey, showApiKey, setShowApiKey,
    modelId, setModelId, useSystemProxy, setUseSystemProxy, forceJson, setForceJson,
    targetLang, setTargetLang, thinkingMode, setThinkingMode, customPrompt, setCustomPrompt,
    batchSize, setBatchSize, timeoutSeconds, setTimeoutSeconds, maxTokens, setMaxTokens,
    parallelCount, setParallelCount, temperature, setTemperature, retryCount, setRetryCount,
    rpm, setRpm, tpm, setTpm, extraBody, setExtraBody, glossaryFile, setGlossaryFile,
    glossaryCleared, setGlossaryCleared, runtime, cadDefaults, providerPresets, customProviderName,
    setCustomProviderName, providerProfiles, providerCredentials, fallbackModels, setFallbackModels,
    adminTokenDraft, setAdminTokenDraft, configLoadErrors, languageOptions, loadingConfig, savingConfig,
    testingConnection, savingCustomProvider, deletingProviderId, configMessage, glossaryInputRef,
    loadConfigResource, loadWorkflowPreset, isCustomProvider, saveCustomProviderPreset,
    deleteCustomProviderPreset, saveRuntimeConfig, testRuntimeConnection,
  }
}
