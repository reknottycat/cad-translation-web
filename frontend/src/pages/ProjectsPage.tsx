import React, { useEffect, useMemo, useState } from 'react'
import { Button, MessagePlugin } from 'tdesign-react'
import { DownloadIcon, RefreshIcon, SearchIcon, DeleteIcon } from 'tdesign-icons-react'
import { apiService } from '../services/api'

interface TaskRecord {
  task_id: string
  original_filename: string
  target_language: string
  extract_only: boolean
  processing_time: string
  text_count: number
  translation_count: number
  files: {
    excel_file?: string
    translated_cad_file?: string
    log_file?: string
  }
}

interface ProjectsSummary {
  counts?: {
    total_projects?: number
    active_projects?: number
    completed_projects?: number
    failed_projects?: number
  }
  alerts?: {
    failed_tasks?: number
    recoverable_tasks?: number
  }
}

const ProjectsPage: React.FC = () => {
  const [tasks, setTasks] = useState<TaskRecord[]>([])
  const [summary, setSummary] = useState<ProjectsSummary>({})
  const [selectedTask, setSelectedTask] = useState<TaskRecord | null>(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'completed' | 'processing' | 'extract'>('all')
  const [loading, setLoading] = useState(false)

  const loadTasks = async () => {
    setLoading(true)
    try {
      const [taskData, summaryData] = await Promise.all([
        apiService.cad.listTasks(),
        apiService.projects.summary(),
      ])
      const rows = (taskData?.data || []) as TaskRecord[]
      setTasks(rows)
      setSummary(summaryData || {})
      setSelectedTask((current) => current || rows[0] || null)
    } catch {
      MessagePlugin.error('Projects load failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadTasks()
  }, [])

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      const matchesSearch = task.original_filename.toLowerCase().includes(search.toLowerCase())
      if (filter === 'all') return matchesSearch
      if (filter === 'extract') return matchesSearch && task.extract_only
      if (filter === 'processing') return matchesSearch && !task.files?.translated_cad_file
      return matchesSearch && Boolean(task.files?.translated_cad_file)
    })
  }, [filter, search, tasks])

  const stats = useMemo(
    () => ({
      total: summary?.counts?.total_projects ?? tasks.length,
      completed: summary?.counts?.completed_projects ?? tasks.filter((item) => item.files?.translated_cad_file).length,
      processing: summary?.counts?.active_projects ?? tasks.filter((item) => !item.files?.translated_cad_file && !item.extract_only).length,
      recoverable: summary?.alerts?.recoverable_tasks ?? 0,
    }),
    [summary, tasks],
  )

  const downloadFile = async (taskId: string, type: 'excel' | 'cad' | 'log') => {
    try {
      const blob = await apiService.cad.download(taskId, type)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${taskId}-${type}`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch {
      MessagePlugin.error(`Download ${type} failed`)
    }
  }

  const removeTask = async (taskId: string) => {
    try {
      await apiService.cad.deleteTask(taskId)
      MessagePlugin.success('Task deleted')
      await loadTasks()
    } catch {
      MessagePlugin.error('Delete failed')
    }
  }

  const statusLabel = (task: TaskRecord): [string, string] => {
    if (task.extract_only) return ['Extract Only', 'pill-neutral']
    if (task.files?.translated_cad_file) return ['Completed', 'pill-success']
    return ['Processing', 'pill-warning']
  }

  const languageLabel = (task: TaskRecord) => (task.target_language ? task.target_language.toUpperCase() : 'N/A')

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel-compact">
        <div className="hero-copy">
          <div className="eyebrow">Projects</div>
          <h1 className="page-title">Task history and output ledger</h1>
          <p className="page-subtitle">
            Review each CAD job, inspect file outputs, and keep a clear record of what has already been translated.
          </p>
        </div>

        <div className="hero-actions">
          <Button theme="danger" variant="outline" loading={loading} onClick={async () => {
            if (window.confirm('Clear all project and CAD task data? This cannot be undone.')) {
              try {
                await apiService.projects.clearAll()
                await apiService.cad.clearAllTasks()
                MessagePlugin.success('All data cleared')
                await loadTasks()
              } catch {
                MessagePlugin.error('Failed to clear data')
              }
            }
          }}>
            <DeleteIcon className="mr-1" />
            Clear Data
          </Button>
          <Button variant="outline" loading={loading} onClick={() => void loadTasks()}>
            <RefreshIcon className="mr-1" />
            Refresh
          </Button>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card">
          <div className="metric-label">Total Tasks</div>
          <div className="metric-value">{stats.total}</div>
          <div className="metric-hint">Tasks stored in the workspace</div>
        </article>
        <article className="metric-card">
          <div className="metric-label">Completed</div>
          <div className="metric-value">{stats.completed}</div>
          <div className="metric-hint">Output packages ready to download</div>
        </article>
        <article className="metric-card">
          <div className="metric-label">Processing</div>
          <div className="metric-value">{stats.processing}</div>
          <div className="metric-hint">Waiting for translation or apply step</div>
        </article>
        <article className="metric-card">
          <div className="metric-label">Recoverable</div>
          <div className="metric-value">{stats.recoverable}</div>
          <div className="metric-hint">Tasks that may benefit from a retry</div>
        </article>
      </section>

      <section className="projects-shell">
        <article className="surface-card projects-main">
          <div className="toolbar-row toolbar-row-wrap">
            <label className="search-shell">
              <SearchIcon />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search filename or task id..." />
            </label>

            <div className="toolbar-filters">
              <select className="input-shell" value={filter} onChange={(e) => setFilter(e.target.value as 'all' | 'completed' | 'processing' | 'extract')}>
                <option value="all">All Status</option>
                <option value="completed">Completed</option>
                <option value="processing">Processing</option>
                <option value="extract">Extract Only</option>
              </select>
            </div>
          </div>

          <div className="project-table">
            <div className="project-table-head">
              <span>Project Name</span>
              <span>Status</span>
              <span>Progress</span>
              <span>Translation Info</span>
              <span>Time</span>
              <span>Actions</span>
            </div>

            {filteredTasks.map((task) => {
              const [label, statusClass] = statusLabel(task)
              const progress = task.files?.translated_cad_file ? 100 : task.extract_only ? 45 : 68
              return (
                <button
                  key={task.task_id}
                  type="button"
                  className={`project-row${selectedTask?.task_id === task.task_id ? ' project-row-active' : ''}`}
                  onClick={() => setSelectedTask(task)}
                >
                  <span className="project-primary">
                    <strong>{task.original_filename}</strong>
                    <small>{task.task_id}</small>
                  </span>
                  <span className={`pill ${statusClass}`}>{label}</span>
                  <span className="progress-inline">
                    <span className="progress-bar">
                      <span style={{ width: `${progress}%` }} />
                    </span>
                    <small>{progress}%</small>
                  </span>
                  <span className="project-meta">
                    {task.translation_count} translated · {languageLabel(task)}
                  </span>
                  <span className="project-meta">{task.processing_time || 'Pending'}</span>
                  <span className="row-actions" onClick={(event) => event.stopPropagation()}>
                    <Button size="small" variant="outline" onClick={() => setSelectedTask(task)}>
                      View
                    </Button>
                    {task.files?.translated_cad_file && (
                      <Button size="small" theme="primary" onClick={() => void downloadFile(task.task_id, 'cad')}>
                        <DownloadIcon />
                      </Button>
                    )}
                  </span>
                </button>
              )
            })}

            {filteredTasks.length === 0 && <div className="empty-state">No project records match the current filters.</div>}
          </div>
        </article>

        <aside className="surface-card project-detail">
          {selectedTask ? (
            <>
              <div className="card-header-row">
                <div>
                  <div className="section-kicker">Task Detail</div>
                  <h2 className="section-heading">{selectedTask.original_filename}</h2>
                </div>
                <span className={`pill ${statusLabel(selectedTask)[1]}`}>{statusLabel(selectedTask)[0]}</span>
              </div>

              <div className="detail-section">
                <div className="detail-row">
                  <span>Task ID</span>
                  <strong>{selectedTask.task_id}</strong>
                </div>
                <div className="detail-row">
                  <span>Target Language</span>
                  <strong>{languageLabel(selectedTask)}</strong>
                </div>
                <div className="detail-row">
                  <span>Extracted Texts</span>
                  <strong>{selectedTask.text_count}</strong>
                </div>
                <div className="detail-row">
                  <span>Translated Texts</span>
                  <strong>{selectedTask.translation_count}</strong>
                </div>
                <div className="detail-row">
                  <span>Processing Time</span>
                  <strong>{selectedTask.processing_time || 'Pending'}</strong>
                </div>
              </div>

              <div className="detail-section">
                <div className="detail-heading">Status Notes</div>
                <div className={`notice-card ${selectedTask.files?.translated_cad_file ? 'success-card' : 'warning-card'}`}>
                  {selectedTask.extract_only
                    ? 'Text extraction completed. This task has not written a translated CAD file yet.'
                    : selectedTask.files?.translated_cad_file
                      ? 'Translation has been applied. Download files are ready.'
                      : 'The task is waiting for translation or CAD apply.'}
                </div>
              </div>

              <div className="detail-section">
                <div className="detail-heading">Downloads</div>
                <div className="detail-actions">
                  <Button variant="outline" onClick={() => void downloadFile(selectedTask.task_id, 'excel')}>
                    Dictionary
                  </Button>
                  <Button
                    theme="primary"
                    disabled={!selectedTask.files?.translated_cad_file}
                    onClick={() => void downloadFile(selectedTask.task_id, 'cad')}
                  >
                    CAD Output
                  </Button>
                </div>
                <div className="detail-actions">
                  <Button variant="text" onClick={() => void downloadFile(selectedTask.task_id, 'log')}>
                    Log File
                  </Button>
                  <Button theme="danger" variant="outline" onClick={() => void removeTask(selectedTask.task_id)}>
                    Delete
                  </Button>
                </div>
              </div>

              <div className="detail-section">
                <div className="detail-heading">Output Snapshot</div>
                <div className="result-grid result-grid-single">
                  <div className="result-item">
                    <div className="result-item-title">Dictionary</div>
                    <div className="result-item-meta">{selectedTask.files?.excel_file ? 'Ready' : 'Not generated yet'}</div>
                  </div>
                  <div className="result-item">
                    <div className="result-item-title">CAD File</div>
                    <div className="result-item-meta">{selectedTask.files?.translated_cad_file ? 'Ready' : 'Waiting'}</div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="empty-state">Select a task to view dictionary, logs, and output files.</div>
          )}
        </aside>
      </section>
    </div>
  )
}

export default ProjectsPage
