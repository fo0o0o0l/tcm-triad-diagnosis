/**
 * 把后端 `model_version` 解析为可读的模型来源标识，便于直观判断是否降级到本地规则。
 *
 * - 大模型：`tongue_llm_v1_qwen-plus` → 「通义千问 qwen-plus」（isLLM = true）
 * - 降级：  `tongue_mock_v1`          → 「本地规则（已降级）」（isLLM = false）
 */

export interface ModelLabel {
  /** 是否真的调用了大模型（false 表示已降级到本地规则） */
  isLLM: boolean
  /** 界面展示文案 */
  text: string
}

/** 匹配「<模块>_llm_v<N>_<模型名>」，如 tongue_llm_v1_qwen-plus */
const LLM_PATTERN = /^[a-z]+_llm_v\d+_(.+)$/

export function describeModel(modelVersion?: string | null): ModelLabel | null {
  const raw = (modelVersion ?? '').trim()
  if (!raw) return null

  if (raw.includes('mock')) {
    return { isLLM: false, text: '本地规则（已降级）' }
  }

  const matched = LLM_PATTERN.exec(raw)
  if (matched) {
    const model = matched[1]
    // 千问系列标注厂商，其它模型直接展示模型名，避免贴错标签
    return { isLLM: true, text: model.startsWith('qwen') ? `通义千问 ${model}` : `大模型 ${model}` }
  }
  if (raw.includes('_llm_v')) {
    return { isLLM: true, text: '大模型' }
  }

  // 未知格式：原样展示，按未调用大模型处理
  return { isLLM: false, text: raw }
}
