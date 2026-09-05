import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const requestInterceptors: Array<(config: any) => any> = []
  const responseInterceptors: Array<(response: any) => any> = []
  const client = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn((handler) => requestInterceptors.push(handler)) },
      response: { use: vi.fn((handler) => responseInterceptors.push(handler)) },
    },
  }
  return { client, requestInterceptors, responseInterceptors }
})

vi.mock('axios', () => ({
  default: { create: vi.fn(() => mocks.client) },
}))

import { apiService, getAdminToken, setAdminToken } from './api'

const storage = new Map<string, string>()

describe('shared API client contract', () => {
  beforeEach(() => {
    storage.clear()
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
        removeItem: (key: string) => storage.delete(key),
      },
    })
    vi.clearAllMocks()
  })

  it('injects the admin token into the same client used for guarded calls', () => {
    setAdminToken(' shared-secret ')
    const set = vi.fn()
    const config = { headers: { set } }

    expect(getAdminToken()).toBe('shared-secret')
    expect(mocks.requestInterceptors[0](config)).toBe(config)
    expect(set).toHaveBeenCalledWith('X-Admin-Token', 'shared-secret')
  })

  it('downloads blobs through the authenticated client', async () => {
    mocks.client.get.mockResolvedValue(new Blob(['result']))

    await apiService.cad.download('task-1', 'translated_cad')

    expect(mocks.client.get).toHaveBeenCalledWith(
      '/cad/download/task-1/translated_cad',
      { responseType: 'blob' },
    )
  })

  it('submits full CAD uploads to the background job contract', async () => {
    const form = new FormData()
    mocks.client.post.mockResolvedValue({ success: true, data: { task_id: 'task-2' } })

    await apiService.cad.upload(form)

    expect(form.get('background')).toBe('true')
    expect(mocks.client.post).toHaveBeenCalledWith(
      '/cad/upload',
      form,
      expect.objectContaining({ headers: { 'Content-Type': 'multipart/form-data' } }),
    )
  })
})
