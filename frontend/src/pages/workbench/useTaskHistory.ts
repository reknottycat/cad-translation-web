import { Dispatch, SetStateAction, useEffect, useRef, useState } from 'react'
import { apiService, getApiErrorMessage } from '../../services/api'
import { BackendCadTask } from './model'

export const useTaskHistory = (setGlobalMessage: Dispatch<SetStateAction<string>>) => {
  const [backendTasks, setBackendTasks] = useState<BackendCadTask[]>([])
  const [backendTasksLoading, setBackendTasksLoading] = useState(false)
  const [selectedBackendTaskId, setSelectedBackendTaskId] = useState<string | null>(null)
  const [taskLogs, setTaskLogs] = useState('')
  const [logsLoading, setLogsLoading] = useState(false)
  const requestInFlight = useRef(false)
  const updatedAfter = useRef<number | undefined>(undefined)

  const refreshBackendTasks = async (silent = false, full = false) => {
    if (requestInFlight.current) return
    requestInFlight.current = true
    if (!silent) setBackendTasksLoading(true)
    try {
      const collected: BackendCadTask[] = []
      let offset = 0
      let total = 0
      do {
        const response: any = await apiService.cad.listTasks({ limit: 100, offset, updated_after: full ? undefined : updatedAfter.current })
        const page = Array.isArray(response?.data) ? response.data : Array.isArray(response) ? response : []
        collected.push(...page)
        total = Number(response?.total ?? page.length)
        offset += page.length
        if (!page.length) break
      } while (offset < total)
      const newest = collected.reduce((latest, task) => Math.max(latest, Number(task.last_activity_at || task.created_at || 0)), updatedAfter.current || 0)
      if (newest) updatedAfter.current = Math.max(0, newest - 0.001)
      setBackendTasks((current) => {
        if (full) return collected
        const byId = new Map(current.map((task) => [task.task_id, task]))
        collected.forEach((task) => byId.set(task.task_id, task))
        return Array.from(byId.values()).sort((left, right) => Number(right.created_at || 0) - Number(left.created_at || 0))
      })
      setSelectedBackendTaskId((current) => current || collected[0]?.task_id || null)
    } catch (error) {
      if (!silent) setGlobalMessage(getApiErrorMessage(error, 'Task list load failed'))
    } finally {
      if (!silent) setBackendTasksLoading(false)
      requestInFlight.current = false
    }
  }

  const fetchTaskLogs = async (taskId: string) => {
    if (!taskId) return
    setLogsLoading(true)
    try { const response: any = await apiService.cad.getTaskLogs(taskId); setTaskLogs(response?.data?.logs || response?.logs || '暂无日志') }
    catch (error) { setTaskLogs(`获取日志失败: ${getApiErrorMessage(error, 'Unknown error')}`) }
    finally { setLogsLoading(false) }
  }

  useEffect(() => { void refreshBackendTasks(false, true) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!backendTasks.length) setSelectedBackendTaskId(null)
    else if (!backendTasks.some((task) => task.task_id === selectedBackendTaskId)) setSelectedBackendTaskId(backendTasks[0].task_id)
  }, [backendTasks, selectedBackendTaskId])
  useEffect(() => {
    let timer: number | undefined
    let stopped = false
    const schedule = () => {
      if (stopped) return
      timer = window.setTimeout(async () => { await refreshBackendTasks(true); schedule() }, document.visibilityState === 'hidden' ? 15000 : 3000)
    }
    const onVisibilityChange = () => { if (timer) window.clearTimeout(timer); if (document.visibilityState === 'visible') void refreshBackendTasks(true); schedule() }
    document.addEventListener('visibilitychange', onVisibilityChange); schedule()
    return () => { stopped = true; if (timer) window.clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibilityChange) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (selectedBackendTaskId) void fetchTaskLogs(selectedBackendTaskId); else setTaskLogs('') }, [selectedBackendTaskId])

  return { backendTasks, backendTasksLoading, selectedBackendTaskId, setSelectedBackendTaskId, taskLogs, logsLoading, refreshBackendTasks }
}
