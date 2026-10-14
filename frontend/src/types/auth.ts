/** 认证相关类型（对齐后端 §4.3 A1~A9）。 */

export type UserRole = 'doctor' | 'patient' | 'admin'
export type UserStatus = 'active' | 'disabled' | 'pending'

/** 登录响应中的用户简要信息（A2）。 */
export interface UserBrief {
  user_no: string
  username: string
  name: string | null
  role: UserRole
  avatar_url: string | null
}

/** 个人中心统计（A5）。 */
export interface UserStats {
  total_reports: number
  month_reports: number
}

/** 当前用户资料（A5 `GET /auth/me`）。 */
export interface UserProfile {
  user_no: string
  username: string
  name: string | null
  email: string | null
  phone: string | null
  role: UserRole
  status: UserStatus
  department: string | null
  avatar_url: string | null
  email_verified: boolean
  created_at: string
  last_login_at: string | null
  stats: UserStats
}

/** 令牌对。 */
export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface LoginRequest {
  account: string
  password: string
  remember?: boolean
}

export type LoginResponse = TokenPair & { user: UserBrief }

export interface RegisterRequest {
  username: string
  password: string
  name?: string
  email?: string
  phone?: string
  department?: string
  verify_code: string
}

export interface RegisterResponse {
  user_no: string
  username: string
  role: UserRole
  status: UserStatus
  created_at: string
}

export type VerifyScene = 'register' | 'reset_password'
export type VerifyChannel = 'email' | 'sms'

export interface SendCodeRequest {
  target: string
  scene: VerifyScene
  channel?: VerifyChannel
}

export interface SendCodeResponse {
  sent: boolean
  expires_in: number
}

export interface ForgotRequest {
  account: string
  channel?: VerifyChannel
}

export interface ForgotResponse {
  sent: boolean
}

export interface ResetPasswordRequest {
  account: string
  new_password: string
  verify_code?: string
  reset_token?: string
}

export interface ResetPasswordResponse {
  reset: boolean
}

export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}

export interface ChangePasswordResponse {
  changed: boolean
}

/** 更新个人资料请求（A10）。未提交的字段保持不变，空串表示清空。 */
export interface UpdateProfileRequest {
  name?: string | null
  phone?: string | null
  department?: string | null
}