import axios from 'axios'

export const API_BASE_URL = ((import.meta as any).env?.VITE_API_BASE_URL as string) || '/api'
export const API_ORIGIN = API_BASE_URL.replace(/\/api\/?$/, '') || ''
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

export const getApiErrorMessage = (error: any, fallback = 'Request failed'): string => {
  return (
    error?.response?.data?.error ||
    error?.response?.data?.detail ||
    error?.message ||
    fallback
  )
}

export const apiService = {
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
    upload: (formData: FormData): Promise<any> =>
      api.post('/cad/upload', formData, {
        ...LONG_RUNNING_REQUEST,
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    translateBatch: (payload: { texts: string[]; target_lang: string }): Promise<any> =>
      api.post('/cad/translate-batch', payload, LONG_RUNNING_REQUEST),
    applyTranslation: (payload: { task_id: string; translations: Array<{ original: string; translated: string }> }): Promise<any> =>
      api.post('/cad/apply-translation', payload, LONG_RUNNING_REQUEST),
    listTasks: (): Promise<any> => api.get('/cad/tasks'),
    stopAllTasks: (): Promise<any> => api.post('/cad/tasks/stop-all'),
    clearAllTasks: (): Promise<any> => api.delete('/cad/tasks'),
    resumeTask: (taskId: string, payload: Record<string, unknown>): Promise<any> => api.post(`/cad/tasks/${taskId}/resume`, payload, LONG_RUNNING_REQUEST),
    getTaskLogs: (taskId: string): Promise<any> => api.get(`/cad/tasks/${taskId}/logs`),
    deleteTask: (taskId: string): Promise<any> => api.delete(`/cad/tasks/${taskId}`),
    download: async (taskId: string, fileType: 'excel' | 'cad' | 'log' | 'translated_cad') => {
      const response = await axios.get(`${API_BASE_URL}/cad/download/${taskId}/${fileType}`, {
        responseType: 'blob',
      })
      return response.data
    },
    downloadPackage: async (taskIds: string[]) => {
      const response = await axios.post(`${API_BASE_URL}/cad/download-package`, { task_ids: taskIds }, {
        responseType: 'blob',
      })
      return response.data
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
