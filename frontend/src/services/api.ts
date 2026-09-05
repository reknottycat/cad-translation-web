import axios from 'axios'

export const API_BASE_URL = ((import.meta as any).env?.VITE_API_BASE_URL as string) || '/api'
export const API_ORIGIN = API_BASE_URL.replace(/\/api\/?$/, '') || ''
const ADMIN_TOKEN_STORAGE_KEY = 'cad-translation.admin-token'

export const getAdminToken = (): string => {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim() || ''
}

export const setAdminToken = (token: string): void => {
  if (typeof window === 'undefined') return
  const normalized = token.trim()
  if (normalized) window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, normalized)
  else window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
}
export const resolveApiUrl = (path: string) => {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_ORIGIN}${normalizedPath}`
}

const axiosClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

axiosClient.interceptors.request.use((config) => {
  const token = getAdminToken()
  if (token) config.headers.set('X-Admin-Token', token)
  return config
})

const LONG_RUNNING_REQUEST = {
  timeout: 900000,
}

axiosClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
)

const api = {
  get: <T = any>(url: string, config?: any) => axiosClient.get<any, T>(url, config),
  post: <T = any>(url: string, data?: any, config?: any) => axiosClient.post<any, T>(url, data, config),
  put: <T = any>(url: string, data?: any, config?: any) => axiosClient.put<any, T>(url, data, config),
  delete: <T = any>(url: string, config?: any) => axiosClient.delete<any, T>(url, config),
}

const toClientPath = (url: string) => {
  const withoutOrigin = API_ORIGIN && url.startsWith(API_ORIGIN) ? url.slice(API_ORIGIN.length) : url
  return withoutOrigin.replace(/^\/api(?=\/|$)/, '') || '/'
}

export const getApiErrorMessage = (error: any, fallback = 'Request failed'): string => {
  return (
    error?.response?.data?.error ||
    error?.response?.data?.detail ||
    error?.message ||
    fallback
  )
}

export const apiService = {
  downloadBlob: (url: string): Promise<Blob> => api.get(toClientPath(url), { responseType: 'blob' }),
  health: (): Promise<any> => api.get('/health'),

  projects: {
    summary: (): Promise<any> => api.get('/projects/summary'),
    clearAll: (): Promise<any> => api.delete('/projects/clear'),
  },

  cad: {
    getDefaults: (): Promise<any> => api.get('/cad/defaults'),
    saveDefaults: (payload: Record<string, unknown>): Promise<any> => api.post('/cad/defaults', payload),
    extract: (formData: FormData): Promise<any> =>
      api.post('/cad/extract', formData, {
        ...LONG_RUNNING_REQUEST,
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    upload: (formData: FormData, background = true): Promise<any> => {
      formData.set('background', String(background))
      return api.post('/cad/upload', formData, {
        ...LONG_RUNNING_REQUEST,
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    translateBatch: (payload: { texts: string[]; target_lang: string }): Promise<any> =>
      api.post('/cad/translate-batch', payload, LONG_RUNNING_REQUEST),
    applyTranslation: (payload: { task_id: string; translations: Array<{ original: string; translated: string }> }): Promise<any> =>
      api.post('/cad/apply-translation', payload, LONG_RUNNING_REQUEST),
    listTasks: (params?: { limit?: number; offset?: number; updated_after?: number }): Promise<any> =>
      api.get('/cad/tasks', { params }),
    getTask: (taskId: string): Promise<any> => api.get(`/cad/tasks/${taskId}`),
    stopAllTasks: (): Promise<any> => api.post('/cad/tasks/stop-all'),
    clearAllTasks: (): Promise<any> => api.delete('/cad/tasks'),
    resumeTask: (taskId: string, payload: Record<string, unknown>): Promise<any> => api.post(`/cad/tasks/${taskId}/resume`, payload, LONG_RUNNING_REQUEST),
    getTaskLogs: (taskId: string): Promise<any> => api.get(`/cad/tasks/${taskId}/logs`),
    deleteTask: (taskId: string): Promise<any> => api.delete(`/cad/tasks/${taskId}`),
    download: async (taskId: string, fileType: 'excel' | 'cad' | 'log' | 'translated_cad') => {
      return api.get(`/cad/download/${taskId}/${fileType}`, {
        responseType: 'blob',
      })
    },
    downloadPackage: async (taskIds: string[]) => {
      return api.post('/cad/download-package', { task_ids: taskIds }, {
        responseType: 'blob',
      })
    },
  },

  translation: {
    translateText: (payload: { text: string; source_lang: string; target_lang: string }): Promise<any> =>
      api.post('/translation/text', payload),
    translateExcel: (formData: FormData): Promise<any> =>
      api.post('/translation/excel', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    getLanguages: (): Promise<any> => api.get('/translation/languages'),
    getConfig: (): Promise<any> => api.get('/translation/config'),
    getProviders: (): Promise<any> => api.get('/translation/providers'),
    saveConfig: (payload: Record<string, unknown>): Promise<any> => api.post('/translation/config', payload),
    uploadGlossary: (formData: FormData): Promise<any> =>
      api.post('/translation/glossary/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    testConnection: (payload: Record<string, unknown>): Promise<any> => api.post('/translation/test-connection', payload),
    saveCustomProvider: (payload: Record<string, unknown>): Promise<any> => api.post('/translation/providers/custom', payload),
    deleteCustomProvider: (providerId: string): Promise<any> => api.delete(`/translation/providers/custom/${providerId}`),
  },
}

export default axiosClient
