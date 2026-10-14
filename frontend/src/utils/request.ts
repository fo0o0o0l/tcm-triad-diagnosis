/**
 * HTTP 请求封装（《开发任务文档》§2.5 / UI/UX §7.3）。
 *
 * - 自动附加 `Authorization: Bearer <access_token>`；
 * - 解包统一响应体 `{ code, message, data, trace_id }`，成功时直接返回 `data`；
 * - `code !== 0` 或 HTTP 错误统一抛 `ApiError`；
 * - 遇到 40100 自动用 refresh_token 静默续期一次并重放原请求，失败则清理会话并跳登录。
 */

import axios from 'axios'
import type {
  AxiosError,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios'

import { useAuthStore } from '@/stores/auth'
import type { ApiResponse, FieldError } from '@/types/api'
import type { LoginResponse } from '@/types/auth'

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

const UNAUTHORIZED = 40100
const LOGIN_PATH = '/login'

/** 业务/网络异常的统一载体。 */
export class ApiError extends Error {
  code: number
  traceId: string | null
  data: unknown
  httpStatus: number | null

  constructor(params: {
    code: number
    message: string
    traceId?: string | null
    data?: unknown
    httpStatus?: number | null
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.code = params.code
    this.traceId = params.traceId ?? null
    this.data = params.data ?? null
    this.httpStatus = params.httpStatus ?? null
  }
}

/** 提取参数校验失败的字段级错误（§4.3 A1 失败示例）。 */
export function getFieldErrors(error: unknown): FieldError[] {
  if (error instanceof ApiError && error.data && typeof error.data === 'object') {
    const fields = (error.data as { fields?: FieldError[] }).fields
    if (Array.isArray(fields)) return fields
  }
  return []
}

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean }

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // FormData（如舌象上传）必须移除默认的 JSON Content-Type，交由浏览器自动生成
  // multipart/form-data 与 boundary；否则 axios 会按 JSON 序列化 FormData，导致文件字段丢失。
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    config.headers.delete('Content-Type')
  }
  return config
})

// ---- 静默续期（单飞，避免并发请求重复刷新）----
let refreshPromise: Promise<string> | null = null

async function requestNewAccessToken(): Promise<string> {
  const { refreshToken, updateTokens } = useAuthStore.getState()
  if (!refreshToken) {
    throw new ApiError({ code: UNAUTHORIZED, message: '登录已过期，请重新登录', httpStatus: 401 })
  }
  // 使用裸 axios，避免触发拦截器递归
  const resp = await axios.post<ApiResponse<LoginResponse>>(
    `${API_BASE_URL}/auth/refresh`,
    { refresh_token: refreshToken },
  )
  const payload = resp.data.data
  updateTokens(payload.access_token, payload.refresh_token)
  return payload.access_token
}

function ensureRefreshed(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = requestNewAccessToken().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

function redirectToLogin(): void {
  if (window.location.pathname !== LOGIN_PATH) {
    window.location.assign(LOGIN_PATH)
  }
}

client.interceptors.response.use(
  (response) => {
    const body = response.data as ApiResponse<unknown>
    if (body && typeof body.code === 'number' && body.code !== 0) {
      return Promise.reject(
        new ApiError({
          code: body.code,
          message: body.message,
          traceId: body.trace_id,
          data: body.data,
          httpStatus: response.status,
        }),
      )
    }
    // 统一响应解包：拦截器返回 `data`（类型由 `http` 助手以泛型声明）
    return body?.data as unknown as AxiosResponse
  },
  async (error: AxiosError<ApiResponse<unknown>>) => {
    const status = error.response?.status ?? null
    const body = error.response?.data
    const code = body?.code ?? (status === 401 ? UNAUTHORIZED : (status ?? -1))
    const original = error.config as RetriableConfig | undefined

    const isRefreshCall = Boolean(original?.url?.includes('/auth/refresh'))
    if (code === UNAUTHORIZED && original && !original._retry && !isRefreshCall) {
      original._retry = true
      try {
        const token = await ensureRefreshed()
        original.headers.Authorization = `Bearer ${token}`
        return client(original)
      } catch {
        useAuthStore.getState().clear()
        redirectToLogin()
      }
    }

    return Promise.reject(
      new ApiError({
        code,
        message: body?.message ?? error.message,
        traceId: body?.trace_id ?? null,
        data: body?.data ?? null,
        httpStatus: status,
      }),
    )
  },
)

/** 类型化请求助手：`T` 为解包后的 `data` 类型。 */
export const http = {
  get: <T>(url: string, config?: AxiosRequestConfig) => client.get<T, T>(url, config),
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.post<T, T>(url, data, config),
  patch: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.patch<T, T>(url, data, config),
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.put<T, T>(url, data, config),
  delete: <T>(url: string, config?: AxiosRequestConfig) => client.delete<T, T>(url, config),
}

export default client