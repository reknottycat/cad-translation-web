import { Button } from 'tdesign-react'
import { CloudUploadIcon, DeleteIcon, DownloadIcon, RefreshIcon } from 'tdesign-icons-react'
import { BackendCadTask, QueueTask, toTitle } from './model'

interface Props { vm: any }

export const WorkbenchWorkspace = ({ vm }: Props) => {
  const { files, selectedTaskId, setSelectedTaskId, backendTasks, backendTasksLoading, selectedBackendTaskId, setSelectedBackendTaskId, processing, stoppingTasks, deletingTaskId, downloadingPackage, configMessage, isMainDropActive, taskLogs, logsLoading, mainFileInputRef, selectedBackendTask, backendTaskStats, appendFiles, handleMainDragOver, handleMainDragLeave, handleMainDrop, removeTask, refreshBackendTasks, resumeBackendTask, restartBackendTask, getBackendTaskStatus, hasStoppableTasks, getBackendTaskStatusLabel, hasLocalTasks, startTask, rerunTask, openOutput, downloadOutput, downloadOutputExcel, downloadPackage, openBackendTaskFile, downloadBackendTaskOutput, deleteBackendTask, stopAllTasks, contentTask, detailBackendTask, detailTaskName, detailTaskStatus, detailTaskProgress, detailTaskType, detailTaskId, detailTaskStage, outputSourceTask, outputBackendTask, outputExcelReady, outputCadReady, packageTaskIds, selectedLocalActionableTask, nextStartableTask, startActionLabel, startActionDisabled, currentActionLabel, selectedBackendOutputCount, fileAccept, getBackendStageLabel } = vm
  return (
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
                  {files.map((task: QueueTask) => (
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
                  {backendTasks.map((task: BackendCadTask) => {
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
                  {backendTasks.map((task: BackendCadTask) => {
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
  )
}
