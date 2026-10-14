/**
 * 认证状态（Zustand + persist，UI/UX §5.1.4 / §5.8.2）。
 *
 * 会话令牌（access / refresh token）与当前用户以 **sessionStorage** 持久化：
 * - 刷新页面（F5）保留登录态，无需重新登录；
 * - 关闭浏览器 / 标签页后 sessionStorage 清空，登录态随之失效（保留「关闭即登出」的安全意图）。
 *
 * 关于「记住用户名和密码」：勾选时由 credential.ts 以设备本地密钥加密保存在 localStorage
 * （跨浏览器会话保留），仅用于登录页回填，与本 store 的会话持久化相互独立。
 */

import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import type { UserBrief } from '@/types/auth'
import { clearSessionId } from '@/utils/session'

const STORAGE_KEY = 'tcm_auth'

interface SessionPayload {
  accessToken: string
  refreshToken: string
  user: UserBrief
  remember: boolean
}

interface AuthState {
  user: UserBrief | null
  accessToken: string | null
  refreshToken: string | null
  /** 勾选「记住用户名和密码」时记住的账号，用于回填 */
  rememberedAccount: string
  setSession: (payload: SessionPayload) => void
  updateTokens: (accessToken: string, refreshToken: string) => void
  setUser: (user: UserBrief) => void
  clear: (options?: { keepAccount?: boolean }) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      rememberedAccount: '',

      setSession: ({ accessToken, refreshToken, user, remember }) =>
        set({
          accessToken,
          refreshToken,
          user,
          rememberedAccount: remember ? user.username : get().rememberedAccount,
        }),

      updateTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),

      setUser: (user) => set({ user }),

      clear: ({ keepAccount = true } = {}) => {
        // 会话随登录态一起作废：避免重新登录后仍读到上一会话已采集的数据
        clearSessionId()
        set((state) => ({
          user: null,
          accessToken: null,
          refreshToken: null,
          rememberedAccount: keepAccount ? state.rememberedAccount : '',
        }))
      },
    }),
    {
      name: STORAGE_KEY,
      version: 2,
      // 会话存 sessionStorage：刷新保留登录态，关闭浏览器 / 标签页即登出
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        rememberedAccount: state.rememberedAccount,
      }),
      // v1（localStorage，仅 rememberedAccount）→ v2：归一化字段，缺失项取默认值
      migrate: (persisted) => {
        const raw = persisted as Partial<AuthState> | null
        return {
          user: raw?.user ?? null,
          accessToken: raw?.accessToken ?? null,
          refreshToken: raw?.refreshToken ?? null,
          rememberedAccount: raw?.rememberedAccount ?? '',
        }
      },
    },
  ),
)

/** 是否已登录（以 access token 是否存在为准）。 */
export const selectIsAuthenticated = (state: AuthState): boolean => Boolean(state.accessToken)
