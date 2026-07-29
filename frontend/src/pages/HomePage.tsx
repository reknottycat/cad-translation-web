import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, MessagePlugin } from 'tdesign-react'
import { ArrowRightIcon, RefreshIcon } from 'tdesign-icons-react'
import { apiService } from '../services/api'

interface RuntimeSummary {
  provider?: string
  model?: string
  base_url?: string
  batch_size?: number
  temperature?: number
  timeout_seconds?: number
}

interface TaskRecord {
  task_id: string
  project_name?: string
  task_type?: string
  status?: string
  message?: string
  updated_at?: string | null
}

interface ProjectsSummary {
  counts?: {
    total_projects?: number
    active_projects?: number
    total_files?: number
    translated_texts?: number
  }
  alerts?: {
    failed_tasks?: number
    recoverable_tasks?: number
  }
  recent_tasks?: TaskRecord[]
  last_release?: {
    filename?: string
    updated_at?: string | null
  } | null
}

const HomePage: React.FC = () => {
  const navigate = useNavigate()
  const [runtime, setRuntime] = useState<RuntimeSummary>({})
  const [providerCount, setProviderCount] = useState(0)
  const [summary, setSummary] = useState<ProjectsSummary>({})
  const [health, setHealth] = useState('checking')
  const [loading, setLoading] = useState(false)

  const loadDashboard = async () => {
    setLoading(true)
    try {
      const [healthData, configData, summaryData]: any = await Promise.all([
        apiService.health(),
        apiService.translation.getConfig(),
        apiService.projects.summary(),
      ])

      setHealth(String(healthData?.status || 'unknown'))
      setRuntime(configData?.runtime || {})
      setProviderCount((configData?.provider_presets || []).length)
      setSummary(summaryData || {})
    } catch {
      MessagePlugin.error('Overview data load failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadDashboard()
  }, [])

  const metrics = useMemo(
    () => [
      {
        label: 'Tracked Files',
        value: String(summary?.counts?.total_files || 0),
        hint: 'DWG / DXF / XLSX assets in the workspace',
      },
      {
        label: 'Active Tasks',
        value: String(summary?.counts?.active_projects || 0),
        hint: `${summary?.alerts?.failed_tasks || 0} flagged for attention`,
      },
      {
        label: 'Providers',
        value: String(providerCount || 0),
        hint: runtime.provider || 'No provider selected',
      },
      {
        label: 'Last Release',
        value: summary?.last_release?.filename || 'None yet',
        hint: summary?.last_release?.updated_at || 'No output package',
      },
    ],
    [providerCount, runtime.provider, summary],
  )

  const recentTasks = summary?.recent_tasks || []

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div className="hero-copy">
          <div className="eyebrow">Dashboard</div>
          <h1 className="page-title">CAD Translation Workstation</h1>
          <p className="page-subtitle">
            A dense operating view for extracting CAD text, translating it, and shipping the output back into the drawing.
          </p>

          <div className="hero-status-row">
            <span className="status-chip status-chip-success">Health: {health}</span>
            <span className="status-chip status-chip-neutral">Provider: {runtime.provider || 'custom'}</span>
            <span className="status-chip status-chip-neutral">Model: {runtime.model || 'Not configured'}</span>
          </div>
        </div>

        <div className="hero-actions">
          <Button theme="primary" size="large" onClick={() => navigate('/cad')}>
            Open Workspace <ArrowRightIcon className="ml-1" />
          </Button>
          <Button variant="outline" size="large" onClick={() => navigate('/gateway')}>
            Model Config
          </Button>
          <Button variant="text" size="large" onClick={() => void loadDashboard()} loading={loading}>
            <RefreshIcon className="mr-1" />
            Refresh
          </Button>
        </div>
      </section>

      <section className="metric-grid">
        {metrics.map((item) => (
          <article key={item.label} className="metric-card">
            <div className="metric-label">{item.label}</div>
            <div className="metric-value">{item.value}</div>
            <div className="metric-hint">{item.hint}</div>
          </article>
        ))}
      </section>

      <section className="dashboard-grid">
        <article className="surface-card">
          <div className="card-header-row">
            <div>
              <div className="section-kicker">Recent Tasks</div>
              <h2 className="section-heading">Latest Activity</h2>
            </div>
            <Button variant="text" onClick={() => navigate('/projects')}>
              Open Ledger
            </Button>
          </div>

          <div className="list-stack">
            {(recentTasks.slice(0, 6) || []).map((task) => (
              <button key={task.task_id} type="button" className="list-row-button" onClick={() => navigate('/projects')}>
                <div className="row-primary">
                  <div className="list-row-title">{task.project_name || task.task_id}</div>
                  <div className="list-row-meta">
                    {task.task_type || 'task'} · {task.message || task.updated_at || 'No detail yet'}
                  </div>
                </div>
                <span
                  className={`pill ${
                    task.status === 'failed' || task.status === 'failure'
                      ? 'pill-danger'
                      : task.status === 'completed'
                        ? 'pill-success'
                        : 'pill-neutral'
                  }`}
                >
                  {task.status || 'unknown'}
                </span>
              </button>
            ))}

            {recentTasks.length === 0 && (
              <div className="empty-state">No tasks yet. Start from CAD Workspace to create the first job.</div>
            )}
          </div>
        </article>

        <article className="surface-card">
          <div className="section-kicker">Runtime</div>
          <h2 className="section-heading">Current Model Settings</h2>

          <div className="info-grid">
            <div className="info-cell">
              <span>Base URL</span>
              <strong>{runtime.base_url || 'Not configured'}</strong>
            </div>
            <div className="info-cell">
              <span>Batch Size</span>
              <strong>{runtime.batch_size || '-'}</strong>
            </div>
            <div className="info-cell">
              <span>Temperature</span>
              <strong>{runtime.temperature ?? '-'}</strong>
            </div>
            <div className="info-cell">
              <span>Timeout</span>
              <strong>{runtime.timeout_seconds || '-'}</strong>
            </div>
          </div>

          <div className="quick-panel">
            <button type="button" className="quick-card" onClick={() => navigate('/cad')}>
              <div className="quick-card-title">CAD Workspace</div>
              <div className="quick-card-text">Upload, extract, translate, and apply in one flow.</div>
            </button>
            <button type="button" className="quick-card" onClick={() => navigate('/translation')}>
              <div className="quick-card-title">Text Tools</div>
              <div className="quick-card-text">Single-text testing and Excel batch jobs.</div>
            </button>
            <button type="button" className="quick-card" onClick={() => navigate('/gateway')}>
              <div className="quick-card-title">Model Config</div>
              <div className="quick-card-text">Tune provider, endpoint, and runtime limits.</div>
            </button>
          </div>
        </article>
      </section>
    </div>
  )
}

export default HomePage
