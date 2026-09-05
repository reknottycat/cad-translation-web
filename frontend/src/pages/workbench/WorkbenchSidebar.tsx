import { Button } from 'tdesign-react'
import { CloudUploadIcon, DownloadIcon } from 'tdesign-icons-react'
import { FallbackModel, LanguageOption, ProviderPreset, ThinkingMode } from './model'

interface Props { vm: any }

export const WorkbenchSidebar = ({ vm }: Props) => {
  const { workflow, setWorkflow, autoSelectWorkflow, setAutoSelectWorkflow, insertionMode, setInsertionMode, translationRegion, setTranslationRegion, skipTranslation, setSkipTranslation, provider, baseUrl, setBaseUrl, apiFormat, setApiFormat, apiKey, setApiKey, setApiKeyDirty, clearApiKey, setClearApiKey, showApiKey, setShowApiKey, modelId, setModelId, useSystemProxy, setUseSystemProxy, forceJson, setForceJson, targetLang, setTargetLang, thinkingMode, setThinkingMode, customPrompt, setCustomPrompt, batchSize, setBatchSize, timeoutSeconds, setTimeoutSeconds, maxTokens, setMaxTokens, parallelCount, setParallelCount, temperature, setTemperature, retryCount, setRetryCount, rpm, setRpm, tpm, setTpm, extraBody, setExtraBody, glossaryFile, setGlossaryFile, glossaryCleared, setGlossaryCleared, runtime, providerPresets, customProviderName, setCustomProviderName, providerProfiles, providerCredentials, fallbackModels, setFallbackModels, adminTokenDraft, setAdminTokenDraft, configLoadErrors, languageOptions, loadingConfig, savingConfig, testingConnection, savingCustomProvider, deletingProviderId, collapsedSections, glossaryInputRef, loadConfigResource, toggleSection, isCustomProvider, loadWorkflowPreset, saveCustomProviderPreset, deleteCustomProviderPreset, saveRuntimeConfig, testRuntimeConnection, workflowOptions, insertionModes, thinkingModes, MAX_BATCH_SIZE, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, MIN_MAX_TOKENS, MAX_MAX_TOKENS, MIN_PARALLEL_COUNT, MAX_PARALLEL_COUNT, MIN_RETRY_COUNT, MAX_RETRY_COUNT, MIN_RPM, MAX_RPM, MIN_TEMPERATURE, MAX_TEMPERATURE, clamp, normalizeNumber, setAdminToken } = vm
  return (
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
                {workflowOptions.map((option: { label: string; value: string }) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <label className="toggle-row">
                <span className={`toggle ${autoSelectWorkflow ? 'toggle-on' : ''}`} onClick={() => setAutoSelectWorkflow((v: boolean) => !v)}>
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
                  {insertionModes.map((option: { label: string; value: string }) => (
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
              <label className="field-group">
                <span className="field-label row-label">
                  管理令牌
                  <button
                    type="button"
                    className="small-link-button"
                    onClick={() => {
                      setAdminToken(adminTokenDraft)
                      void Promise.allSettled([
                        loadConfigResource('config'),
                        loadConfigResource('providers'),
                      ])
                    }}
                  >
                    保存并重试
                  </button>
                </span>
                <input
                  className="field field-input mono"
                  type="password"
                  value={adminTokenDraft}
                  placeholder="启用 Admin Guard 时必填"
                  onChange={(event) => setAdminTokenDraft(event.target.value)}
                />
              </label>

              {(Object.entries(configLoadErrors) as Array<[string, string]>).map(([resource, message]) => (
                <p className="helper-copy" key={resource}>
                  {resource}: {message}{' '}
                  <button type="button" className="small-link-button" onClick={() => void loadConfigResource(resource as 'config' | 'providers' | 'languages')}>
                    重试
                  </button>
                </p>
              ))}

              <label className="toggle-row">
                <span className={`toggle ${skipTranslation ? 'toggle-on' : ''}`} onClick={() => setSkipTranslation((v: boolean) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">跳过翻译</span>
              </label>

              <label className="field-group">
                <span className="field-label">选择平台</span>
                <select className="field field-select" value={provider} onChange={(e) => loadWorkflowPreset(e.target.value)} disabled={loadingConfig}>
                  {providerPresets.map((preset: ProviderPreset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                  {!providerPresets.some((preset: ProviderPreset) => preset.id === 'custom') && (
                    <option value="custom">Custom (添加新服务商)</option>
                  )}
                </select>

                {providerPresets.filter((p: ProviderPreset) => isCustomProvider(p.id)).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <span className="field-label" style={{ fontSize: 12 }}>已添加的自定义</span>
                    {providerPresets.filter((p: ProviderPreset) => isCustomProvider(p.id)).map((preset: ProviderPreset) => (
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

                {provider === 'custom' || isCustomProvider(provider) ? (
                  <>
                    {provider === 'custom' && (
                      <>
                        <span className="field-label" style={{ marginTop: 8, display: 'block' }}>服务商名称</span>
                        <input
                          className="field field-input"
                          type="text"
                          value={customProviderName}
                          placeholder="例如：My API"
                          onChange={(e) => setCustomProviderName(e.target.value)}
                        />
                      </>
                    )}
                    <span className="field-label" style={{ marginTop: 8, display: 'block' }}>基础 URL</span>
                    <input
                      className="field field-input mono"
                      type="text"
                      value={baseUrl}
                      placeholder="https://your-endpoint/v1"
                      onChange={(e) => setBaseUrl(e.target.value)}
                    />
                    <span className="field-label" style={{ marginTop: 8, display: 'block' }}>API 协议</span>
                    <select className="field field-select" value={apiFormat} onChange={(event) => setApiFormat(event.target.value)}>
                      <option value="openai_compatible">OpenAI compatible</option>
                      <option value="anthropic">Anthropic</option>
                      <option value="google">Google</option>
                      <option value="ollama">Ollama</option>
                      <option value="lmstudio">LM Studio</option>
                    </select>
                    <span className="field-label" style={{ marginTop: 8, display: 'block' }}>模型 ID</span>
                    <input
                      className="field field-input"
                      type="text"
                      value={modelId}
                      placeholder="例如：gpt-4o"
                      onChange={(e) => {
                        setModelId(e.target.value)
                      }}
                    />
                    {provider === 'custom' && (
                      <button
                        type="button"
                        className="small-link-button"
                        style={{ marginTop: 10, fontSize: 13 }}
                        disabled={savingCustomProvider}
                        onClick={() => void saveCustomProviderPreset()}
                      >
                        {savingCustomProvider ? '添加中...' : '+ 添加为预设'}
                      </button>
                    )}
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
                  <button type="button" className="small-link-button" onClick={() => setShowApiKey((v: boolean) => !v)}>
                    {showApiKey ? 'Hide' : 'Show'}
                  </button>
                </span>
                <input
                  className="field field-input mono"
                  type={showApiKey ? 'text' : 'password'}
                  value={apiKey}
                  placeholder={
                    providerCredentials[provider]?.configured
                      ? `已配置 (${providerCredentials[provider].masked || providerCredentials[provider].source})`
                      : runtime.api_key_configured && runtime.provider === provider
                        ? runtime.masked_api_key || 'configured'
                        : '********'
                  }
                  onChange={(e) => {
                    setApiKey(e.target.value)
                    setApiKeyDirty(true)
                    setClearApiKey(false)
                  }}
                />
                <p className="helper-copy">
                  留空会保留现有密钥。
                  {providerCredentials[provider]?.configured && (
                    <button
                      type="button"
                      className="small-link-button"
                      onClick={() => {
                        setApiKey('')
                        setApiKeyDirty(false)
                        setClearApiKey(true)
                      }}
                    >
                      {clearApiKey ? '保存后将删除' : '删除已存密钥'}
                    </button>
                  )}
                </p>
              </label>

              {provider !== 'custom' && !isCustomProvider(provider) && (
                <label className="field-group">
                  <span className="field-label">模型 ID</span>
                  <input
                    className="field field-input"
                    type="text"
                    value={modelId}
                    onChange={(e) => {
                      setModelId(e.target.value)
                    }}
                  />
                </label>
              )}

              <label className="toggle-row">
                <span className={`toggle ${useSystemProxy ? 'toggle-on' : ''}`} onClick={() => setUseSystemProxy((v: boolean) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">启用系统代理</span>
              </label>

              <label className="toggle-row">
                <span className={`toggle ${forceJson ? 'toggle-on' : ''}`} onClick={() => setForceJson((v: boolean) => !v)}>
                  <span />
                </span>
                <span className="toggle-label">强制 JSON 输出</span>
                <button type="button" className="help-dot" aria-label="help">
                  ?
                </button>
              </label>

              <div className="field-group">
                <span className="field-label row-label">
                  备用模型（按顺序）
                  <button
                    type="button"
                    className="small-link-button"
                    onClick={() => setFallbackModels((current: FallbackModel[]) => [
                      ...current,
                      { provider: 'custom', format: 'openai_compatible', base_url: '', model: '' },
                    ])}
                  >
                    + 添加
                  </button>
                </span>
                {fallbackModels.map((fallback: FallbackModel, index: number) => (
                  <div key={`${index}-${fallback.provider}`} style={{ border: '1px solid #e7e7e7', borderRadius: 6, padding: 8, marginTop: 8 }}>
                    <select
                      className="field field-select"
                      value={fallback.provider}
                      onChange={(event) => {
                        const nextProvider = event.target.value
                        const preset = providerPresets.find((item: ProviderPreset) => item.id === nextProvider)
                        setFallbackModels((current: FallbackModel[]) => current.map((item: FallbackModel, itemIndex: number) => itemIndex === index ? {
                          ...item,
                          provider: nextProvider,
                          format: providerProfiles[nextProvider]?.format || preset?.api_format || 'openai_compatible',
                          base_url: providerProfiles[nextProvider]?.base_url || preset?.base_url || '',
                          model: providerProfiles[nextProvider]?.model || preset?.default_model || '',
                        } : item))
                      }}
                    >
                      {providerPresets.map((preset: ProviderPreset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
                    </select>
                    <select className="field field-select" value={fallback.format} onChange={(event) => setFallbackModels((current: FallbackModel[]) => current.map((item: FallbackModel, itemIndex: number) => itemIndex === index ? { ...item, format: event.target.value } : item))}>
                      <option value="openai_compatible">OpenAI compatible</option>
                      <option value="anthropic">Anthropic</option>
                      <option value="google">Google</option>
                      <option value="ollama">Ollama</option>
                      <option value="lmstudio">LM Studio</option>
                    </select>
                    <input className="field field-input mono" value={fallback.base_url} placeholder="Base URL" onChange={(event) => setFallbackModels((current: FallbackModel[]) => current.map((item: FallbackModel, itemIndex: number) => itemIndex === index ? { ...item, base_url: event.target.value } : item))} />
                    <input className="field field-input" value={fallback.model} placeholder="Model ID" onChange={(event) => setFallbackModels((current: FallbackModel[]) => current.map((item: FallbackModel, itemIndex: number) => itemIndex === index ? { ...item, model: event.target.value } : item))} />
                    <label className="toggle-row">
                      <input type="checkbox" checked={Boolean(fallback.reasoning_enabled)} onChange={(event) => setFallbackModels((current: FallbackModel[]) => current.map((item: FallbackModel, itemIndex: number) => itemIndex === index ? { ...item, reasoning_enabled: event.target.checked } : item))} />
                      <span className="toggle-label">启用推理模式</span>
                    </label>
                    <p className="helper-copy">
                      {providerCredentials[fallback.provider]?.configured ? '使用该服务商已保存的密钥' : '该服务商尚未配置密钥'}
                      {' · '}
                      <button type="button" className="small-link-button" disabled={index === 0} onClick={() => setFallbackModels((current: FallbackModel[]) => { const next = [...current]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next })}>上移</button>
                      {' · '}
                      <button type="button" className="small-link-button" disabled={index === fallbackModels.length - 1} onClick={() => setFallbackModels((current: FallbackModel[]) => { const next = [...current]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; return next })}>下移</button>
                      {' · '}
                      <button type="button" className="small-link-button" onClick={() => setFallbackModels((current: FallbackModel[]) => current.filter((_: FallbackModel, itemIndex: number) => itemIndex !== index))}>移除</button>
                    </p>
                  </div>
                ))}
              </div>
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
                    .filter((option: LanguageOption) => option.value !== 'auto')
                    .map((option: LanguageOption) => (
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
                  {thinkingModes.map((mode: { label: string; value: ThinkingMode }) => (
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
  )
}
