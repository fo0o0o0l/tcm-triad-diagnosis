/** 认证 API 服务（对齐后端 §4.3 A1~A11）。 */

import { API_BASE_URL, http } from '@/utils/request'
import type {
  ChangePasswordRequest,
  ChangePasswordResponse,
  ForgotRequest,
  ForgotResponse,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RegisterResponse,
  ResetPasswordRequest,
  ResetPasswordResponse,
  SendCodeRequest,
  SendCodeResponse,
  UpdateProfileRequest,
  UserProfile,
} from '@/types/auth'

export interface LogoutResponse {
  revoked: boolean
}

export const authApi = {
  /** A1 注册 */
  register: (payload: RegisterRequest) => http.post<RegisterResponse>('/auth/register', payload),

  /** A2 登录 */
  login: (payload: LoginRequest) => http.post<LoginResponse>('/auth/login', payload),

  /** A3 刷新令牌 */
  refresh: (refreshToken: string) =>
    http.post<LoginResponse>('/auth/refresh', { refresh_token: refreshToken }),

  /** A4 登出 */
  logout: (refreshToken: string) =>
    http.post<LogoutResponse>('/auth/logout', { refresh_token: refreshToken }),

  /** A5 当前用户信息 */
  me: () => http.get<UserProfile>('/auth/me'),

  /** A6 发送验证码 */
  sendCode: (payload: SendCodeRequest) => http.post<SendCodeResponse>('/auth/verify-code', payload),

  /** A7 发起找回 */
  forgotPassword: (payload: ForgotRequest) =>
    http.post<ForgotResponse>('/auth/password/forgot', payload),

  /** A8 重置密码 */
  resetPassword: (payload: ResetPasswordRequest) =>
    http.post<ResetPasswordResponse>('/auth/password/reset', payload),

  /** A9 修改密码（登录态） */
  changePassword: (payload: ChangePasswordRequest) =>
    http.post<ChangePasswordResponse>('/auth/password/change', payload),

  /** A10 更新个人资料（姓名 / 手机 / 科室） */
  updateProfile: (payload: UpdateProfileRequest) => http.patch<UserProfile>('/auth/me', payload),

  /** A11 上传头像；FormData 交由浏览器自动设置 multipart 边界 */
  uploadAvatar: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<UserProfile>('/auth/avatar', form)
  },

  /** 头像地址：后端返回相对 `/api/v1` 的路径，需拼接基地址后交给 `<img>` */
  avatarUrl: (path: string | null | undefined) => (path ? `${API_BASE_URL}${path}` : null),
}