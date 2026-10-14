import { useEffect, useState } from 'react'

import { inquiryApi } from '@/services/api'
import { sessionDisplayNo, type SessionPatient } from '@/utils/session'

interface SessionNoProps {
  sessionId: string
  className?: string
}

/**
 * 会话编号展示（UI/UX §4.2）：`{患者姓名|待补姓名|匿名患者}_{M月D日}[ #序号]`。
 *
 * 患者姓名取自问诊记录 `patient_snapshot`；未提交 / 无记录时按「待补姓名」展示，
 * 拉取失败不阻断页面（编号退化为兜底文案）。
 */
export function SessionNo({ sessionId, className }: SessionNoProps) {
  const [patient, setPatient] = useState<SessionPatient | null>(null)

  useEffect(() => {
    let cancelled = false
    setPatient(null)
    inquiryApi
      .getRecord(sessionId)
      .then((state) => {
        if (cancelled) return
        const snapshot = state.record?.patient_snapshot
        setPatient(snapshot ? { name: snapshot.name, anonymous: snapshot.anonymous } : null)
      })
      .catch(() => {
        // 未提交 / 无记录：保持「待补姓名」兜底
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  return <code className={className}>{sessionDisplayNo(sessionId, patient)}</code>
}
