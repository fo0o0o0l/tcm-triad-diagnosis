import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ModelBadge } from '@/components/ModelBadge'
import { PageShell } from '@/components/PageShell'
import { SessionNo } from '@/components/SessionNo'
import {
  DEFAULT_FACE_FEATURES,
  FACE_FEATURE_LABELS,
  FACE_REGION_LABELS,
  faceApi,
  type AnalyzeResult,
  type DetectResult,
  type FaceAnalysisQueryResult,
  type FaceFeatureName,
  type FaceQualityResult,
  type ImageSource,
} from '@/services/api'
import { ApiError } from '@/utils/request'
import { resolveSessionId } from '@/utils/session'

import styles from './FaceCapturePage.module.css'

/** 采集 → AI 全链路阶段，用于驱动子步骤条与按钮禁用。 */
type Stage = 'idle' | 'uploading' | 'detecting' | 'analyzing' | 'ai' | 'done' | 'error'

const MAX_MB = 10
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
/** 与后端 face_detection 缩略图边长一致，用于把 bbox 还原到显示坐标。 */
const DETECT_THUMB_SIZE = 320

function confidenceLevel(value: number): 'high' | 'medium' | 'low' {
  if (value >= 0.85) return 'high'
  if (value >= 0.7) return 'medium'
  return 'low'
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

/** 优先请求后置摄像头；设备不支持该约束时退回默认摄像头。 */
async function requestCameraStream(): Promise<MediaStream> {
  try {
    return await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'OverconstrainedError') {
      return navigator.mediaDevices.getUserMedia({ video: true })
    }
    throw err
  }
}

/** 把 getUserMedia 的异常翻译成可操作的中文提示（浏览器安全策略 / 权限 / 设备三类）。 */
function describeCameraError(err: unknown): string {
  switch (err instanceof DOMException ? err.name : '') {
    case 'NotAllowedError':
    case 'SecurityError':
      return '摄像头权限被拒绝：请点击地址栏左侧的摄像头图标选择「允许」，并确认系统「隐私和安全性 → 摄像头」已对该浏览器开放'
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return '未检测到摄像头设备，请改用本地上传'
    case 'NotReadableError':
    case 'TrackStartError':
      return '摄像头被其他程序占用，请关闭其他正在使用摄像头的应用后重试'
    case 'OverconstrainedError':
      return '摄像头不支持所需的采集参数，请改用本地上传'
    default:
      return '无法访问摄像头，请检查权限或改用本地上传'
  }
}

interface NaturalSize {
  width: number
  height: number
}

/**
 * P3 面诊采集页（UI/UX §5.2 面诊变体）。
 * 复用 P2 采集框架：本地上传 / 摄像头拍摄，依次执行质量校验 → 面部区域检测 → 特征识别 → AI 解读，
 * 多脸/遮挡在质量校验阶段阻断并给出建议，低可信不阻断、失败可重试（PRD §6.2）。
 */
export function FaceCapturePage() {
  const [searchParams] = useSearchParams()
  const sessionId = useMemo(() => resolveSessionId(searchParams.get('session_id')), [searchParams])

  const [stage, setStage] = useState<Stage>('idle')
  const [error, setError] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [recordId, setRecordId] = useState<string | null>(null)
  const [natural, setNatural] = useState<NaturalSize | null>(null)
  const [quality, setQuality] = useState<FaceQualityResult | null>(null)
  const [detect, setDetect] = useState<DetectResult | null>(null)
  const [analyze, setAnalyze] = useState<AnalyzeResult | null>(null)
  const [analysis, setAnalysis] = useState<FaceAnalysisQueryResult | null>(null)
  const [cameraOn, setCameraOn] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const previewRef = useRef<string | null>(null)

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    setCameraOn(false)
  }, [])

  useEffect(
    () => () => {
      stopCamera()
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [stopCamera],
  )

  // <video> 仅在 cameraOn 为真时渲染，需待其挂载后再绑定媒体流；
  // 若在 startCamera 里直接取 videoRef，元素尚未渲染，ref 为空会导致看不到画面。
  useEffect(() => {
    if (!cameraOn) return
    const video = videoRef.current
    const stream = streamRef.current
    if (!video || !stream) return
    video.srcObject = stream
    void video.play().catch(() => undefined)
  }, [cameraOn])

  const showError = useCallback((err: unknown) => {
    if (err instanceof ApiError) {
      const data = err.data as { suggestions?: string[] } | null
      setSuggestions(Array.isArray(data?.suggestions) ? data.suggestions : [])
      setError(err.message || '请求失败，请重试')
    } else {
      setSuggestions([])
      setError(err instanceof Error ? err.message : '网络异常，请稍后重试')
    }
    setStage('error')
  }, [])

  const pollAnalysis = useCallback(async (): Promise<FaceAnalysisQueryResult> => {
    let delay = 1000
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await sleep(delay)
      const result = await faceApi.getAnalysis(sessionId)
      if (result.status === 'completed' || result.status === 'failed') return result
      delay = Math.min(3000, delay + 500)
    }
    throw new Error('面象分析超时，请稍后重试')
  }, [sessionId])

  // 切换模块后返回本页时组件会重新挂载，useState 中的进度会丢失；
  // 挂载时按会话从后端拉取当前记录并恢复（无记录则保持未采集态）。
  const hydratedRef = useRef<string | null>(null)
  useEffect(() => {
    if (hydratedRef.current === sessionId) return
    hydratedRef.current = sessionId
    void (async () => {
      try {
        const state = await faceApi.getRecord(sessionId)
        if (!state) return
        setRecordId(state.record_id)
        setQuality(state.quality)
        // 预览用后端原图地址重建（非 blob，无需在卸载时 revoke）
        const rawName = state.image_ref.split('/').pop() || 'raw.jpg'
        setPreviewUrl(faceApi.mediaUrl(state.record_id, rawName))
        if (state.detect) setDetect(state.detect)
        if (state.analyze) setAnalyze(state.analyze)
        if (state.analysis) {
          setAnalysis(state.analysis)
          // 后台任务可能仍在异步执行，继续轮询到终态
          if (state.analysis.status === 'pending' || state.analysis.status === 'analyzing') {
            try {
              setAnalysis(await pollAnalysis())
            } catch {
              /* 轮询失败时保留后端已返回的状态 */
            }
          }
        }
        setStage('done')
      } catch {
        // 网络异常降级为未采集态，用户可重新采集
      }
    })()
  }, [pollAnalysis, sessionId])

  const runPipeline = useCallback(
    async (file: File, source: ImageSource) => {
      setError('')
      setSuggestions([])
      setQuality(null)
      setDetect(null)
      setAnalyze(null)
      setAnalysis(null)
      setRecordId(null)
      setNatural(null)

      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
      previewRef.current = URL.createObjectURL(file)
      setPreviewUrl(previewRef.current)

      try {
        setStage('uploading')
        const uploaded = await faceApi.uploadImage(sessionId, file, source)
        setRecordId(uploaded.record_id)
        setQuality(uploaded.quality)

        setStage('detecting')
        setDetect(await faceApi.detect(sessionId, uploaded.record_id))

        setStage('analyzing')
        setAnalyze(await faceApi.analyze(sessionId, uploaded.record_id, DEFAULT_FACE_FEATURES))

        setStage('ai')
        await faceApi.startAiAnalysis(sessionId, uploaded.record_id)
        setAnalysis(await pollAnalysis())
        setStage('done')
      } catch (err) {
        showError(err)
      }
    },
    [pollAnalysis, sessionId, showError],
  )

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return
      if (!ALLOWED_TYPES.includes(file.type)) {
        setError('仅支持 jpg / jpeg / png / webp 格式')
        setStage('error')
        return
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        setError(`文件超过大小上限（${MAX_MB}MB）`)
        setStage('error')
        return
      }
      stopCamera()
      void runPipeline(file, 'upload')
    },
    [runPipeline, stopCamera],
  )

  const startCamera = useCallback(async () => {
    setError('')
    // 非安全上下文（如用局域网 IP 而非 localhost 访问）浏览器会直接隐藏 mediaDevices
    if (!window.isSecureContext || !navigator.mediaDevices) {
      setError('当前访问方式不允许调用摄像头：请改用 http://localhost:5173 或 HTTPS 访问')
      setStage('error')
      return
    }
    try {
      streamRef.current = await requestCameraStream()
      // 绑定媒体流交给上方 effect 处理（此处 <video> 尚未渲染，ref 为空）
      setCameraOn(true)
    } catch (err) {
      console.error('[face] getUserMedia failed:', err)
      setError(describeCameraError(err))
      setStage('error')
    }
  }, [])

  const capture = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    canvas.toBlob((blob) => {
      if (blob) void runPipeline(new File([blob], 'camera.jpg', { type: 'image/jpeg' }), 'camera')
    }, 'image/jpeg', 0.92)
    stopCamera()
  }, [runPipeline, stopCamera])

  const retryAnalysis = useCallback(async () => {
    if (!recordId) return
    setError('')
    setAnalysis(null)
    try {
      setStage('ai')
      await faceApi.startAiAnalysis(sessionId, recordId)
      setAnalysis(await pollAnalysis())
      setStage('done')
    } catch (err) {
      showError(err)
    }
  }, [pollAnalysis, recordId, sessionId, showError])

  const [clearing, setClearing] = useState(false)

  // 重新采集：先软删后端记录（否则刷新后页面会按会话回填旧数据），再清空本地态。
  // 清空期间置灰按钮并提示，避免请求在途时刷新导致中断、记录未删而回填。
  const reset = useCallback(async () => {
    if (clearing) return
    setError('')
    setClearing(true)
    try {
      await faceApi.removeRecord(sessionId)
    } catch (err) {
      showError(err)
      setClearing(false)
      return
    }
    stopCamera()
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = null
    setPreviewUrl(null)
    setNatural(null)
    setRecordId(null)
    setQuality(null)
    setDetect(null)
    setAnalyze(null)
    setAnalysis(null)
    setSuggestions([])
    setStage('idle')
    setClearing(false)
  }, [clearing, sessionId, showError, stopCamera])

  const busy =
    stage === 'uploading' || stage === 'detecting' || stage === 'analyzing' || stage === 'ai'
  const steps = [
    { key: 'capture', label: '图像采集', done: Boolean(previewUrl) },
    { key: 'quality', label: '质量校验', done: Boolean(quality?.passed) },
    { key: 'detect', label: '面部检测', done: Boolean(detect) },
    { key: 'features', label: '特征识别', done: Boolean(analyze) },
    { key: 'ai', label: 'AI 解读', done: analysis?.status === 'completed' },
  ]
  const activeIndex = steps.findIndex((step) => !step.done)

  return (
    <PageShell
      title="面诊采集与分析"
      description="望诊 · 面：本地/摄像头采集 → 质量校验 → 面部检测 → 特征识别 → AI 解读"
    >
      <div className={styles.sessionBar}>
        <span className={styles.sessionLabel}>当前会话</span>
        <SessionNo sessionId={sessionId} className={styles.sessionId} />
      </div>

      <ol className={styles.steps}>
        {steps.map((step, index) => {
          const status = step.done ? 'done' : index === activeIndex && busy ? 'active' : ''
          return (
            <li key={step.key} className={`${styles.step} ${status ? styles[status] : ''}`}>
              <span className={styles.stepDot}>{step.done ? '✓' : index + 1}</span>
              <span className={styles.stepLabel}>{step.label}</span>
            </li>
          )
        })}
      </ol>

      <div className={styles.grid}>
        {/* 左栏：采集区 */}
        <section className={styles.panel}>
          <h2 className={styles.panelTitle}>图像采集</h2>

          <div className={styles.actions}>
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
            >
              本地上传
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => (cameraOn ? stopCamera() : void startCamera())}
            >
              {cameraOn ? '关闭摄像头' : '摄像头拍摄'}
            </button>
            {cameraOn ? (
              <button type="button" className="btn btn--primary" onClick={capture}>
                拍摄
              </button>
            ) : null}
            {previewUrl ? (
              <button
                type="button"
                className="btn btn--ghost"
                disabled={busy || clearing}
                onClick={() => void reset()}
              >
                {clearing ? '清空中…' : '重新采集'}
              </button>
            ) : null}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept={ALLOWED_TYPES.join(',')}
            hidden
            onChange={(event) => {
              handleFile(event.target.files?.[0])
              event.target.value = ''
            }}
          />

          <div className={styles.stage}>
            {cameraOn ? <video ref={videoRef} className={styles.video} playsInline muted /> : null}
            {previewUrl && !cameraOn ? (
              <figure className={styles.figure}>
                <img
                  className={styles.preview}
                  src={previewUrl}
                  alt="面象预览"
                  onLoad={(event) =>
                    setNatural({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    })
                  }
                />
                {detect && natural ? (
                  <RegionOverlay regions={detect.regions} natural={natural} />
                ) : null}
              </figure>
            ) : null}
            {!cameraOn && !previewUrl ? (
              <div className={styles.stageEmpty}>
                <p>请上传或拍摄面象图像</p>
                <p className={styles.stageTip}>
                  引导：正脸居中、五官无遮挡、避免口罩与帽子；在均匀自然光下拍摄
                </p>
              </div>
            ) : null}
          </div>

          <p className={styles.privacy}>图像仅用于本次辨证分析，默认私有存储，需授权方可访问。</p>
        </section>

        {/* 右栏：结果区 */}
        <section className={styles.panel}>
          <h2 className={styles.panelTitle}>分析结果</h2>

          {error ? (
            <div className={styles.error}>
              <div>{error}</div>
              {suggestions.length > 0 ? (
                <ul className={styles.suggestions}>
                  {suggestions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {busy ? <div className={styles.status}>正在处理：{stageText(stage)}…</div> : null}

          {/* 质量提示区 */}
          {quality ? (
            <div className={styles.block}>
              <div className={styles.blockTitle}>质量校验</div>
              <div className={styles.metrics}>
                <Metric label="清晰度" value={quality.clearness} />
                <Metric label="光照" value={quality.lighting} />
                <Metric label="构图" value={quality.composition} />
                <div className={styles.metric}>
                  <span className={styles.metricLabel}>面部检测</span>
                  <span className={styles.muted}>{quality.face_detected ? '已检出' : '未检出'}</span>
                </div>
                <div className={styles.metric}>
                  <span className={styles.metricLabel}>单脸</span>
                  <span className={styles.muted}>{quality.single_face ? '是' : '否'}</span>
                </div>
              </div>
            </div>
          ) : null}

          {/* 区域检测区 */}
          {detect ? (
            <div className={styles.block}>
              <div className={styles.blockTitle}>面部区域检测</div>
              <div className={styles.inline}>
                <span>人脸数</span>
                <strong>{detect.face_count}</strong>
                <span>检测置信度</span>
                <span className={`${styles.badge} ${styles[confidenceLevel(detect.detect_confidence)]}`}>
                  {Math.round(detect.detect_confidence * 100)}%
                </span>
                <span className={styles.muted}>
                  {detect.status === 'extracting' ? '低可信（不阻断）' : '检测成功'}
                </span>
              </div>
              <div className={styles.tagRow}>
                {detect.regions.map((region) => (
                  <span className={styles.tag} key={region.name}>
                    {FACE_REGION_LABELS[region.name] ?? region.name}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {/* 特征结果区 */}
          {analyze ? (
            <div className={styles.block}>
              <div className={styles.blockTitle}>
                面象特征
                <span className={`${styles.badge} ${styles[confidenceLevel(analyze.overall_confidence)]}`}>
                  整体 {Math.round(analyze.overall_confidence * 100)}%
                </span>
              </div>
              <div className={styles.featureGrid}>
                {analyze.features.map((feature) => (
                  <div className={styles.featureCard} key={feature.name}>
                    <div className={styles.featureName}>
                      {FACE_FEATURE_LABELS[feature.name as FaceFeatureName] ?? feature.name}
                    </div>
                    <div className={styles.featureLabel}>{feature.label}</div>
                    {feature.area && feature.area.length > 0 ? (
                      <div className={styles.featureArea}>
                        分布：{feature.area.map((name) => FACE_REGION_LABELS[name] ?? name).join('、')}
                      </div>
                    ) : null}
                    <div
                      className={`${styles.badge} ${styles[confidenceLevel(feature.confidence)]}`}
                    >
                      {Math.round(feature.confidence * 100)}%
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* AI 解读区 */}
          {analysis ? (
            <div className={styles.block}>
              <div className={styles.blockTitle}>
                AI 面象解读
                <ModelBadge modelVersion={analysis.model_version} />
              </div>

              {analysis.status === 'completed' && analysis.result ? (
                <>
                  <p className={styles.summary}>{analysis.result.face_summary}</p>
                  {analysis.result.main_syndrome ? (
                    <div className={styles.inline}>
                      <span>主要证候倾向</span>
                      <strong>{analysis.result.main_syndrome.name}</strong>
                      <span
                        className={`${styles.badge} ${styles[confidenceLevel(analysis.result.main_syndrome.confidence)]}`}
                      >
                        {Math.round(analysis.result.main_syndrome.confidence * 100)}%
                      </span>
                    </div>
                  ) : null}

                  {analysis.result.secondary_syndromes.length > 0 ? (
                    <div className={styles.tagRow}>
                      {analysis.result.secondary_syndromes.map((item) => (
                        <span className={styles.tag} key={item.name}>
                          {item.name} {Math.round(item.confidence * 100)}%
                        </span>
                      ))}
                    </div>
                  ) : null}

                  {analysis.result.treatment_principles.length > 0 ? (
                    <div className={styles.tagRow}>
                      {analysis.result.treatment_principles.map((item) => (
                        <span className={styles.tagPrimary} key={item}>
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  <ul className={styles.recommendations}>
                    {analysis.result.recommendations.map((item) => (
                      <li key={`${item.category}-${item.text}`}>
                        <strong>{item.category}：</strong>
                        {item.text}
                      </li>
                    ))}
                  </ul>
                </>
              ) : analysis.status === 'failed' ? (
                <div className={styles.error}>
                  <div>面象分析暂不可用，可重试（特征识别结果已保留）。</div>
                  {analysis.retryable ? (
                    <button type="button" className="btn btn--ghost" onClick={() => void retryAnalysis()}>
                      重新分析
                    </button>
                  ) : null}
                </div>
              ) : (
                <div className={styles.status}>AI 分析中…</div>
              )}
            </div>
          ) : null}

          {stage === 'idle' ? (
            <div className={styles.empty}>尚无分析结果，请先上传或拍摄面象图像。</div>
          ) : null}
        </section>
      </div>
    </PageShell>
  )
}

/** 面部区域检测框叠加：把检测缩略图坐标（≤320）还原为相对显示图像的百分比。 */
function RegionOverlay({
  regions,
  natural,
}: {
  regions: { name: string; bbox: number[] }[]
  natural: NaturalSize
}) {
  const scale = DETECT_THUMB_SIZE / Math.max(natural.width, natural.height)
  const thumbWidth = Math.max(1, natural.width * scale)
  const thumbHeight = Math.max(1, natural.height * scale)
  return (
    <div className={styles.overlay}>
      {regions.map((region) => {
        const [x0, y0, x1, y1] = region.bbox
        return (
          <div
            key={region.name}
            className={styles.regionBox}
            style={{
              left: `${(x0 / thumbWidth) * 100}%`,
              top: `${(y0 / thumbHeight) * 100}%`,
              width: `${((x1 - x0) / thumbWidth) * 100}%`,
              height: `${((y1 - y0) / thumbHeight) * 100}%`,
            }}
          >
            <span className={styles.regionName}>
              {FACE_REGION_LABELS[region.name] ?? region.name}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={`${styles.badge} ${styles[confidenceLevel(value)]}`}>
        {Math.round(value * 100)}%
      </span>
    </div>
  )
}

function stageText(stage: Stage): string {
  return (
    {
      uploading: '上传与质量校验',
      detecting: '面部区域检测',
      analyzing: '面象特征识别',
      ai: 'AI 面象解读',
    }[stage as string] ?? '处理中'
  )
}