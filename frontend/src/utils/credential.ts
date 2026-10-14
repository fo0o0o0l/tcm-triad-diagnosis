/**
 * 凭据本地记忆（UI/UX §5.1.4「自实现方案」）。
 *
 * 安全约束：密码禁止明文落盘。采用「设备本地密钥 + AES-GCM」：
 * - 密钥以不可导出（extractable=false）的 CryptoKey 形式存放于 IndexedDB，
 *   JS 无法读取其原始字节，密钥不离开当前设备；
 * - 密码用随机 IV 加密后，以 `{iv, ct}`（base64）形式存于 localStorage。
 *
 * 仅在安全上下文（HTTPS / localhost）可用；不可用时静默降级为「不记忆密码」。
 */

const DB_NAME = 'tcm_cred'
const STORE_NAME = 'keys'
const KEY_ID = 'device_key'
const STORAGE_KEY = 'tcm_saved_cred'

const encoder = new TextEncoder()
const decoder = new TextDecoder()

function toBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

function fromBase64(value: string): Uint8Array<ArrayBuffer> {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

export function isCredentialStorageSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof crypto !== 'undefined' &&
    typeof crypto.subtle !== 'undefined' &&
    typeof indexedDB !== 'undefined'
  )
}

function openKeyDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function readKey(db: IDBDatabase): Promise<CryptoKey | null> {
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(KEY_ID)
    request.onsuccess = () => resolve((request.result as CryptoKey | undefined) ?? null)
    request.onerror = () => reject(request.error)
  })
}

function writeKey(db: IDBDatabase, key: CryptoKey): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put(key, KEY_ID)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

/** 读取或首次生成设备本地密钥（不可导出，仅本机可用）。 */
async function getDeviceKey(): Promise<CryptoKey> {
  const db = await openKeyDb()
  try {
    const existing = await readKey(db)
    if (existing) return existing
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
      'encrypt',
      'decrypt',
    ])
    await writeKey(db, key)
    return key
  } finally {
    db.close()
  }
}

/** 登录成功后写入（仅在勾选「记住用户名和密码」时调用）。 */
export async function saveCredential(username: string, password: string): Promise<void> {
  if (!isCredentialStorageSupported()) return
  try {
    const key = await getDeviceKey()
    const iv = crypto.getRandomValues(new Uint8Array(12))
    const cipher = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      key,
      encoder.encode(password),
    )
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ v: 1, username, iv: toBase64(iv), ct: toBase64(new Uint8Array(cipher)) }),
    )
  } catch {
    // 存储失败不应阻断登录流程
  }
}

/** 进入登录页时读取并解密，用于自动回填账号与密码。 */
export async function loadCredential(): Promise<{ username: string; password: string } | null> {
  if (!isCredentialStorageSupported()) return null
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as { username?: string; iv?: string; ct?: string }
    if (!parsed.username || !parsed.iv || !parsed.ct) return null
    const key = await getDeviceKey()
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: fromBase64(parsed.iv) },
      key,
      fromBase64(parsed.ct),
    )
    return { username: parsed.username, password: decoder.decode(plain) }
  } catch {
    // 密钥丢失或内容损坏：清理避免反复失败
    clearCredential()
    return null
  }
}

/** 清除已保存的登录信息（保留设备密钥）。 */
export function clearCredential(): void {
  localStorage.removeItem(STORAGE_KEY)
}