/**
 * 三诊共用会话标识（UI/UX §4.1 会话状态；会话服务接入前的前端占位实现）。
 *
 * 舌诊 / 面诊 / 问诊共用同一个 `session_id`，使左侧常驻步骤条切换模块后
 * 仍能读取同一会话下各诊位已采集、已分析的数据。
 * 解析优先级：URL 查询参数 `?session_id=` > sessionStorage 缓存 > 新生成。
 */

export const SESSION_KEY = 'tcm_session_id'

const SESSION_QUERY = 'session_id'
/** 当天会话序号计数键前缀（生成 `s_YYYYMMDD_NNNN`，并供展示用的 `#序号` 使用） */
const SESSION_SEQ_KEY = 'tcm_session_seq'

/** 读取并自增当天序号；本地存储不可用时返回 null，由调用方退回随机后缀。 */
function nextDailySequence(date: string): number | null {
  try {
    const raw = Number(localStorage.getItem(`${SESSION_SEQ_KEY}_${date}`) ?? '0')
    const next = (Number.isFinite(raw) ? raw : 0) + 1
    localStorage.setItem(`${SESSION_SEQ_KEY}_${date}`, String(next))
    return next
  } catch {
    return null
  }
}

function generateSessionId(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
  const sequence = nextDailySequence(date)
  if (sequence === null) {
    return `s_${date}_${Math.random().toString(36).slice(2, 6)}`
  }
  return `s_${date}_${String(sequence).padStart(4, '0')}`
}

/**
 * 解析当前会话：命中 URL 参数时回写缓存，保证后续跨模块切换沿用同一会话。
 */
export function resolveSessionId(fromUrl?: string | null): string {
  if (fromUrl) {
    sessionStorage.setItem(SESSION_KEY, fromUrl)
    return fromUrl
  }
  const stored = sessionStorage.getItem(SESSION_KEY)
  if (stored) return stored
  const id = generateSessionId()
  sessionStorage.setItem(SESSION_KEY, id)
  return id
}

/** 读取当前会话（不存在则生成）。 */
export function getSessionId(): string {
  return resolveSessionId(null)
}

/** 为模块路由拼接会话参数，供常驻步骤条切换时保持同一会话。 */
export function withSession(path: string, sessionId: string): string {
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}${SESSION_QUERY}=${encodeURIComponent(sessionId)}`
}

/** 清除当前会话标识（退出登录 / 会话失效时调用），避免下次登录复用上一会话的数据。 */
export function clearSessionId(): void {
  sessionStorage.removeItem(SESSION_KEY)
}

/**
 * 生成并记录一个全新会话标识（「新建会话 / 开始下一位」使用）。
 *
 * 不能只清缓存再跳转：若用户本就在采集页，路由不变会使各页面的 sessionId
 * memo 不重算，新会话不会被创建。故必须显式生成新 id 并随 URL 参数跳转。
 */
export function startNewSession(): string {
  const id = generateSessionId()
  sessionStorage.setItem(SESSION_KEY, id)
  return id
}

/** 会话编号展示所需的患者信息（来源：问诊记录 `patient_snapshot`）。 */
export interface SessionPatient {
  name?: string | null
  anonymous?: boolean | null
}

const SESSION_ID_PATTERN = /^s_(\d{4})(\d{2})(\d{2})_(\d+)$/

/**
 * 会话编号展示值（UI/UX §4.2）：`{患者姓名|待补姓名|匿名患者}_{M月D日}`。
 *
 * - 日期取会话 id 中的创建日期；
 * - 当天第 2 个及以后的会话追加 `#序号`，避免同一患者同天重号；
 * - 问诊未提交 / 未填姓名显示「待补姓名」，开启匿名显示「匿名患者」。
 */
export function sessionDisplayNo(sessionId: string, patient?: SessionPatient | null): string {
  const matched = SESSION_ID_PATTERN.exec(sessionId)
  const now = new Date()
  const month = matched ? Number(matched[2]) : now.getMonth() + 1
  const day = matched ? Number(matched[3]) : now.getDate()
  const sequence = matched ? Number(matched[4]) : 0
  const who = patient?.anonymous ? '匿名患者' : patient?.name?.trim() || '待补姓名'
  const sequenceSuffix = sequence > 1 ? ` #${sequence}` : ''
  return `${who}_${month}月${day}日${sequenceSuffix}`
}
