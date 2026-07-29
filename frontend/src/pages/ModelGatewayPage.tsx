import React, { useEffect, useMemo, useState } from 'react'
import { Button, Dialog, Input, MessagePlugin, Textarea } from 'tdesign-react'
import { DeleteIcon } from 'tdesign-icons-react'
import { apiService, getApiErrorMessage } from '../services/api'

interface ProviderPreset {
  id: string
  name: string
  base_url: string
  default_model: string
  notes: string
}

interface RuntimeSummary {
  provider?: string
  base_url?: string
  model?: string
  api_key_configured?: boolean
  timeout_seconds?: number
  temperature?: number
  max_tokens?: number
  batch_size?: number
  batch_json?: boolean
  api_key_source?: 'config' | 'none'
  masked_api_key?: string
}

interface ConnectionResult {
  success?: boolean
  reachable?: boolean
  status_code?: number
  provider?: string
  endpoint?: string
  model?: string
  message?: string
}

interface FormState {
  provider: string
  connectionType: 'official' | 'custom'
  baseUrl: string
  host: string
  port: string
  apiPath: string
  apiKey: string
  model: string
  temperature: string
  maxTokens: string
  batchSize: string
  timeout: string
  batchJson: boolean
}

const defaultState: FormState = {
  provider: 'custom',
  connectionType: 'official',
  baseUrl: '',
  host: '',
  port: '443',
  apiPath: '/v1',
  apiKey: '',
  model: '',
  temperature: '0.1',
  maxTokens: '4000',
  batchSize: '12',
  timeout: '60',
  batchJson: true,
}

const parseEndpoint = (rawUrl: string) => {
  try {
    const parsed = new URL(rawUrl)
    return {
      baseUrl: rawUrl,
      host: parsed.hostname,
      port: parsed.port || (parsed.protocol === 'https:' ? '443' : '80'),
      apiPath: parsed.pathname && parsed.pathname !== '/' ? parsed.pathname : '/v1',
    }
  } catch {
    return {
      baseUrl: rawUrl,
      host: '',
      port: '443',
      apiPath: '/v1',
    }
  }
}

const ModelGatewayPage: React.FC = () => {
  const [form, setForm] = useState<FormState>(defaultState)
  const [runtime, setRuntime] = useState<RuntimeSummary>({})
  const [presets, setPresets] = useState<ProviderPreset[]>([])
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<ConnectionResult | null>(null)

  const [addDialogVisible, setAddDialogVisible] = useState(false)
  const [newProvider, setNewProvider] = useState({ id: '', name: '', baseUrl: '', model: '', notes: '' })

  const loadGateway = async () => {
    try {
      const [configData, providersData]: any = await Promise.all([
        apiService.translation.getConfig(),
        apiService.translation.getProviders(),
      ])
      const runtimeSummary = configData?.runtime || {}
      const endpointParts = parseEndpoint(runtimeSummary.base_url || '')
      setRuntime(runtimeSummary)
      setPresets(providersData?.presets || [])
      setForm({
        provider: runtimeSummary.provider || 'custom',
        connectionType: runtimeSummary.provider === 'custom' ? 'custom' : 'official',
        baseUrl: runtimeSummary.base_url || '',
        host: endpointParts.host,
        port: endpointParts.port,
        apiPath: endpointParts.apiPath,
        apiKey: '',
        model: runtimeSummary.model || '',
        temperature: String(runtimeSummary.temperature ?? 0.1),
        maxTokens: String(runtimeSummary.max_tokens ?? 4000),
        batchSize: String(runtimeSummary.batch_size ?? 12),
        timeout: String(runtimeSummary.timeout_seconds ?? 60),
        batchJson: Boolean(runtimeSummary.batch_json ?? true),
      })
    } catch {
      MessagePlugin.error('Model Gateway load failed')
    }
  }

  useEffect(() => {
    void loadGateway()
  }, [])

  const resolvedBaseUrl = useMemo(() => {
    if (form.connectionType === 'custom' && form.host) {
      const protocol = form.port === '443' ? 'https' : 'http'
      const portSegment =
        (protocol === 'https' && form.port === '443') || (protocol === 'http' && form.port === '80')
          ? ''
          : `:${form.port}`
      return `${protocol}://${form.host}${portSegment}${form.apiPath || ''}`
    }
    return form.baseUrl
  }, [form.apiPath, form.baseUrl, form.connectionType, form.host, form.port])

  const updateForm = (key: keyof FormState, value: string | boolean) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const applyPreset = (providerId: string) => {
    const preset = presets.find((item) => item.id === providerId)
    if (!preset) return
    const endpointParts = parseEndpoint(preset.base_url)
    setForm((current) => ({
      ...current,
      provider: providerId,
      connectionType: providerId === 'custom' ? 'custom' : 'official',
      baseUrl: preset.base_url,
      host: endpointParts.host,
      port: endpointParts.port,
      apiPath: endpointParts.apiPath,
      model: preset.default_model,
    }))
  }

  const buildPayload = () => {
    const payload: Record<string, unknown> = {
      provider: form.provider,
      base_url: resolvedBaseUrl,
      model: form.model,
      temperature: Number(form.temperature),
      max_tokens: Number(form.maxTokens),
      timeout_seconds: Number(form.timeout),
      batch_size: Number(form.batchSize),
      batch_json: form.batchJson,
    }

    if (form.apiKey.trim()) {
      payload.api_key = form.apiKey.trim()
    }

    return payload
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiService.translation.saveConfig(buildPayload())
      MessagePlugin.success('Configuration saved')
      await loadGateway()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Save API failed'))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const data: any = await apiService.translation.testConnection(buildPayload())
      setTestResult(data)
      MessagePlugin.success(data?.success ? 'Connection OK' : 'Connection failed')
    } catch (error) {
      const message = getApiErrorMessage(error, 'Test endpoint failed or is not available.')
      setTestResult({ success: false, message })
      MessagePlugin.error(message)
    } finally {
      setTesting(false)
    }
  }

  const handleAddPreset = async () => {
    if (!newProvider.id || !newProvider.name || !newProvider.baseUrl) {
      MessagePlugin.warning('Please fill in required fields (ID, Name, Base URL)')
      return
    }

    try {
      await apiService.translation.saveCustomProvider({
        id: newProvider.id,
        name: newProvider.name,
        base_url: newProvider.baseUrl,
        default_model: newProvider.model,
        notes: newProvider.notes,
      })
      MessagePlugin.success('Custom provider added')
      setAddDialogVisible(false)
      setNewProvider({ id: '', name: '', baseUrl: '', model: '', notes: '' })
      await loadGateway()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Failed to add custom provider'))
    }
  }

  const handleDeletePreset = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    try {
      await apiService.translation.deleteCustomProvider(id)
      MessagePlugin.success('Provider deleted')
      await loadGateway()
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Failed to delete provider'))
    }
  }

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel-compact">
        <div className="hero-copy">
          <div className="eyebrow">Model Config</div>
          <h1 className="page-title">Model runtime configuration</h1>
          <p className="page-subtitle">
            Configure provider, endpoint, API key, and tuning values for every translation job.
          </p>
        </div>

        <div className="hero-status-row">
          <span className="status-chip status-chip-neutral">Active provider: {runtime.provider || 'custom'}</span>
          <span className="status-chip status-chip-neutral">Active model: {runtime.model || 'Not configured'}</span>
        </div>
      </section>

      <section className="projects-shell">
        <article className="surface-card projects-main">
          <div className="section-kicker">Connection Settings</div>
          <h2 className="section-heading">Runtime endpoint setup</h2>

          <div className="provider-grid">
            {presets.map((preset) => {
              const isCustom = !['openai', 'openrouter', 'dashscope', 'deepseek', 'groq', 'minimax', 'minimax-cn', 'zhipu', 'moonshot', 'siliconflow', 'together', 'anthropic', 'google', 'ollama', 'lmstudio', 'custom'].includes(preset.id)
              return (
                <button key={preset.id} type="button" className="provider-card" onClick={() => applyPreset(preset.id)}>
                  <div className="provider-card-head">
                    <strong>{preset.name}</strong>
                    {isCustom && <span className="pill pill-neutral">Custom</span>}
                  </div>
                  <div className="provider-card-model">{preset.default_model}</div>
                  <p>{preset.notes}</p>
                </button>
              )
            })}
          </div>

          <div className="form-grid form-grid-two">
            <label className="form-field">
              <span>Provider</span>
              <select className="input-shell" value={form.provider} onChange={(e) => applyPreset(e.target.value)}>
                {presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="form-field">
              <span>Connection Type</span>
              <div className="segmented-toggle">
                <button
                  type="button"
                  className={form.connectionType === 'official' ? 'segment-active' : ''}
                  onClick={() => updateForm('connectionType', 'official')}
                >
                  Official API
                </button>
                <button
                  type="button"
                  className={form.connectionType === 'custom' ? 'segment-active' : ''}
                  onClick={() => updateForm('connectionType', 'custom')}
                >
                  Custom Endpoint
                </button>
              </div>
            </label>

            <label className="form-field form-field-span">
              <span>Base URL</span>
              <input className="input-shell" value={resolvedBaseUrl} onChange={(e) => updateForm('baseUrl', e.target.value)} />
            </label>
            <label className="form-field">
              <span>Host / IP</span>
              <input className="input-shell" value={form.host} onChange={(e) => updateForm('host', e.target.value)} />
            </label>
            <label className="form-field">
              <span>Port</span>
              <input className="input-shell" value={form.port} onChange={(e) => updateForm('port', e.target.value)} />
            </label>
            <label className="form-field">
              <span>API Path</span>
              <input className="input-shell" value={form.apiPath} onChange={(e) => updateForm('apiPath', e.target.value)} />
            </label>
            <div className="form-field form-field-span">
              <label>API Key</label>
              <input
                type="password"
                className="input-shell"
                value={form.apiKey}
                onChange={(e) => updateForm('apiKey', e.target.value)}
                placeholder="sk-..."
              />
              {runtime.api_key_configured && !form.apiKey && (
                <small className="helper-note">
                  Key loaded from config file
                  {runtime.masked_api_key ? ` (${runtime.masked_api_key})` : ''}. Enter a new key above to override.
                </small>
              )}
            </div>
            <label className="form-field">
              <span>Model Name</span>
              <input className="input-shell" value={form.model} onChange={(e) => updateForm('model', e.target.value)} />
            </label>
            <label className="form-field">
              <span>Temperature</span>
              <input className="input-shell" value={form.temperature} onChange={(e) => updateForm('temperature', e.target.value)} />
            </label>
            <label className="form-field">
              <span>Max Tokens</span>
              <input className="input-shell" value={form.maxTokens} onChange={(e) => updateForm('maxTokens', e.target.value)} />
            </label>
            <label className="form-field">
              <span>Batch Size</span>
              <input className="input-shell" value={form.batchSize} onChange={(e) => updateForm('batchSize', e.target.value)} />
            </label>
            <label className="form-field">
              <span>Timeout (sec)</span>
              <input className="input-shell" value={form.timeout} onChange={(e) => updateForm('timeout', e.target.value)} />
            </label>

            <label className="switch-field form-field-span">
              <span>Batch JSON</span>
              <button type="button" className={`switch-shell${form.batchJson ? ' switch-shell-on' : ''}`} onClick={() => updateForm('batchJson', !form.batchJson)}>
                <span />
              </button>
            </label>
          </div>

          <div className="detail-actions">
            <Button theme="primary" loading={testing} onClick={handleTest}>
              Test Connection
            </Button>
            <Button theme="success" loading={saving} onClick={handleSave}>
              Save Config
            </Button>
            <Button variant="outline" onClick={() => setForm(defaultState)}>
              Reset
            </Button>
          </div>
        </article>

        <aside className="surface-card project-detail">
          <div className="section-kicker">Runtime Status</div>
          <h2 className="section-heading">Active endpoint</h2>

          <div className="detail-section">
            <div className="detail-row">
              <span>Endpoint</span>
              <strong>{runtime.base_url || resolvedBaseUrl || 'Not configured'}</strong>
            </div>
            <div className="detail-row">
              <span>Model</span>
              <strong>{runtime.model || form.model || 'Unknown'}</strong>
            </div>
            <div className="detail-row">
              <span>API Key</span>
              <strong>{runtime.api_key_configured ? 'Configured (config)' : 'Missing'}</strong>
            </div>
            <div className="detail-row">
              <span>Batch JSON</span>
              <strong>{form.batchJson ? 'On' : 'Off'}</strong>
            </div>
            <div className="detail-row">
              <span>Status</span>
              <strong>{testResult?.success ? 'Active' : 'Idle'}</strong>
            </div>
          </div>

          <div className="detail-section">
            <div className="detail-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              Provider Presets
              <Button size="small" variant="text" onClick={() => setAddDialogVisible(true)}>
                + Custom
              </Button>
            </div>
            <div className="preset-list">
              {presets.map((preset) => {
                const isCustom = !['openai', 'openrouter', 'dashscope', 'deepseek', 'groq', 'minimax', 'minimax-cn', 'zhipu', 'moonshot', 'siliconflow', 'together', 'anthropic', 'google', 'ollama', 'lmstudio', 'custom'].includes(preset.id)
                return (
                  <div key={preset.id} className="preset-card-wrap">
                    <button type="button" className="preset-card" onClick={() => applyPreset(preset.id)}>
                      <strong>
                        {preset.name}{' '}
                        {isCustom && <span className="preset-tag">Custom</span>}
                      </strong>
                      <span>{preset.default_model}</span>
                      <small>{preset.notes}</small>
                    </button>
                    {isCustom && (
                      <Button
                        shape="circle"
                        variant="text"
                        size="small"
                        className="preset-delete"
                        onClick={(e) => handleDeletePreset(e, preset.id)}
                      >
                        <DeleteIcon />
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="detail-section">
            <div className="detail-heading">Connection Result</div>
            <div className={`notice-card ${testResult?.success ? 'success-card' : 'warning-card'}`}>
              {testResult
                ? `${testResult.success ? 'OK' : 'Failed'} · HTTP ${testResult.status_code ?? '-'} · ${testResult.message || 'Not tested'}`
                : 'Run Test Connection after filling provider, endpoint, and API key.'}
            </div>
          </div>
        </aside>
      </section>

      <Dialog
        header="Add Custom Provider Preset"
        visible={addDialogVisible}
        onConfirm={handleAddPreset}
        onClose={() => setAddDialogVisible(false)}
      >
        <div className="dialog-stack">
          <Input
            label="Provider ID"
            placeholder="e.g. my-custom-endpoint"
            value={newProvider.id}
            onChange={(val) => setNewProvider({ ...newProvider, id: val })}
          />
          <Input
            label="Display Name"
            placeholder="e.g. Acme Corp internal"
            value={newProvider.name}
            onChange={(val) => setNewProvider({ ...newProvider, name: val })}
          />
          <Input
            label="Base URL"
            placeholder="https://..."
            value={newProvider.baseUrl}
            onChange={(val) => setNewProvider({ ...newProvider, baseUrl: val })}
          />
          <Input
            label="Default Model"
            placeholder="e.g. llama-3"
            value={newProvider.model}
            onChange={(val) => setNewProvider({ ...newProvider, model: val })}
          />
          <Textarea
            placeholder="Notes (optional)"
            value={newProvider.notes}
            onChange={(val) => setNewProvider({ ...newProvider, notes: val })}
          />
        </div>
      </Dialog>
    </div>
  )
}

export default ModelGatewayPage
