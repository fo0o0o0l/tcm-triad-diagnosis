/** 通用 API 类型（《开发任务文档》§4.1 统一响应体）。 */

/** 后端统一响应结构：`{ code, message, data, trace_id }`。 */
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  trace_id: string
}

/** 分页响应通用结构（§4.1）。 */
export interface PageResult<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

/** 参数校验失败时 `data.fields` 的结构（§4.3 A1 失败示例）。 */
export interface FieldError {
  field: string
  error: string
}