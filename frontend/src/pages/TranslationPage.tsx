import React, { useEffect, useState } from 'react'
import { Button, MessagePlugin } from 'tdesign-react'
import { apiService, getApiErrorMessage } from '../services/api'

interface LanguageOption {
  label: string
  value: string
}

const fallbackLanguageOptions: LanguageOption[] = [
  { label: 'Auto Detect', value: 'auto' },
  { label: 'Chinese', value: 'zh' },
  { label: 'English', value: 'en' },
  { label: 'Japanese', value: 'ja' },
  { label: 'Korean', value: 'ko' },
  { label: 'Deutsch', value: 'de' },
  { label: 'French', value: 'fr' },
  { label: 'Russian', value: 'ru' },
]

const TranslationPage: React.FC = () => {
  const [languageOptions, setLanguageOptions] = useState<LanguageOption[]>(fallbackLanguageOptions)
  const [sourceLang, setSourceLang] = useState('auto')
  const [targetLang, setTargetLang] = useState('ru')
  const [input, setInput] = useState('')
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const [excelFile, setExcelFile] = useState<File | null>(null)
  const [excelLoading, setExcelLoading] = useState(false)
  const [downloadUrl, setDownloadUrl] = useState('')

  useEffect(() => {
    const loadLanguages = async () => {
      try {
        const data = await apiService.translation.getLanguages()
        const languages = data?.languages || {}
        const options: LanguageOption[] = [
          { label: 'Auto Detect', value: 'auto' },
          ...Object.entries(languages).map(([value, label]) => ({
            value,
            label: String(label),
          })),
        ]
        setLanguageOptions(options)
        if (data?.default_source) setSourceLang(String(data.default_source))
        if (data?.default_target) setTargetLang(String(data.default_target))
      } catch (error) {
        MessagePlugin.warning(getApiErrorMessage(error, 'Language list fallback to local defaults'))
      }
    }

    void loadLanguages()
  }, [])

  const handleTranslate = async () => {
    if (!input.trim()) return
    setLoading(true)
    try {
      const data = await apiService.translation.translateText({
        text: input,
        source_lang: sourceLang,
        target_lang: targetLang,
      })
      setResult(data?.translated_text || '')
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Text translation failed'))
    } finally {
      setLoading(false)
    }
  }

  const handleExcelSubmit = async () => {
    if (!excelFile) return
    setExcelLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', excelFile)
      formData.append('source_lang', sourceLang)
      formData.append('target_lang', targetLang)
      formData.append('translation_mode', 'add')
      const data = await apiService.translation.translateExcel(formData)
      setDownloadUrl(data?.download_url || '')
      MessagePlugin.success('Excel job submitted')
    } catch (error) {
      MessagePlugin.error(getApiErrorMessage(error, 'Excel translation failed'))
    } finally {
      setExcelLoading(false)
    }
  }

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel-compact">
        <div className="hero-copy">
          <div className="eyebrow">Text Tools</div>
          <h1 className="page-title">Text translation utilities</h1>
          <p className="page-subtitle">
            Use the current runtime to test single text translations and submit Excel batch jobs from the same page.
          </p>
        </div>
      </section>

      <section className="dashboard-grid">
        <article className="surface-card">
          <div className="card-header-row">
            <div>
              <div className="section-kicker">Single Text</div>
              <h2 className="section-heading">Interactive translation test</h2>
            </div>
            <span className="status-chip status-chip-neutral">Text-only</span>
          </div>

          <div className="form-grid form-grid-two">
            <label className="form-field">
              <span>Source Language</span>
              <select value={sourceLang} onChange={(e) => setSourceLang(e.target.value)} className="input-shell">
                {languageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="form-field">
              <span>Target Language</span>
              <select value={targetLang} onChange={(e) => setTargetLang(e.target.value)} className="input-shell">
                {languageOptions.filter((option) => option.value !== 'auto').map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="form-field">
            <span>Input Text</span>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              className="textarea-shell"
              placeholder="Paste CAD notes, labels, or other technical text here..."
            />
          </label>

          <div className="toolbar-row">
            <Button theme="primary" loading={loading} onClick={handleTranslate}>
              Translate
            </Button>
          </div>

          <div className="result-panel">
            <div className="result-block">
              <span className="result-label">Output</span>
              <div className="result-value">{result || 'Translation result will appear here.'}</div>
            </div>
          </div>
        </article>

        <article className="surface-card">
          <div className="section-kicker">Excel Batch</div>
          <h2 className="section-heading">Spreadsheet translation</h2>
          <p className="card-copy">
            Upload `.xlsx` or `.xls` and translate rows using the same runtime settings as the text tool.
          </p>

          <label className="upload-zone upload-zone-compact">
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => setExcelFile(e.target.files?.[0] || null)}
              className="hidden-input"
            />
            <span className="upload-title">{excelFile ? excelFile.name : 'Select Excel file'}</span>
            <span className="upload-subtitle">Supported formats: .xlsx / .xls</span>
          </label>

          <div className="toolbar-row">
            <Button theme="primary" loading={excelLoading} disabled={!excelFile} onClick={handleExcelSubmit}>
              Submit Excel Job
            </Button>
            {downloadUrl && (
              <Button variant="outline" onClick={() => window.open(downloadUrl, '_blank')}>
                Open Download
              </Button>
            )}
          </div>

          <div className="info-grid">
            <div className="info-cell">
              <span>Runtime</span>
              <strong>Current Model Config</strong>
            </div>
            <div className="info-cell">
              <span>Mode</span>
              <strong>Append Translation</strong>
            </div>
            <div className="info-cell">
              <span>Input</span>
              <strong>{excelFile ? 'Ready' : 'Waiting'}</strong>
            </div>
            <div className="info-cell">
              <span>Delivery</span>
              <strong>Excel Download</strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  )
}

export default TranslationPage
