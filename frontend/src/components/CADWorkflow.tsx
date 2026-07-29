import React, { useMemo, useState } from 'react'
import { Button, MessagePlugin } from 'tdesign-react'
import { CloudUploadIcon, DownloadIcon, RefreshIcon } from 'tdesign-icons-react'
import { apiService, getApiErrorMessage } from '../services/api'

interface TextEntry {
  id: string
  original_text: string
  translated_text: string
  entity_type: string
  layer: string
  position: string
}

interface ExtractionResult {
  task_id: string
  text_count: number
  excel_file: string
  texts: TextEntry[]
}

interface TranslationResult {
  task_id: string
  translation_count: number
  translated_cad_file: string
}

const languageOptions = [
  { label: 'English', value: 'en' },
  { label: 'Chinese', value: 'zh' },
  { label: 'Japanese', value: 'ja' },
  { label: 'Korean', value: 'ko' },
  { label: 'Deutsch', value: 'de' },
  { label: 'French', value: 'fr' },
  { label: 'Russian', value: 'ru' },
]

const backendOptions = [
  { label: 'AutoCAD Engine', value: 'autocad_com' },
  { label: 'GstarCAD Engine', value: 'gstar_com' },
  { label: 'ODA CLI', value: 'oda_cli' },
  { label: 'LibreDWG CLI', value: 'libredwg_cli' },
  { label: 'DXF Native', value: 'dxf_native' },
  { label: 'Auto Fallback', value: 'auto' },
]

const workflowModes = [
  { label: 'CAD Translation', value: 'translate' },
  { label: 'Extract Only', value: 'extract' },
]

const CADWorkflow: React.FC = () => {
  const [currentStep, setCurrentStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [glossaryFile, setGlossaryFile] = useState<File | null>(null)
  const [extractionResult, setExtractionResult] = useState<ExtractionResult | null>(null)
  const [textDictionary, setTextDictionary] = useState<TextEntry[]>([])
  const [targetLanguage, setTargetLanguage] = useState('ru')
  const [converterBackend, setConverterBackend] = useState('auto')
  const [workflowMode, setWorkflowMode] = useState('translate')
  const [batchSize, setBatchSize] = useState(12)
  const [temperature, setTemperature] = useState(0.7)
  const [retryCount, setRetryCount] = useState(2)
  const [translationProgress, setTranslationProgress] = useState(0)
  const [finalResult, setFinalResult] = useState<TranslationResult | null>(null)
  const [processingLog, setProcessingLog] = useState<string[]>([
    'Upload DWG/DXF file to start extraction.',
    'Dictionary rows will appear after the extract step succeeds.',
  ])

  const stats = useMemo(
    () => ({
      total: textDictionary.length,
      translated: textDictionary.filter((entry) => entry.translated_text).length,
      remaining: textDictionary.filter((entry) => !entry.translated_text).length,
    }),
    [textDictionary],
  )

  const appendLog = (line: string) => {
    setProcessingLog((current) => [line, ...current].slice(0, 8))
  }

  const handleFileUpload = async (file: File) => {
    const fileExtension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'))
    if (!['.dwg', '.dxf'].includes(fileExtension)) {
      setError('Only DWG or DXF files are supported.')
      return
    }

    setUploadedFile(file)
    setLoading(true)
    setError('')
    setFinalResult(null)
    appendLog(`Uploading ${file.name} to extract CAD text...`)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('converter_backend', converterBackend)
      formData.append('target_language', targetLanguage)
      const response: any = await apiService.cad.extract(formData)
      const payload = response?.data || response
      setExtractionResult(payload)
      setTextDictionary(payload?.texts || [])
      setCurrentStep(2)
      appendLog(`Extraction complete. ${payload?.text_count || 0} text rows loaded.`)
      MessagePlugin.success('CAD text extracted')
    } catch (caughtError: any) {
      const message = getApiErrorMessage(caughtError, 'CAD extract failed')
      setError(message)
      appendLog(`Extraction failed: ${message}`)
      MessagePlugin.error(message)
    } finally {
      setLoading(false)
    }
  }

  const handleTranslateDictionary = async () => {
    if (!textDictionary.length) return
    setLoading(true)
    setError('')
    setTranslationProgress(0)
    appendLog(`Starting AI batch translation to ${targetLanguage.toUpperCase()}...`)
    const updatedDictionary = [...textDictionary]

    try {
      for (let index = 0; index < textDictionary.length; index += batchSize) {
        const batch = textDictionary.slice(index, index + batchSize)
        const response: any = await apiService.cad.translateBatch({
          texts: batch.map((entry) => entry.original_text),
          target_lang: targetLanguage,
        })
        const payload = response?.data || response
        const translatedTexts = payload?.translated_texts || payload?.data?.translated_texts || []
        if (!translatedTexts.length) throw new Error(payload?.detail || payload?.message || 'Batch translation failed')

        translatedTexts.forEach((translatedText: string, batchIndex: number) => {
          if (updatedDictionary[index + batchIndex]) {
            updatedDictionary[index + batchIndex].translated_text = translatedText
          }
        })

        setTextDictionary([...updatedDictionary])
        setTranslationProgress(Math.round(((index + batch.length) / textDictionary.length) * 100))
      }

      setCurrentStep(3)
      appendLog(`Translation complete. ${updatedDictionary.length} rows processed.`)
      MessagePlugin.success('Dictionary translated')
    } catch (caughtError: any) {
      const message = getApiErrorMessage(caughtError, 'Batch translation failed')
      setError(message)
      appendLog(`Translation failed: ${message}`)
      MessagePlugin.error(message)
    } finally {
      setLoading(false)
    }
  }

  const handleApplyTranslation = async () => {
    if (!extractionResult) return
    setLoading(true)
    setError('')
    appendLog('Applying translated dictionary back into CAD output...')

    try {
      const response: any = await apiService.cad.applyTranslation({
        task_id: extractionResult.task_id,
        translations: textDictionary.map((entry) => ({
          original: entry.original_text,
          translated: entry.translated_text,
        })),
      })
      const payload = response?.data || response
      setFinalResult(payload)
      setCurrentStep(4)
      appendLog('CAD output package is ready for download.')
      MessagePlugin.success('Translation applied to CAD output')
    } catch (caughtError: any) {
      const message = getApiErrorMessage(caughtError, 'Apply translation failed')
      setError(message)
      appendLog(`Apply failed: ${message}`)
      MessagePlugin.error(message)
    } finally {
      setLoading(false)
    }
  }

  const handleDictionaryChange = (index: number, value: string) => {
    setTextDictionary((current) => current.map((entry, entryIndex) => (entryIndex === index ? { ...entry, translated_text: value } : entry)))
  }

  const downloadFile = (url: string, filename: string) => {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const resetWorkflow = () => {
    setCurrentStep(1)
    setLoading(false)
    setError('')
    setUploadedFile(null)
    setGlossaryFile(null)
    setExtractionResult(null)
    setTextDictionary([])
    setFinalResult(null)
    setTranslationProgress(0)
    setProcessingLog(['Upload DWG/DXF file to start extraction.'])
  }

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel-compact">
        <div className="hero-copy">
          <div className="eyebrow">CAD Workspace</div>
          <h1 className="page-title">Upload and translate CAD drawings</h1>
          <p className="page-subtitle">
            A split-pane workbench for file upload, extraction, editable translation rows, and output packaging.
          </p>

          <div className="hero-status-row">
            <span className="status-chip status-chip-neutral">Step {currentStep} of 4</span>
            <span className="status-chip status-chip-success">Rows: {stats.total}</span>
            <span className="status-chip status-chip-neutral">Remaining: {stats.remaining}</span>
          </div>
        </div>

        <div className="hero-actions">
          <Button theme="primary" loading={loading} disabled={!textDictionary.length} onClick={() => void handleTranslateDictionary()}>
            Translate Dictionary
          </Button>
          <Button variant="outline" onClick={resetWorkflow}>
            <RefreshIcon className="mr-1" />
            Reset
          </Button>
        </div>
      </section>

      {error && <div className="notice-card warning-card">{error}</div>}

      <section className="workspace-shell">
        <aside className="rail-stack">
          <article className="rail-card">
            <div className="section-kicker">1. Workflow</div>
            <h2 className="section-heading">Choose job type</h2>
            <div className="segmented-toggle segmented-toggle-wide">
              {workflowModes.map((mode) => (
                <button
                  key={mode.value}
                  type="button"
                  className={workflowMode === mode.value ? 'segment-active' : ''}
                  onClick={() => setWorkflowMode(mode.value)}
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <p className="rail-note">CAD Translation keeps the extraction, translation, and apply steps linked.</p>
          </article>

          <article className="rail-card">
            <div className="section-kicker">2. CAD Options</div>
            <h2 className="section-heading">File + engine settings</h2>

            <label className="form-field">
              <span>Target Language</span>
              <select className="input-shell" value={targetLanguage} onChange={(e) => setTargetLanguage(e.target.value)}>
                {languageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="form-field">
              <span>Converter Backend</span>
              <select className="input-shell" value={converterBackend} onChange={(e) => setConverterBackend(e.target.value)}>
                {backendOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </article>

          <article className="rail-card">
            <div className="section-kicker">3. Translation Model</div>
            <h2 className="section-heading">Batch tuning</h2>
            <div className="range-group">
              <div className="range-header">
                <span>Batch Size</span>
                <strong>{batchSize}</strong>
              </div>
              <input type="range" min="1" max="24" value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} />
            </div>
            <div className="range-group">
              <div className="range-header">
                <span>Temperature</span>
                <strong>{temperature.toFixed(1)}</strong>
              </div>
              <input type="range" min="0" max="2" step="0.1" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
            </div>
            <div className="range-group">
              <div className="range-header">
                <span>Retry Count</span>
                <strong>{retryCount}</strong>
              </div>
              <input type="range" min="0" max="5" value={retryCount} onChange={(e) => setRetryCount(Number(e.target.value))} />
            </div>
          </article>

          <article className="rail-card">
            <div className="section-kicker">4. Translation Config</div>
            <h2 className="section-heading">Status and logs</h2>
            <div className="status-stack">
              <div className="detail-row">
                <span>Extraction</span>
                <strong>{extractionResult ? 'Done' : 'Waiting'}</strong>
              </div>
              <div className="detail-row">
                <span>Translation</span>
                <strong>{stats.translated ? `${stats.translated}/${stats.total}` : 'Waiting'}</strong>
              </div>
              <div className="detail-row">
                <span>Output</span>
                <strong>{finalResult ? 'Ready' : 'Pending'}</strong>
              </div>
            </div>
            <div className="log-shell">
              {processingLog.map((line) => (
                <div key={line} className="log-line">
                  {line}
                </div>
              ))}
            </div>
          </article>

          <article className="rail-card">
            <div className="section-kicker">5. Glossary</div>
            <h2 className="section-heading">CSV glossary upload</h2>
            <label className="upload-zone upload-zone-compact">
              <input
                type="file"
                accept=".csv"
                className="hidden-input"
                onChange={(event) => {
                  const file = event.target.files?.[0] || null
                  setGlossaryFile(file)
                  appendLog(file ? `Glossary selected: ${file.name}` : 'Glossary cleared.')
                }}
              />
              <CloudUploadIcon size="42px" />
              <span className="upload-title">{glossaryFile ? glossaryFile.name : 'Drop glossary CSV here'}</span>
              <span className="upload-subtitle">Optional local glossary for operator workflows</span>
            </label>
          </article>
        </aside>

        <div className="workspace-main">
          <article className="surface-card">
            <div className="card-header-row">
              <div>
                <div className="section-kicker">Upload</div>
                <h2 className="section-heading">CAD file intake</h2>
              </div>
              <div className="hero-actions">
                <Button theme="primary" loading={loading} disabled={!uploadedFile} onClick={() => void handleTranslateDictionary()}>
                  AI Batch Translate
                </Button>
                <Button variant="outline" disabled={!extractionResult?.excel_file} onClick={() => extractionResult?.excel_file && downloadFile(extractionResult.excel_file, 'dictionary.xlsx')}>
                  <DownloadIcon className="mr-1" />
                  Download Excel
                </Button>
                <Button theme="success" loading={loading} disabled={!stats.total || stats.remaining > 0} onClick={() => void handleApplyTranslation()}>
                  Apply to CAD
                </Button>
              </div>
            </div>

            <label className="upload-zone upload-zone-main">
              <input
                type="file"
                accept=".dwg,.dxf"
                className="hidden-input"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void handleFileUpload(file)
                }}
              />
              <CloudUploadIcon size="52px" />
              <span className="upload-title">{uploadedFile ? uploadedFile.name : 'Click to upload a DWG or DXF file'}</span>
              <span className="upload-subtitle">Supports local CAD drawings and returns an editable text dictionary.</span>
            </label>

            {loading && (
              <div className="progress-shell">
                <div className="progress-label">Processing progress</div>
                <div className="progress-bar">
                  <span style={{ width: `${translationProgress || 25}%` }} />
                </div>
              </div>
            )}

            <div className="workflow-strip">
              {['Upload', 'Extract', 'Translate', 'Apply'].map((step, index) => (
                <div key={step} className={`workflow-step${currentStep >= index + 1 ? ' workflow-step-active' : ''}`}>
                  <span>{index + 1}</span>
                  <strong>{step}</strong>
                </div>
              ))}
            </div>
          </article>

          <article className="surface-card">
            <div className="card-header-row">
              <div>
                <div className="section-kicker">Dictionary</div>
                <h2 className="section-heading">Editable CAD text grid</h2>
              </div>
              <span className="status-chip status-chip-neutral">
                {stats.translated}/{stats.total} translated
              </span>
            </div>

            <div className="dictionary-table">
              <div className="dictionary-head">
                <span>Original Text</span>
                <span>Translated Text</span>
                <span>Entity Type</span>
                <span>Layer</span>
              </div>

              {(textDictionary.slice(0, 14) || []).map((entry, index) => (
                <div key={entry.id} className="dictionary-row">
                  <div className="dictionary-original">{entry.original_text}</div>
                  <input
                    className="dictionary-input"
                    value={entry.translated_text || ''}
                    onChange={(event) => handleDictionaryChange(index, event.target.value)}
                    placeholder="Enter translated text"
                  />
                  <div className="dictionary-meta">{entry.entity_type || '-'}</div>
                  <div className="dictionary-meta">{entry.layer || '-'}</div>
                </div>
              ))}

              {!textDictionary.length && (
                <div className="empty-state empty-state-large">
                  Upload a CAD file first. Extracted dictionary entries will appear here.
                </div>
              )}
            </div>
          </article>

          <article className="surface-card result-card">
            <div className="card-header-row">
              <div>
                <div className="section-kicker">Output</div>
                <h2 className="section-heading">Download package</h2>
              </div>
            </div>

            <div className="result-grid">
              <div className="result-item">
                <div className="result-item-title">Translated CAD</div>
                <div className="result-item-meta">
                  {finalResult?.translated_cad_file ? 'Translated output ready' : 'Waiting for apply step'}
                </div>
                <Button
                  theme="primary"
                  disabled={!finalResult?.translated_cad_file}
                  onClick={() => finalResult?.translated_cad_file && downloadFile(finalResult.translated_cad_file, 'translated-output.dxf')}
                >
                  <DownloadIcon className="mr-1" />
                  Download
                </Button>
              </div>

              <div className="result-item">
                <div className="result-item-title">Dictionary Export</div>
                <div className="result-item-meta">
                  {extractionResult?.excel_file ? 'Excel dictionary ready' : 'Generated after extract step'}
                </div>
                <Button
                  variant="outline"
                  disabled={!extractionResult?.excel_file}
                  onClick={() => extractionResult?.excel_file && downloadFile(extractionResult.excel_file, 'dictionary.xlsx')}
                >
                  <DownloadIcon className="mr-1" />
                  Download
                </Button>
              </div>
            </div>
          </article>
        </div>
      </section>
    </div>
  )
}

export default CADWorkflow
