import { describeModel } from '@/utils/model'

import styles from './ModelBadge.module.css'

/**
 * 分析结果来源标识：明确展示实际调用的模型名（如「通义千问 qwen-plus」）；
 * 若已降级到本地规则，则显示「本地规则（已降级）」，便于一眼判断是否降级。
 */
export function ModelBadge({ modelVersion }: { modelVersion?: string | null }) {
  const label = describeModel(modelVersion)
  if (!label) return null
  return (
    <span className={`${styles.badge} ${label.isLLM ? styles.llm : styles.mock}`}>
      {label.text}
    </span>
  )
}
