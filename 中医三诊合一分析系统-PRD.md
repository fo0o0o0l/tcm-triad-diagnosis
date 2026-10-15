# 中医三诊合一分析系统 产品需求规格说明书（PRD）

| 项目 | 内容 |
|---|---|
| 文档名称 | 中医三诊合一分析系统 产品需求规格说明书 |
| 文档版本 | v1.5 |
| 文档状态 | 最终版 |
| 产品定位 | 面向中医诊疗场景的"舌诊 + 面诊 + 问诊"三诊数据采集、AI 分析与合参报告的 Web 应用 |
| 交付形态 | Web 应用（PC 浏览器优先，移动端浏览器兼容采集能力） |
| 目标读者 | 产品、UI/UX、前端、后端、算法、测试 |

**修订记录**

| 版本 | 日期 | 修订内容 | 修订人 |
|---|---|---|---|
| v1.0 | 2026-10-12 | 首版，覆盖五大核心模块 | 产品经理 |
| v1.1 | 2026-10-13 | 明确报告历史查询（R4）：多词关键词 AND、匿名/已归档快捷筛选、分页与响应字段（§6.5.4 / §9.6） | 产品经理 |
| v1.2 | 2026-10-13 | 明确报告删除（R6）为软删：检索/详情/PDF 不再返回，前端二次确认 + 后端审计日志（§9.6） | 产品经理 |
| v1.3 | 2026-10-14 | 三诊合参调整为**用户手动确认后触发**（不再自动开始），且**三诊全部完成方可合参**（缺任一一诊即阻断并提示补齐具体诊位）；原"缺诊降级"能力标注为后续迭代（§6.4、§2.2） | 产品经理 |
| v1.4 | 2026-10-14 | 会话编号展示口径：由业务 id 改为「用户姓名_月日」（当天第 2 个及以后追加 `#序号`；未填姓名 / 匿名分别显示「待补姓名」「匿名用户」），报告头与历史列表同步（§6.5） | 产品经理 |
| v1.5 | 2026-10-15 | 与实现对齐：界面文案统一为「用户」；移除未实现能力（会话 CRUD 接口、分享链接与令牌、多用户档案）相关描述；接口清单补齐 `fusion/readiness` 与 `reports/compare` | 产品经理 |

**术语表**

| 术语 | 定义 |
|---|---|
| 三诊 | 本系统中指舌诊、面诊、问诊三类诊法的数据与结论 |
| 四诊合参 | 中医传统"望闻问切"，本系统实现的"三诊合参"为其工程化子集：望（舌/面）+ 问 |
| 舌象 | 舌体的颜色、形态，以及舌面苔的颜色、质地等视觉特征集合 |
| 面象 | 面部整体色泽、光泽度，以及局部皮肤状态（痘痘、斑点）等视觉特征集合 |
| 特征项 | 可从图像或问卷中结构化提取并可被规则/AI 判读的最小单位（如"舌色"） |
| 诊断置信度 | 系统对单诊/合参结论的把握程度，取值 0–100，用于提示参考强度 |
| 会话（Session） | 一次完整的"用户—采集—分析—报告"过程，是各模块数据的聚合载体 |
| 采集质量分 | 图像在清晰度、光照、构图等维度的合规度评分，低于阈值时要求重采 |

---

## 1. 背景与目标

### 1.1 背景与问题

中医诊疗中的舌诊、面诊依赖医师目视经验判断，问诊依赖口头问答，三者结论通常分散记录、缺乏统一载体，导致：

- **标准不统一**：同一舌象不同医师判读差异大，缺少可复现的结构化特征描述。
- **数据不沉淀**：图像、问答、结论分散，无法形成可回溯的诊疗记录，复诊对比困难。
- **合参效率低**：医师需在多个信息源间人工交叉比对，才能形成综合判断。
- **交付不规范**：诊断报告格式各异，无法标准化导出、打印与归档。

### 1.2 产品决策

构建一个统一入口的 Web 应用，将"舌象采集 → 面象采集 → 智能问诊 → 三诊合参 → 报告输出"串成一条完整会话流：

- 采集环节通过**质量校验**保证输入可用；
- 分析环节通过**结构化特征项 + 规则/AI 判读**输出可解释结论；
- 合参环节通过**多诊数据融合**生成综合诊断与调理建议；
- 报告环节支持**在线预览、PDF 导出、A4 打印、历史查询**。

### 1.3 目标（可观察结果）

- 用户可在一次会话内完成舌、面、问三类数据采集并触发合参分析。
- 每次分析结果以结构化特征项 + 置信度形式呈现，并可追溯到原始采集图像。
- 用户可导出一份包含三诊依据、综合结论、调理建议的 PDF 报告，并可 A4 打印不失真。
- 用户可在历史记录中按用户、时间、结论关键词检索并重新打开报告。

> 说明：本文不设定转化率、准确率等量化指标，相关指标待算法侧测量后另行补充 `[TBD]`。

---

## 2. 产品范围

### 2.1 目标用户

| 角色 | 描述 | 核心诉求 |
|---|---|---|
| 医师/中医师（主用户） | 使用系统为用户做辅助诊断 | 快速采集、可信判读、可交付报告 |
| 用户 | 数据主体，被采集舌象/面象/问诊信息 | 隐私受控、过程被解释 |
| 系统管理员 | 维护规则库、字典、账号 | 配置可管、操作可审计 |

> 合规提示：本系统输出为**辅助参考**，不构成最终医疗诊断，报告须显式声明并由医师确认签署。`[Assumption, TBD]`（落地前需确认适用的医疗器械/互联网诊疗法规与备案要求）

### 2.2 范围边界

**P0（本次交付，构成完整用户旅程）**

1. 舌诊分析模块：舌象采集、舌头区域自动提取、舌象智能分析（舌色/苔色/苔质/舌形）
2. 面诊分析模块：面象采集、面部区域自动检测、面象智能分析（面色/光泽/痘痘/斑点）
3. 问诊模块：智能问诊表单
4. 三诊合参模块：数据融合、AI 综合分析、综合诊断报告生成
5. 报告管理模块：报告预览、PDF 导出、A4 打印适配、历史记录查询

**P1（后续迭代，本期不实现但架构需预留）**

- 采集设备（专用采集仪）接入
- 报告批量导出、机构签名盖章
- 权限分级（机构 → 科室 → 医师）

**明确排除**

- 预约挂号、支付、药方开具与药品物流
- 舌象/面象视频流实时分析
- 跨机构数据共享

### 2.3 最小完整旅程

```
进入会话 → 采集舌象（含质量校验） → 采集面象（含质量校验）
→ 填写问诊表单 → 三诊齐全后由用户确认触发合参 → 查看综合报告 → 导出/打印/归档
```

**完成证据**：用户看到一份包含三诊依据与综合结论的报告，并成功导出 PDF 或完成归档。

**恢复路径**：任一诊数据缺失或图像质量不达标时，会话保留为"草稿"，允许仅对失败环节重采，不丢失已完成数据。

---

## 3. 用户角色与权限

| 能力 | 医师 | 用户 | 管理员 |
|---|---|---|---|
| 创建会话、采集数据 | ✅ | ❌ | ❌ |
| 触发分析/合参 | ✅ | ❌ | ❌ |
| 查看原始采集图像 | ✅ | ✅（仅本人） | ❌ |
| 查看/导出报告 | ✅ | ✅（仅本人） | ❌ |
| 编辑/删除报告 | ✅ | ❌ | ✅（审计留痕） |
| 维护特征项字典、规则阈值 | ❌ | ❌ | ✅ |
| 查看操作审计日志 | ❌ | ❌ | ✅ |

---

## 4. 技术架构

### 4.1 总体架构

```
┌───────────────────────────────────────────────────────────────────┐
│                          接入层                                    │
│   PC 浏览器（Chrome/Edge 最新版）  |  移动端浏览器（H5 采集）        │
└───────────────────────────────┬───────────────────────────────────┘
                                │ HTTPS / JSON
┌───────────────────────────────▼───────────────────────────────────┐
│                        前端应用层（SPA）                           │
│  舌诊视图 | 面诊视图 | 问诊表单 | 合参视图 | 报告视图 | 历史记录     │
│  图像采集组件(WebRTC/File) | 区域标注画布 | 质量提示 | PDF/打印      │
└───────────────────────────────┬───────────────────────────────────┘
                                │ RESTful API（Bearer Token）
┌───────────────────────────────▼───────────────────────────────────┐
│                        应用服务层（API Gateway）                    │
│  会话服务 | 舌诊服务 | 面诊服务 | 问诊服务 | 合参服务 | 报告服务     │
│  鉴权与权限 | 限流 | 审计日志 | 文件签名与访问控制                    │
└───────┬────────────────────┬────────────────────┬─────────────────┘
        │                    │                    │
┌───────▼───────┐   ┌────────▼────────┐   ┌───────▼─────────────────┐
│  算法推理层    │   │   数据存储层     │   │   规则与知识层           │
│ 舌体分割模型   │   │ 关系型数据库     │   │ 特征项字典               │
│ 面部检测模型   │   │ 对象存储(图像)   │   │ 判读规则库/阈值          │
│ 特征分类模型   │   │ 缓存(会话态)     │   │ 建议/话术模板            │
│ 大模型解读服务 │   │ 任务队列         │   │ 报告模板                 │
└───────────────┘   └─────────────────┘   └─────────────────────────┘
```

### 4.2 分层职责

| 层 | 职责 | 关键技术约束 |
|---|---|---|
| 前端应用层 | 采集、校验提示、结果可视化、报告渲染与打印 | 采集需支持本地文件上传与摄像头拍摄两种来源；PDF 导出与 A4 打印须保持版式一致 |
| 应用服务层 | 编排会话流程、鉴权、调用算法、聚合结果、生成报告 | 所有写操作幂等；算法调用超时需可降级并返回明确状态 |
| 算法推理层 | 舌体分割、面部检测、特征分类、合参推理 | 以独立服务暴露，输入输出为标准化结构；模型可热更新版本号 |
| 数据存储层 | 结构化数据、图像对象、会话临时态、异步任务 | 图像私有读，需签名 URL 访问；敏感信息加密存储 |
| 规则与知识层 | 特征项定义、判读阈值、建议模板、报告模板 | 阈值可配置且带版本，报告需记录所用规则版本 |

### 4.3 关键技术选型建议

| 能力 | 建议方案 | 说明 |
|---|---|---|
| 舌体区域提取 | 语义分割模型（输入原图 → 输出舌体掩膜） | 输出掩膜 + 置信度，低于阈值触发重采提示 |
| 面部区域检测 | 人脸检测 + 关键点定位 | 用于定位额头/面颊/鼻部等采样区域 |
| 舌/面特征分类 | 多标签分类模型 | 每个特征项输出标签 + 置信度 |
| 三诊合参 | 规则引擎 + 大模型生成 | 规则负责一致性校验与加权，大模型负责可读结论与建议生成 |
| 图像存储 | 对象存储 + 私有桶 | 通过后端签发的临时 URL 访问 |
| 异步任务 | 消息队列 + 任务状态表 | 分析任务异步执行，前端轮询/推送任务状态 |

> 具体模型、版本与部署形态由算法团队确定 `[TBD]`；接口契约按 §10 固定。

---

## 5. 核心业务流程

### 5.1 主流程（时序）

```
医师            前端              应用服务            算法层
 │  创建会话      │                  │                  │
 │──────────────▶│  前端生成 session_id                │
 │               │                  │                  │
 │  上传/拍摄舌象 │                  │                  │
 │──────────────▶│─POST /tongue/...▶│─调用舌体分割─────▶│
 │               │◀─质量分+掩膜──────│◀──掩膜+置信度─────│
 │   (质量不足 → 重采提示)            │                  │
 │──────────────▶│─POST /tongue/analyze▶│─特征分类─────▶│
 │               │◀─舌象特征结果─────│◀──特征+置信度─────│
 │  上传/拍摄面象 │────(同上 face 流程)───────────────────│
 │  填写问诊表单  │─POST /inquiry/submit▶│ 校验+落库      │
 │  触发合参      │─POST /fusion/analyze▶│─规则+大模型────▶│
 │               │◀─综合结论───────│◀──合参结果────────│
 │  查看/导出报告 │─GET /reports/{id}▶│ 渲染PDF         │
```

### 5.2 会话状态机

| 状态 | 说明 | 允许迁移至 |
|---|---|---|
| `draft` | 已创建，数据未齐 | `collecting` / `abandoned` |
| `collecting` | 正在采集（舌/面/问） | `ready` / `draft` / `abandoned` |
| `ready` | 三诊数据齐备且通过校验 | `analyzing` |
| `analyzing` | 合参分析进行中 | `completed` / `failed` |
| `completed` | 报告已生成 | （可重新分析，回到 `analyzing`） |
| `failed` | 分析失败 | `analyzing`（重试） / `abandoned` |
| `abandoned` | 用户放弃 | 终态 |

**规则**：仅 `ready` 状态可触发合参；`analyzing` 期间禁止重复触发（幂等保护）。

---

## 6. 功能需求

### 6.1 舌诊分析模块（FR-TONGUE）

**目的**：采集舌象图像、自动提取舌头区域、识别结构化舌象特征，并调用 AI 分析接口产出舌象解读，为合参提供"望诊—舌"依据。

**布局（舌诊视图）**

| 区域 | 职责 |
|---|---|
| 采集区 | 提供"本地文件上传""摄像头拍摄"两个入口，展示当前图像 |
| 质量提示区 | 展示清晰度、光照、构图等质量分与具体改进建议（§7.1） |
| 区域提取区 | 叠加舌体掩膜，展示提取置信度 |
| 特征结果区 | 分卡片展示舌色、苔色、苔质、舌形四类特征及置信度 |
| AI 解读区 | 展示舌象 AI 分析结果（§6.1.4） |

**触发**：医师在会话内进入舌诊模块，且会话状态为 `draft` 或 `collecting`。

**处理规则**

1. **采集**：支持本地上传与摄像头拍摄，来源与规格见 §7.1。
2. **质量校验**：采集后自动执行，规则见 §7.1；未通过则阻断并返回改进建议。
3. **舌头区域自动提取**：见 §6.1.2。
4. **舌象特征识别**：见 §6.1.3。
5. **舌象 AI 分析**：提交后调用 AI 接口（§6.1.4）。
6. **重新采集**：覆盖当前 `tongue_record`，历史版本留存于审计日志。

#### 6.1.1 采集方式

| 来源 | 交互 | 说明 |
|---|---|---|
| 本地上传 | 拖拽或点击选择文件 | jpg/jpeg/png/webp，≤10MB，分辨率 ≥640×480 |
| 摄像头拍摄 | 打开摄像头 + 引导框 | 引导框提示舌体居中、伸舌自然、避免舌尖过伸；提供光照提示 |

**字段（采集记录）**

| 字段 | 类型 | 说明 |
|---|---|---|
| source | 枚举 | `upload` / `camera` |
| file | 文件 | 原始图像 |
| captured_at | 时间 | 采集时间 |

#### 6.1.2 舌头区域自动提取

**目的**：从原图中分离舌体区域，作为特征识别的输入，排除背景干扰。

**处理规则**

1. 对通过质量校验的图像执行舌体语义分割，输出掩膜（mask）与提取置信度。
2. 前端在图像上叠加掩膜显示提取范围。
3. 判定：

| 情形 | 判定条件 | 处理 |
|---|---|---|
| 提取成功 | 置信度 ≥ 阈值（默认 0.7 `[Assumption, TBD]`） | 进入特征识别 |
| 低可信 | 置信度 < 阈值但掩膜存在 | **不阻断**，标记低可信，报告提示，允许继续 |
| 提取失败 | 未检出舌体区域 | 阻断，提示"未能识别舌体，请重拍" |

**字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| mask_ref | 字符串 | 掩膜图像引用 |
| extract_confidence | 数字 | 提取置信度 0–1 |

#### 6.1.3 舌象特征识别

**目的**：对舌体区域执行多标签分类，输出四类舌象特征。

**处理规则**

1. 对提取后的舌体区域执行特征分类，每项输出 `label` + `confidence`。
2. 每类特征可同时存在多个标签（如舌形同时"胖大 + 齿痕"）。
3. 计算舌诊整体置信度 = 各特征置信度的加权均值（权重见 §7.2）。

**特征清单**

| 特征项 | 字段名 | 类型 | 取值（枚举，最终以字典为准） | 说明 |
|---|---|---|---|---|
| 舌色 | tongue_color | 单选 | 淡白、淡红、红、绛红、青紫 | 舌体主色 |
| 苔色 | coating_color | 单选 | 白、黄、灰黑 | 舌苔颜色 |
| 苔质 | coating_texture | 多选 | 薄、厚、腻、腐、剥落/少苔 | 舌苔质地与厚薄 |
| 舌形 | tongue_shape | 多选 | 正常、胖大、瘦薄、齿痕、裂纹、点刺 | 舌体形态 |

**字段（分析结果）**

| 字段 | 类型 | 说明 |
|---|---|---|
| features | 数组 | `[{name, label, confidence}]` |
| overall_confidence | 数字 | 舌诊整体置信度 |

#### 6.1.4 舌象 AI 智能分析

**目的**：在特征识别结果基础上，调用 AI 分析接口输出可读的舌象解读与证候倾向。

**触发**：特征识别完成后自动触发；用户可在 AI 解读区点击"重新分析"。

**调用方式**：前端调用 `POST /api/v1/sessions/{session_id}/tongue/ai-analysis`（见 §9.2.4）；分析异步执行，前端轮询 `task_id` 或订阅推送。

**输入**：`record_id` + `features`（特征识别结果）+ 提取置信度。

**输出字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| tongue_summary | 文本 | 舌象总结：对舌色、苔色、苔质、舌形的归纳描述 |
| main_syndrome | 对象 | 主要证候倾向：`{ name, confidence }` |
| secondary_syndromes | 数组 | 次要证候倾向：`[{ name, confidence }]` |
| treatment_principles | 字符串数组 | 治疗原则 |
| recommendations | 对象数组 | 调理建议：`[{ category, text }]` |

**结果与状态变化**：写入 `tongue_analysis`，与 `tongue_record` 关联；结果在 AI 解读区展示，并作为三诊合参输入之一（§6.4）。

**异常与边界**

| 场景 | 处理 |
|---|---|
| AI 服务超时/不可用 | 特征识别结果仍保留；分析置 `failed`，展示"舌象分析暂不可用，可重试"，不阻断采集流程 |
| 输出字段缺失 | 缺失字段以"暂无"占位 |
| 重新分析 | 覆盖当前分析结果并保留旧版本于审计日志 |

#### 6.1.5 异常与边界

| 场景 | 处理 |
|---|---|
| 文件格式不支持 | 前端即时拒绝并提示支持的格式 |
| 文件超限 | 拒绝并提示大小上限 |
| 摄像头无权限/被占用 | 提示切换本地上传，给出授权指引 |
| 图像无舌体/识别失败 | 阻断分析，提示重采 |
| 分析服务超时 | 任务置 `failed`，提供"重试"入口，保留原始图像 |

**状态**：`未采集 → 采集中 → 待分析 → 特征识别中 → 特征完成 → AI 分析中 → AI 完成 / 失败`

---

### 6.2 面诊分析模块（FR-FACE）

**目的**：采集面象图像、自动检测面部区域、识别结构化面象特征，并调用 AI 分析接口产出面象解读，为合参提供"望诊—面"依据。

**布局（面诊视图）**：结构与舌诊视图一致，将"舌体区域"替换为"面部区域"，特征结果区展示面色、光泽、痘痘、斑点四类特征。

**触发**：会话内进入面诊模块，会话状态为 `draft` 或 `collecting`。

**处理规则**

1. **采集**：支持本地上传与摄像头拍摄，来源与规格见 §7.1。
2. **质量校验**：规则见 §7.1；面象额外校验正脸、五官无遮挡、画面中仅一张清晰人脸。
3. **面部区域自动检测**：见 §6.2.2。
4. **面象特征识别**：见 §6.2.3。
5. **面象 AI 分析**：提交后调用 AI 接口（§6.2.4）。
6. **重新采集**：覆盖当前 `face_record`，历史版本留存于审计日志。

#### 6.2.1 采集方式

| 来源 | 交互 | 说明 |
|---|---|---|
| 本地上传 | 拖拽或点击选择文件 | jpg/jpeg/png/webp，≤10MB，分辨率 ≥640×480 |
| 摄像头拍摄 | 打开摄像头 + 正脸引导框 | 引导面部居中、光线均匀、素颜无遮挡、避免逆光 |

**字段（采集记录）**：`source`、`file`、`captured_at`（同 §6.1.1）。

#### 6.2.2 面部区域自动检测

**目的**：检测人脸并定位采样区域，为分区特征识别提供依据。

**处理规则**

1. 检测人脸并定位关键点，划分采样区域：额头、左颊、右颊、鼻部、下颌。
2. 判定：

| 情形 | 判定条件 | 处理 |
|---|---|---|
| 检测成功 | 检出 1 张清晰正脸且关键点完整 | 进入特征识别 |
| 多脸/侧脸/遮挡 | 人脸数 ≠ 1，或角度过大、五官被遮挡 | 阻断，提示"请确保画面中仅一张清晰正脸、五官无遮挡" |
| 检测失败 | 未检出人脸 | 阻断，提示重拍 |

**字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| face_count | 数字 | 检出人脸数 |
| regions | 数组 | `[{name, bbox}]`，bbox 为区域坐标 |
| detect_confidence | 数字 | 检测置信度 0–1 |

#### 6.2.3 面象特征识别

**目的**：对面部各采样区域执行特征分类，输出四类面象特征。

**处理规则**

1. 对检测到的面部区域执行特征分类，每项输出 `label` + `confidence`。
2. 痘痘、斑点额外输出分布区域（`area`，取自 `regions`）。
3. 计算面诊整体置信度 = 各特征置信度的加权均值（权重见 §7.2）。

**特征清单**

| 特征项 | 字段名 | 类型 | 取值（枚举，最终以字典为准） | 说明 |
|---|---|---|---|---|
| 面色 | face_color | 单选 | 红润、苍白、萎黄、潮红、晦暗、青紫 | 面部整体色泽 |
| 光泽 | luster | 单选 | 有光泽、少光泽、油光 | 皮肤光泽与油润度 |
| 痘痘 | acne | 单选+区域 | 无、少量、中等、较多（含分布区域） | 痤疮/丘疹情况 |
| 斑点 | spots | 单选+区域 | 无、少量、中等、较多（含分布区域） | 色素沉着/斑点情况 |

**字段（分析结果）**

| 字段 | 类型 | 说明 |
|---|---|---|
| features | 数组 | `[{name, label, confidence, area?}]` |
| overall_confidence | 数字 | 面诊整体置信度 |

#### 6.2.4 面象 AI 智能分析

**目的**：在特征识别结果基础上，调用 AI 分析接口输出可读的面象解读与证候倾向。

**触发**：特征识别完成后自动触发；用户可在 AI 解读区点击"重新分析"。

**调用方式**：前端调用 `POST /api/v1/sessions/{session_id}/face/ai-analysis`（见 §9.3.4）；分析异步执行，前端轮询 `task_id` 或订阅推送。

**输入**：`record_id` + `features`（含分布区域）+ 检测置信度。

**输出字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| face_summary | 文本 | 面象总结：对面色、光泽、痘痘、斑点的归纳描述 |
| main_syndrome | 对象 | 主要证候倾向：`{ name, confidence }` |
| secondary_syndromes | 数组 | 次要证候倾向：`[{ name, confidence }]` |
| treatment_principles | 字符串数组 | 治疗原则 |
| recommendations | 对象数组 | 调理建议：`[{ category, text }]` |

**结果与状态变化**：写入 `face_analysis`，与 `face_record` 关联；结果在 AI 解读区展示，并作为三诊合参输入之一（§6.4）。

**异常与边界**

| 场景 | 处理 |
|---|---|
| AI 服务超时/不可用 | 特征识别结果仍保留；分析置 `failed`，展示"面象分析暂不可用，可重试" |
| 输出字段缺失 | 缺失字段以"暂无"占位 |
| 重新分析 | 覆盖当前分析结果并保留旧版本于审计日志 |

#### 6.2.5 异常与边界

| 场景 | 处理 |
|---|---|
| 多脸/侧脸/遮挡 | 阻断，提示重拍 |
| 图像无面部/检测失败 | 阻断分析，提示重采 |
| 其余场景 | 同 §6.1.5 |

**状态**：`未采集 → 采集中 → 待分析 → 检测中 → 特征识别中 → 特征完成 → AI 分析中 → AI 完成 / 失败`

---

### 6.3 问诊模块（FR-INQUIRY）

**目的**：通过结构化问卷采集用户基础信息、症状与体质信息，并在提交后调用 AI 分析接口产出证候判读，为合参提供"问诊"依据。

**布局（问诊表单视图）**

| 区域 | 职责 |
|---|---|
| 分组导航（左侧） | 按分组锚点跳转；显示各分组完成状态（未开始/进行中/已完成） |
| 题目区（中间） | 按分组顺序渲染题目，支持单选/多选/填空/量表/开关（匿名） |
| 进度提示（顶部） | 显示必填项完成度（如 `必填 5/8`）与整体进度条 |
| 操作区（底部固定） | 保存草稿、提交并分析、重置表单 |
| 结果区（提交后） | 展示 AI 问诊分析结果（§6.3.5） |

**表单结构（分组与优先级）**

表单采用**分组 → 题目**两级结构，每个分组由 `group_id`、`title`、`priority`（P0/P1/P2）与 `questions[]` 组成。P0 分组与 P0 题目为必填并阻断提交；P1/P2 为可选，缺失仅降低分析置信度、不阻断。

| # | 分组 ID | 分组名称 | 优先级 | 关键内容 |
|---|---|---|---|---|
| 1 | basic | 基础信息收集 | P0 | 性别、年龄、身高、体重（必填+校验）；姓名（可选，支持匿名） |
| 2 | chief_symptom | 主诉 | P0 | 主要不适描述 |
| 3 | cold_heat | 寒热症状收集 | P0 | 怕冷畏寒、怕热喜凉、寒热交替等 |
| 4 | sweating | 汗出情况收集 | P1 | 自汗、盗汗、无汗、汗出过多等 |
| 5 | sleep | 睡眠情况收集 | P1 | 入睡困难、易醒、多梦、早醒等 |
| 6 | diet_taste | 饮食口味收集 | P1 | 食欲、口味、口渴情况 |
| 7 | excretion | 二便情况收集 | P1 | 大便、小便情况 |
| 8 | chest_abdomen | 胸腹不适收集 | P1 | 胸闷、心悸、腹胀、腹痛等 |
| 9 | other | 其他症状补充 | P2 | 文本输入框，支持详细描述 |

**触发**：会话内进入问诊模块（会话状态为 `draft` 或 `collecting`）。

**处理规则**

1. **题目类型**：单选（single）、多选（multi）、文本（text，含多行）、数字（number）、量表（scale，0–10）、开关（switch，用于匿名）。题型由问诊模板配置驱动。
2. **必填与优先级**：
   - P0 题目标记为必填，提交时校验；缺失则阻断并定位到首个未完成项。
   - P1/P2 题目可选，未答不影响提交；缺失情况随分析请求上报，用于置信度调整。
3. **条件显示**：题目可配置 `visibleWhen`（如"口渴"选择"不渴"时隐藏"喜冷饮/喜热饮"子项）。规则集见 `[TBD]`（Q3）。
4. **匿名支持**：姓名题提供"匿名"开关；开启后姓名置空并隐藏输入框，报告与历史记录以"匿名用户+会话编号"展示。
5. **草稿自动保存**：见 §6.3.3。
6. **提交**：本地校验通过后提交至后端；写入 `inquiry_record`，会话内该诊标记完成，并调用问诊 AI 分析（§6.3.5）。

#### 6.3.1 字段清单（按分组）

**分组 1：基础信息收集（basic，P0）**

| 字段 | 类型 | 优先级 | 必填 | 校验规则 | 默认 |
|---|---|---|---|---|---|
| gender | 单选 | P0 | 是 | 枚举：男/女/未知 | 未知 |
| age | 数字 | P0 | 是 | 整数，1–120 | 空 |
| height | 数字 | P0 | 是 | 数值，50–250 cm，允许 1 位小数 | 空 |
| weight | 数字 | P0 | 是 | 数值，10–300 kg，允许 1 位小数 | 空 |
| name | 文本 | P1 | 否 | 1–20 字；开启"匿名"时禁用并置空 | 空 |
| anonymous | 开关 | P1 | 否 | 布尔；开启即姓名置空 | 关 |

**分组 2：主诉（chief_symptom，P0）**

| 字段 | 类型 | 优先级 | 必填 | 校验规则 | 默认 |
|---|---|---|---|---|---|
| chief_complaint | 多行文本 | P0 | 是 | 1–500 字 | 空 |

**分组 3：寒热症状收集（cold_heat，P0）**

| 字段 | 类型 | 优先级 | 必填 | 选项 | 默认 |
|---|---|---|---|---|---|
| cold_heat | 多选 | P0 | 是 | 怕冷畏寒、怕热喜凉、寒热交替、手足不温、手足心热、无明显寒热 | 空 |

**分组 4：汗出情况收集（sweating，P1）**

| 字段 | 类型 | 优先级 | 必填 | 选项 | 默认 |
|---|---|---|---|---|---|
| sweating | 多选 | P1 | 否 | 自汗、盗汗、无汗、汗出过多、正常 | 空 |

**分组 5：睡眠情况收集（sleep，P1）**

| 字段 | 类型 | 优先级 | 必填 | 选项 | 默认 |
|---|---|---|---|---|---|
| sleep | 多选 | P1 | 否 | 入睡困难、易醒、多梦、早醒、嗜睡、正常 | 空 |

**分组 6：饮食口味收集（diet_taste，P1）**

| 字段 | 类型 | 优先级 | 必填 | 选项 | 默认 |
|---|---|---|---|---|---|
| appetite | 单选 | P1 | 否 | 正常、食欲不振、食欲亢进 | 空 |
| taste | 多选 | P1 | 否 | 正常、口苦、口甜、口酸、口咸、口淡 | 空 |
| thirst | 单选 | P1 | 否 | 不渴、口渴喜冷饮、口渴喜热饮、口干不欲饮 | 空 |

**分组 7：二便情况收集（excretion，P1）**

| 字段 | 类型 | 优先级 | 必填 | 选项 | 默认 |
|---|---|---|---|---|---|
| stool | 单选 | P1 | 否 | 正常、便溏、便秘、先干后溏 | 空 |
| urine | 单选 | P1 | 否 | 正常、清长、黄赤、频数、癃闭 | 空 |

**分组 8：胸腹不适收集（chest_abdomen，P1）**

| 字段 | 类型 | 优先级 | 必填 | 选项 | 默认 |
|---|---|---|---|---|---|
| chest_abdomen | 多选 | P1 | 否 | 胸闷、心悸、腹胀、腹痛、胁痛、无明显不适 | 空 |

**分组 9：其他症状补充（other，P2）**

| 字段 | 类型 | 优先级 | 必填 | 校验规则 | 默认 |
|---|---|---|---|---|---|
| other_symptoms | 多行文本 | P2 | 否 | ≤ 1000 字 | 空 |

#### 6.3.2 数据校验规则

| 规则 | 说明 |
|---|---|
| 类型校验 | 数字字段仅接受数值，超范围拒绝并提示区间 |
| 必填校验 | 仅 P0 字段参与，提交时统一校验，失败定位首个未完成项并高亮 |
| 联动校验 | 匿名开关开启时姓名自动清空；不渴时隐藏喜冷饮/喜热饮 |
| 互斥校验 | 同一多选组内若同时选择"无明显寒热/正常"与阳性症状，提示需修正（规则集 `[TBD]`，Q3） |
| 长度校验 | 文本字段按上限截断提示，不允许超长提交 |

#### 6.3.3 草稿自动保存（P1）

**目的**：避免用户中途离开或刷新导致已填内容丢失。

**实现方案**

- 存储介质：浏览器 `localStorage`，键名 `inquiry_draft_{session_id}`。
- 触发时机：表单字段变更后**防抖 800ms** 自动写入；分组切换、页面隐藏（`visibilitychange`）时立即写入。
- 数据结构：

```json
{
  "session_id": "s_20261012_0001",
  "template_version": "inquiry_v1",
  "updated_at": "2026-10-12T10:12:00+08:00",
  "answers": { "gender": "男", "age": 34, "height": 172, "weight": 68,
               "cold_heat": ["怕冷畏寒"], "sleep": ["多梦"] }
}
```

- **恢复**：进入问诊模块时读取草稿，若存在且 `template_version` 与当前模板一致则自动回填并提示"已恢复上次填写内容"；版本不一致时丢弃草稿并提示用户重新填写（详见 §6.3.6）。
- **清理**：提交成功后立即删除本地草稿；用户点击"重置"时删除草稿。
- **与服务端草稿的区别**：本地草稿仅存于当前浏览器，用于即时恢复；服务端草稿（`PUT .../inquiry/draft`，见 §9.4）用于跨设备/跨会话恢复，二者互不冲突，服务端为准。

#### 6.3.4 表单实现方案

| 环节 | 实现方式 |
|---|---|
| 结构来源 | 由后端 `GET /api/v1/inquiry/template` 下发模板 JSON（分组 + 题目 + 类型 + 优先级 + 选项 + 校验），前端按模板动态渲染，避免硬编码 |
| 渲染引擎 | 前端维护"字段 Schema → 组件"映射（single→单选组、multi→多选组、number→数字输入、text→文本域、scale→量表、switch→开关），按分组渲染并生成导航锚点 |
| 状态管理 | 表单值集中于单一状态对象（`answers`），随模板 `qid` 作为 key；由状态驱动进度条、必填完成度与条件显隐 |
| 校验时机 | 失焦即时校验单字段；提交时全量校验并聚合错误列表 |
| 草稿策略 | 本地 localStorage 防抖保存 + 服务端草稿双写（§6.3.3） |
| 提交载荷 | `{ answers: [{qid, value}], template_version }`，提交后触发 AI 分析 |

#### 6.3.5 问诊 AI 智能分析

**目的**：将结构化问诊答案交由 AI 分析接口，产出证候判读与调理建议。

**触发**：问诊提交成功后自动触发；用户亦可在结果区点击"重新分析"。

**调用方式**：前端调用 `POST /api/v1/sessions/{session_id}/inquiry/ai-analysis`，后端转发至 AI 分析服务（见 §9.4.4）。分析异步执行，前端轮询 `task_id` 状态或订阅推送。

**输入**：`record_id`（问诊记录）+ 归一后的 `answers` + 缺答项清单（P1/P2 未答项）。

**输出字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| symptoms_summary | 文本 | 症状总结：对已采集症状的归纳描述 |
| main_syndrome | 对象 | 主要证候：`{ name, confidence }`，含证候名称与置信度 |
| secondary_syndromes | 数组 | 次要证候：`[{ name, confidence }]`，可多条 |
| treatment_principles | 字符串数组 | 治疗原则，如"益气健脾""温阳散寒" |
| recommendations | 对象数组 | 调理建议：`[{ category, text }]`，分类含饮食/作息/情志/复诊等 |

**结果与状态变化**：写入 `inquiry_analysis`，与 `inquiry_record` 关联；结果在问诊结果区展示，并作为三诊合参的问诊输入之一（§6.4）。

**异常与边界**

| 场景 | 处理 |
|---|---|
| AI 服务超时/不可用 | 问诊记录仍视为已提交成功；分析置 `failed`，展示"问诊分析暂不可用，可重试"，不阻断合参流程（合参将使用原始答案） |
| 输出字段缺失 | 缺失字段以"暂无"占位，不阻断展示 |
| 重新分析 | 覆盖当前分析结果并保留旧版本于审计日志 |

#### 6.3.6 异常与边界

| 场景 | 处理 |
|---|---|
| 未保存即离开 | 本地草稿已自动保存，直接离开不丢数据；弹窗仅在存在未持久化改动时提示 |
| 提交途中网络失败 | 保留已填内容与本地草稿，提供服务端重试 |
| 模板更新导致旧草稿不兼容 | 校验 `template_version`，不一致时丢弃旧草稿并提示重新填写 |
| localStorage 不可用（隐私模式） | 降级为不自动保存，提示用户手动保存 |
| 匿名 + 报告 | 报告与历史记录以"匿名用户 + 会话编号"标识 |

**状态**：`未填写 → 填写中（含本地草稿） → 已提交 → 分析中 → 分析完成 / 分析失败`

---

### 6.4 三诊合参模块（FR-FUSION）

**目的**：融合舌、面、问三诊数据，输出综合诊断结论与调理建议，生成报告主体。

**前置条件**：三诊数据均"已完成"且通过校验，会话状态为 `ready`。

**触发方式**：**用户手动确认后触发**。系统不自动开始合参——三诊齐全时展示确认态，由用户显式点击「开始分析」触发；后台仍在分析中或已有完成结果时直接续接，无需重复确认。

**处理规则**

1. **数据融合**
   - 汇总归一：将舌诊/面诊的特征项标签与置信度、各诊 AI 分析结果（`main_syndrome`/`secondary_syndromes`/`treatment_principles`）、问诊结构化答案统一为合参输入结构。
   - 一致性校验：识别跨诊矛盾（如舌色"淡白"与面色"潮红"并存），矛盾项在报告中显式列出并降低相关权重。
2. **AI 综合分析**：规则引擎完成特征加权与候选结论筛选，大模型基于候选结论生成自然语言结论与建议。
   - 输出：**综合诊断结论**（可多条，含置信度）、**辨证要点**、**三诊依据摘要**、**调理建议**（饮食、作息、情志、复诊建议）。
3. **置信度与免责**：计算合参整体置信度；当整体置信度低于阈值或存在数据缺失时，报告顶部展示"参考强度有限"提示。
4. **可追溯**：报告记录所引用的原始图像、特征项、所用规则版本与模型版本。

**缺诊处理**

| 缺诊情形 | 处理 |
|---|---|
| 缺任一一诊（舌诊 / 面诊 / 问诊） | **阻断合参**，提示"尚未完成：xxx（需三诊全部完成后方可合参）"，并在对应诊位给出直达入口；不生成报告 |
| 缺两诊及以上 | 同上，提示中逐项列出缺失诊位 |

> 说明：早期版本曾设计"仅缺一诊可降级合参（报告标注未含某诊并降低置信度）"。本期统一收紧为**三诊全齐方可合参**；降级所需的数据与规则能力（`missing_modules` 字段、缺失诊次权重按比例分摊）保留在数据结构与规则层，供后续版本按需放开。`[Assumption, TBD]`

**结果与状态变化**：生成 `fusion_result` 与 `report`，会话迁移至 `completed`。

**异常与边界**

| 场景 | 处理 |
|---|---|
| 分析超时 | 状态 `failed`，允许重试，不产生半成品报告 |
| 重复触发 | 幂等拦截，提示"分析进行中" |
| 重新分析 | 生成新版本报告，旧报告保留在历史中 |

**状态**：`不可用 → 就绪 → 分析中 → 已完成 / 失败`

---

### 6.5 报告管理模块（FR-REPORT）

**目的**：呈现、导出、打印与检索诊断报告。

**布局（报告视图）**

| 区域 | 职责 |
|---|---|
| 报告头 | 会话编号（展示为「用户姓名_月日」）、用户基本信息、生成时间、免责声明 |
| 结论区 | 综合诊断结论、辨证要点、整体置信度 |
| 依据区 | 舌诊/面诊图像（含区域标注）+ 特征项表格；问诊答案摘要 |
| 建议区 | 调理建议（分类展示） |
| 操作区 | 预览、导出 PDF、打印（A4）、归档 |

**处理规则**

1. **报告预览**：在线渲染，内容与 PDF/A4 打印一致（同一模板渲染）。
2. **PDF 导出**：按报告模板生成 PDF，文件名规则 `报告_{用户姓名}_{会话编号}_{yyyyMMdd}.pdf`；含分页、页眉页脚（页码）。
3. **A4 打印适配**：以 A4（210×297mm）为基准排版；打印前移除交互控件，保证不溢出、不截断；长表格自动分页且表头重复。
4. **历史记录查询**：支持按用户姓名、会话编号、生成时间范围、结论关键词（多词 AND）检索，并提供「匿名用户 / 已归档」快捷筛选；列表项可重新打开报告（详见 §9.6）。

**字段（报告元信息）**

| 字段 | 类型 | 说明 |
|---|---|---|
| report_id | 字符串 | 报告唯一标识 |
| session_id | 字符串 | 关联会话 |
| patient_snapshot | 对象 | 生成时的用户信息快照（不随档案变更） |
| generated_at | 时间 | 生成时间 |
| overall_confidence | 数字 | 合参整体置信度 |
| rule_version / model_version | 字符串 | 生成时所用规则与模型版本 |
| status | 枚举 | `draft` / `final` / `archived` |

**异常与边界**

| 场景 | 处理 |
|---|---|
| PDF 生成失败 | 提示重试，保留在线预览可用 |
| 图像加载失败 | 占位提示 + 重试，不阻断文本内容 |
| 报告已归档后编辑 | 禁止直接改，需"另存为新版本" |

**状态**：`生成中 → 已生成 → 已归档`（编辑产生新版本）

---

## 7. 共享规则与异常处理

### 7.1 图像采集与质量校验规则

舌诊、面诊共用同一套采集与质量校验机制，规则只在此处定义一次。

**采集来源**

| 来源 | 说明 |
|---|---|
| 本地上传 | 支持 `jpg/jpeg/png/webp`，单文件 ≤ 10MB，分辨率 ≥ 640×480 |
| 摄像头拍摄 | 调用设备摄像头，提供引导框与光照提示；拍摄后即时进入校验 |

**质量校验维度**

| 维度 | 判定内容 | 未通过提示示例 |
|---|---|---|
| 清晰度 | 图像模糊度（拉普拉斯方差） | "图像模糊，请保持稳定后重拍" |
| 光照 | 过曝/欠曝/偏色 | "光照不足/过强，请在均匀自然光下拍摄" |
| 构图 | 目标区域是否完整居中 | "舌体/面部未完整入镜，请调整距离" |
| 遮挡（面诊） | 口罩、头发、手部遮挡五官 | "请摘除遮挡物后重拍" |
| 人脸数（面诊） | 画面中清晰正脸数量 | "请确保画面中仅一张清晰正脸" |

**校验结果**

- `passed = true`：全部维度达标，进入区域提取。
- `passed = false`：阻断进入下一步，返回各维度得分与 `suggestions[]`，用户按提示重采。
- 质量分与置信度阈值默认 0.7 `[Assumption, TBD]`（Q2）。

### 7.2 计算与阈值规则

| 规则 | 定义 |
|---|---|
| 单诊整体置信度 | 该诊各特征项置信度的加权均值，权重由特征字典配置 |
| 合参整体置信度 | 三诊整体置信度按可配置权重加权；缺失诊次的权重按比例分摊 `[Assumption, TBD]` |
| 低可信判定 | 置信度 < 阈值（默认 0.7 `[Assumption, TBD]`）标记为低可信，报告显式提示 |
| 规则版本 | 每次分析记录所用字典/阈值版本，保证结果可复现 |

### 7.3 幂等与并发

- 会话内同一诊位的采集/分析请求按 `session_id + module + 幂等键` 去重。
- `analyzing` 状态下重复触发合参被拦截并返回进行中状态。

### 7.4 数据留存与隐私

- 原始图像默认私有，访问需后端签发临时 URL（有效期默认 15 分钟 `[Assumption, TBD]`）。
- 用户姓名、图像、问诊答案属敏感信息，传输 HTTPS，存储加密。
- 删除报告需二次确认并记录审计日志。
- 数据留存期限、删除权响应时限 `[TBD]`（依赖合规结论）。

## 8. 数据模型（核心实体）

```
-- 会话不单独建表：各记录表以 session_id 字符串关联（session_id 由前端生成，形如 s_YYYYMMDD_NNNN）
  ├── TongueRecord(舌诊记录)
  │     ├── record_id, session_id, image_ref, quality_score
  │     ├── mask_ref, extract_confidence
  │     └── features: [{name, label, confidence}]
  ├── TongueAnalysis(舌诊AI分析)
  │     ├── tongue_id, record_id, status
  │     ├── tongue_summary
  │     ├── main_syndrome: {name, confidence}
  │     ├── secondary_syndromes: [{name, confidence}]
  │     ├── treatment_principles: [string]
  │     ├── recommendations: [{category, text}]
  │     └── model_version
  ├── FaceRecord(面诊记录)
  │     ├── record_id, session_id, image_ref, quality_score
  │     ├── regions: [{name, bbox}]
  │     └── features: [{name, label, confidence, area?}]
  ├── FaceAnalysis(面诊AI分析)
  │     ├── face_id, record_id, status
  │     ├── face_summary
  │     ├── main_syndrome: {name, confidence}
  │     ├── secondary_syndromes: [{name, confidence}]
  │     ├── treatment_principles: [string]
  │     ├── recommendations: [{category, text}]
  │     └── model_version
  ├── InquiryRecord(问诊记录)
  │     ├── record_id, session_id, template_version
  │     ├── patient_snapshot: {name?, gender, age, height, weight, anonymous}
  │     └── answers: [{qid, type, value}]
  ├── InquiryAnalysis(问诊AI分析)
  │     ├── inquiry_id, record_id, status, missing_items
  │     ├── symptoms_summary
  │     ├── main_syndrome: {name, confidence}
  │     ├── secondary_syndromes: [{name, confidence}]
  │     ├── treatment_principles: [string]
  │     ├── recommendations: [{category, text}]
  │     └── model_version
  ├── FusionResult(合参结果)
  │     ├── fusion_id, session_id, overall_confidence
  │     ├── conclusions: [{text, confidence}]
  │     ├── syndrome_points: [string]
  │     ├── suggestions: [{category, text}]
  │     └── rule_version, model_version
  └── Report(报告)
        ├── report_id, session_id, status, generated_at
        └── report_url, pdf_url
```

| 实体 | 关键关系 |
|---|---|
| Session 1 : 1 TongueRecord / FaceRecord / InquiryRecord（按诊位唯一，重采覆盖并留痕） |
| TongueRecord 1 : N TongueAnalysis、FaceRecord 1 : N FaceAnalysis、InquiryRecord 1 : N InquiryAnalysis（重新分析产生新版本，当前有效版本唯一） |
| Session 1 : N Report（重新分析产生新版本） |
| Session 1 : 1 FusionResult（当前有效版本） |

---

## 9. 接口设计

**通用约定**

- 基础路径：`/api/v1`
- 认证：`Authorization: Bearer <token>`
- 请求/响应：`application/json`；上传使用 `multipart/form-data`
- 统一响应结构：

```json
{
  "code": 0,
  "message": "ok",
  "data": { },
  "trace_id": "a1b2c3d4"
}
```

| code | 含义 |
|---|---|
| 0 | 成功 |
| 40001 | 参数校验失败 |
| 40100 | 未认证/令牌失效 |
| 40300 | 无权限访问该资源 |
| 40400 | 资源不存在 |
| 40901 | 状态冲突（如分析进行中） |
| 42201 | 图像质量不达标 |
| 42900 | 请求过于频繁 |
| 50000 | 服务内部错误 |
| 50300 | 算法服务不可用 |

---

### 9.1 会话服务

> 本版本后端不提供会话 CRUD 接口：会话编号（`session_id`）由前端本地生成，格式为 `s_YYYYMMDD_NNNN`（末段为当天会话序号）；各模块接口以 `session_id` 作为路径参数（见 §9.2 ~ §9.6）。

---

### 9.2 舌诊服务

#### 9.2.1 上传舌象图像

`POST /api/v1/sessions/{session_id}/tongue/image`（`multipart/form-data`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| file | File | 是 | jpg/jpeg/png/webp，≤10MB |
| source | String | 是 | `upload` / `camera` |

响应：

```json
{ "code": 0, "message": "ok",
  "data": {
    "record_id": "t_0001",
    "image_ref": "img://tongue/t_0001_raw",
    "quality": { "passed": true, "clearness": 0.95, "lighting": 0.9, "composition": 0.88,
                 "suggestions": [] }
  } }
```

质量不达标：

```json
{ "code": 42201, "message": "图像质量不达标",
  "data": { "passed": false, "clearness": 0.5, "lighting": 0.4,
            "suggestions": ["光照不足，请在均匀自然光下重拍", "图像模糊，请保持稳定"] } }
```

#### 9.2.2 舌体区域提取

`POST /api/v1/sessions/{session_id}/tongue/extract`

请求：`{ "record_id": "t_0001" }`

响应：

```json
{ "code": 0, "message": "ok",
  "data": { "mask_ref": "img://tongue/t_0001_mask", "confidence": 0.86 } }
```

#### 9.2.3 舌象特征识别

`POST /api/v1/sessions/{session_id}/tongue/analyze`

请求：

```json
{ "record_id": "t_0001", "features": ["tongue_color", "coating_color", "coating_texture", "tongue_shape"] }
```

响应：

```json
{ "code": 0, "message": "ok",
  "data": {
    "record_id": "t_0001",
    "overall_confidence": 0.83,
    "features": [
      { "name": "tongue_color",     "label": "淡红", "confidence": 0.90 },
      { "name": "coating_color",    "label": "白",   "confidence": 0.85 },
      { "name": "coating_texture",  "label": "薄",   "confidence": 0.80 },
      { "name": "tongue_shape",     "label": "齿痕", "confidence": 0.76 }
    ]
  } }
```

#### 9.2.4 舌象 AI 分析

`POST /api/v1/sessions/{session_id}/tongue/ai-analysis`

请求：

```json
{ "record_id": "t_0001", "language": "zh-CN" }
```

响应（异步任务）：

```json
{ "code": 0, "message": "ok",
  "data": { "task_id": "task_8001", "analysis_status": "analyzing" } }
```

查询分析结果：`GET /api/v1/sessions/{session_id}/tongue/analysis`

```json
{ "code": 0, "message": "ok",
  "data": {
    "tongue_id": "ta_0001",
    "record_id": "t_0001",
    "status": "completed",
    "result": {
      "tongue_summary": "舌质淡红，舌苔薄白，舌体见齿痕，提示脾虚湿盛。",
      "main_syndrome": { "name": "脾气虚证", "confidence": 0.84 },
      "secondary_syndromes": [
        { "name": "湿盛困脾证", "confidence": 0.61 }
      ],
      "treatment_principles": ["健脾益气", "化湿"],
      "recommendations": [
        { "category": "饮食", "text": "宜健脾祛湿，少食生冷油腻。" },
        { "category": "作息", "text": "规律作息，适度运动。" },
        { "category": "复诊", "text": "建议 2 周后复诊对比舌象。" }
      ]
    },
    "model_version": "tongue_llm_v1"
  } }
```

分析失败：

```json
{ "code": 50300, "message": "舌象分析暂不可用，请重试",
  "data": { "status": "failed", "retryable": true } }
```

---

### 9.3 面诊服务

#### 9.3.1 上传面象图像

`POST /api/v1/sessions/{session_id}/face/image`（`multipart/form-data`）

字段同 §9.2.1，额外校验正脸与遮挡；响应结构一致，`data.quality` 含 `face_detected` 与 `single_face`。

#### 9.3.2 面部区域检测

`POST /api/v1/sessions/{session_id}/face/detect`

响应：

```json
{ "code": 0, "message": "ok",
  "data": {
    "face_count": 1,
    "regions": [
      { "name": "forehead", "bbox": [220, 120, 460, 260] },
      { "name": "left_cheek",  "bbox": [180, 280, 300, 420] },
      { "name": "right_cheek", "bbox": [380, 280, 500, 420] },
      { "name": "nose",        "bbox": [300, 260, 380, 380] }
    ] } }
```

检测失败/多脸：

```json
{ "code": 42201, "message": "画面需包含且仅包含一张清晰正脸",
  "data": { "face_count": 2, "suggestions": ["请确保单人正脸、五官无遮挡"] } }
```

#### 9.3.3 面象特征识别

`POST /api/v1/sessions/{session_id}/face/analyze`

响应：

```json
{ "code": 0, "message": "ok",
  "data": {
    "record_id": "f_0001",
    "overall_confidence": 0.80,
    "features": [
      { "name": "face_color",   "label": "红润", "confidence": 0.84 },
      { "name": "luster",       "label": "有光泽", "confidence": 0.79 },
      { "name": "acne",         "label": "少量", "confidence": 0.81, "area": ["forehead"] },
      { "name": "spots",        "label": "无",   "confidence": 0.88 }
    ] } }
```

#### 9.3.4 面象 AI 分析

`POST /api/v1/sessions/{session_id}/face/ai-analysis`

请求：

```json
{ "record_id": "f_0001", "language": "zh-CN" }
```

响应（异步任务）：

```json
{ "code": 0, "message": "ok",
  "data": { "task_id": "task_8101", "analysis_status": "analyzing" } }
```

查询分析结果：`GET /api/v1/sessions/{session_id}/face/analysis`

```json
{ "code": 0, "message": "ok",
  "data": {
    "face_id": "fa_0001",
    "record_id": "f_0001",
    "status": "completed",
    "result": {
      "face_summary": "面色红润有光泽，额头少量痤疮，无明显斑点，提示气血尚充。",
      "main_syndrome": { "name": "气血充足", "confidence": 0.78 },
      "secondary_syndromes": [
        { "name": "肺胃热盛（轻）", "confidence": 0.52 }
      ],
      "treatment_principles": ["调和气血", "清淡饮食"],
      "recommendations": [
        { "category": "饮食", "text": "清淡饮食，少食辛辣。" },
        { "category": "作息", "text": "保证睡眠，注意面部清洁。" }
      ]
    },
    "model_version": "face_llm_v1"
  } }
```

分析失败：

```json
{ "code": 50300, "message": "面象分析暂不可用，请重试",
  "data": { "status": "failed", "retryable": true } }
```

---

### 9.4 问诊服务

#### 9.4.1 获取问诊模板

`GET /api/v1/inquiry/template?version=latest`

响应 `data`：

```json
{
  "template_version": "inquiry_v1",
  "groups": [
    { "group_id": "basic", "title": "基础信息收集", "priority": "P0",
      "questions": [
        { "qid": "gender", "type": "single", "priority": "P0", "required": true,
          "options": ["男", "女", "未知"], "default": "未知" },
        { "qid": "age", "type": "number", "priority": "P0", "required": true,
          "range": [1, 120], "unit": "岁" },
        { "qid": "height", "type": "number", "priority": "P0", "required": true,
          "range": [50, 250], "unit": "cm", "decimals": 1 },
        { "qid": "weight", "type": "number", "priority": "P0", "required": true,
          "range": [10, 300], "unit": "kg", "decimals": 1 },
        { "qid": "name", "type": "text", "priority": "P1", "required": false, "maxLength": 20 },
        { "qid": "anonymous", "type": "switch", "priority": "P1", "required": false,
          "effect": "clearFields", "targets": ["name"] }
      ] },
    { "group_id": "chief_symptom", "title": "主诉", "priority": "P0",
      "questions": [
        { "qid": "chief_complaint", "type": "text", "priority": "P0", "required": true, "maxLength": 500 }
      ] },
    { "group_id": "cold_heat", "title": "寒热症状收集", "priority": "P0",
      "questions": [
        { "qid": "cold_heat", "type": "multi", "priority": "P0", "required": true,
          "options": ["怕冷畏寒", "怕热喜凉", "寒热交替", "手足不温", "手足心热", "无明显寒热"] }
      ] },
    { "group_id": "sweating", "title": "汗出情况收集", "priority": "P1",
      "questions": [
        { "qid": "sweating", "type": "multi", "priority": "P1", "required": false,
          "options": ["自汗", "盗汗", "无汗", "汗出过多", "正常"] }
      ] },
    { "group_id": "sleep", "title": "睡眠情况收集", "priority": "P1",
      "questions": [
        { "qid": "sleep", "type": "multi", "priority": "P1", "required": false,
          "options": ["入睡困难", "易醒", "多梦", "早醒", "嗜睡", "正常"] }
      ] },
    { "group_id": "diet_taste", "title": "饮食口味收集", "priority": "P1",
      "questions": [
        { "qid": "appetite", "type": "single", "priority": "P1", "required": false,
          "options": ["正常", "食欲不振", "食欲亢进"] },
        { "qid": "taste", "type": "multi", "priority": "P1", "required": false,
          "options": ["正常", "口苦", "口甜", "口酸", "口咸", "口淡"] },
        { "qid": "thirst", "type": "single", "priority": "P1", "required": false,
          "options": ["不渴", "口渴喜冷饮", "口渴喜热饮", "口干不欲饮"] }
      ] },
    { "group_id": "excretion", "title": "二便情况收集", "priority": "P1",
      "questions": [
        { "qid": "stool", "type": "single", "priority": "P1", "required": false,
          "options": ["正常", "便溏", "便秘", "先干后溏"] },
        { "qid": "urine", "type": "single", "priority": "P1", "required": false,
          "options": ["正常", "清长", "黄赤", "频数", "癃闭"] }
      ] },
    { "group_id": "chest_abdomen", "title": "胸腹不适收集", "priority": "P1",
      "questions": [
        { "qid": "chest_abdomen", "type": "multi", "priority": "P1", "required": false,
          "options": ["胸闷", "心悸", "腹胀", "腹痛", "胁痛", "无明显不适"] }
      ] },
    { "group_id": "other", "title": "其他症状补充", "priority": "P2",
      "questions": [
        { "qid": "other_symptoms", "type": "text", "priority": "P2", "required": false, "maxLength": 1000 }
      ] }
  ]
}
```

#### 9.4.2 保存草稿

`PUT /api/v1/sessions/{session_id}/inquiry/draft`

请求：

```json
{ "template_version": "inquiry_v1",
  "answers": [ { "qid": "gender", "value": "男" },
               { "qid": "chief_complaint", "value": "近期乏力、畏寒" } ] }
```

响应：`{ "code": 0, "message": "ok", "data": { "saved": true, "updated_at": "2026-10-12T10:12:00+08:00" } }`

#### 9.4.3 提交问诊

`POST /api/v1/sessions/{session_id}/inquiry/submit`

请求同草稿结构；响应：

```json
{ "code": 0, "message": "ok", "data": { "record_id": "q_0001", "completed": true } }
```

校验失败：

```json
{ "code": 40001, "message": "存在未完成的必填项",
  "data": { "missing": ["cold_heat"], "first_missing": "cold_heat" } }
```

#### 9.4.4 问诊 AI 分析

`POST /api/v1/sessions/{session_id}/inquiry/ai-analysis`

请求：

```json
{ "record_id": "q_0001", "language": "zh-CN" }
```

响应（异步任务）：

```json
{ "code": 0, "message": "ok",
  "data": { "task_id": "task_9001", "analysis_status": "analyzing" } }
```

查询分析结果：`GET /api/v1/sessions/{session_id}/inquiry/analysis`

```json
{ "code": 0, "message": "ok",
  "data": {
    "inquiry_id": "ia_0001",
    "record_id": "q_0001",
    "status": "completed",
    "missing_items": ["sweating", "other_symptoms"],
    "result": {
      "symptoms_summary": "用户乏力、畏寒，夜间多梦，食欲不振，二便尚可。",
      "main_syndrome": { "name": "气虚证", "confidence": 0.86 },
      "secondary_syndromes": [
        { "name": "阳虚证", "confidence": 0.62 },
        { "name": "心脾两虚证", "confidence": 0.55 }
      ],
      "treatment_principles": ["益气健脾", "温阳散寒"],
      "recommendations": [
        { "category": "饮食", "text": "宜温补，适量食用山药、红枣、姜茶。" },
        { "category": "作息", "text": "规律作息，避免熬夜，保证睡眠。" },
        { "category": "情志", "text": "保持情绪平稳，避免思虑过度。" },
        { "category": "复诊", "text": "建议 2 周后复诊评估。" }
      ]
    },
    "model_version": "inquiry_llm_v1"
  } }
```

分析失败：

```json
{ "code": 50300, "message": "问诊分析暂不可用，请重试",
  "data": { "status": "failed", "retryable": true } }
```

---

### 9.5 三诊合参服务

#### 触发合参分析

`POST /api/v1/sessions/{session_id}/fusion/analyze`

请求：

```json
{ "options": { "include_inquiry": true, "language": "zh-CN" } }
```

响应（同步返回任务即可，结果异步/轮询获取）：

```json
{ "code": 0, "message": "ok",
  "data": { "fusion_status": "analyzing", "task_id": "task_7788" } }
```

状态冲突：

```json
{ "code": 40901, "message": "分析进行中，请稍后查看" }
```

#### 查询合参结果

`GET /api/v1/sessions/{session_id}/fusion/result`

响应：

```json
{ "code": 0, "message": "ok",
  "data": {
    "fusion_id": "fu_0001",
    "status": "completed",
    "overall_confidence": 0.82,
    "missing_modules": [],
    "conclusions": [
      { "text": "综合舌、面、问诊信息，提示以气虚为主，兼有寒象。", "confidence": 0.82 }
    ],
    "syndrome_points": ["舌淡红、苔薄白", "面色红润", "主诉乏力、畏寒"],
    "suggestions": [
      { "category": "饮食", "text": "宜温补，适量食用山药、红枣、姜茶。" },
      { "category": "作息", "text": "规律作息，避免熬夜。" },
      { "category": "复诊", "text": "建议 2 周后复诊对比舌象变化。" }
    ],
    "rule_version": "rule_2026.10",
    "model_version": "fusion_llm_v1"
  } }
```

失败：

```json
{ "code": 50300, "message": "算法服务暂时不可用，请重试",
  "data": { "status": "failed", "retryable": true } }
```

---

### 9.6 报告服务

#### 生成报告

报告在合参分析完成（fusion `status=completed`）后由后端自动生成，**无独立写接口**；前端通过「获取报告详情」获取生成结果。

#### 获取报告详情

`GET /api/v1/reports/{report_id}`

响应 `data`：报告头、patient_snapshot、conclusions、依据（含图像签名 URL）、suggestions、overall_confidence、rule_version、model_version。

```json
{ "code": 0, "message": "ok",
  "data": {
    "report_id": "r_0001",
    "session_id": "s_20261012_0001",
    "status": "final",
    "generated_at": "2026-10-12T10:30:00+08:00",
    "patient_snapshot": { "name": "张三", "gender": "male", "age": 34 },
    "overall_confidence": 0.82,
    "images": [
      { "type": "tongue", "url": "https://cdn/...signed", "expires_at": "2026-10-12T10:45:00+08:00" }
    ],
    "pdf_url": "https://cdn/...report_r_0001.pdf"
  } }
```

#### 导出 PDF / 打印

- 导出：`GET /api/v1/reports/{report_id}/pdf` → 返回 PDF 流或签名 URL。
- 打印：前端基于同一报告模板触发 `window.print()`，CSS 按 A4 适配；无需单独接口。

#### 历史记录查询

`GET /api/v1/reports?patient_name=&keyword=&anonymous=&status=&from=&to=&page=1&page_size=20`

- 参数说明：`keyword` 可重复传入，多词为 **AND**，单次命中「结论摘要 / 会话编号 / 用户姓名」之一；`anonymous`（匿名用户）与 `status`（`draft/final/archived`，已归档传 `archived`）为快捷筛选；`from`/`to` 为 `yyyy-MM-dd`。分页约定见《开发任务文档》§4.1（`page ≥ 1`、`1 ≤ page_size ≤ 100`）。
- 仅返回未软删报告，按生成时间倒序；`reports` 暂无归属字段，故不支持按医生检索。

响应：

```json
{ "code": 0, "message": "ok",
  "data": {
    "total": 128, "page": 1, "page_size": 20,
    "items": [
      { "report_id": "r_0001", "session_id": "s_20261012_0001",
        "patient_name": "张三", "anonymous": false,
        "generated_at": "2026-10-12T10:30:00+08:00",
        "overall_confidence": 0.82, "health_level": "fair",
        "status": "final", "summary": "气虚为主，兼有寒象" }
    ] } }
```

#### 归档 / 删除

- `POST /api/v1/reports/{report_id}/archive` → `status = archived`
- `DELETE /api/v1/reports/{report_id}` → 软删（置 `deleted_at`，此后历史检索 / 报告详情 / PDF 均不再返回）；二次确认由前端完成，后端记录审计日志（PRD §7.4）

---

## 10. 非功能需求

| 类别 | 要求 |
|---|---|
| 性能 | 图像上传后质量校验 ≤ 3s；单诊分析 ≤ 10s；合参分析 ≤ 30s（异步，前端展示进度）`[Assumption, TBD]` |
| 兼容性 | Chrome/Edge 最新两个大版本；移动端 Safari/Chrome 支持摄像头采集 |
| 可用性 | 算法服务不可用时，采集与问诊仍可用，分析给出明确失败与重试 |
| 安全 | HTTPS 全链路；图像私有访问；敏感字段加密；操作审计留痕 |
| 可维护 | 特征字典、阈值、报告模板可配置且带版本 |
| 可访问性 | 表单可键盘操作；报告 PDF 文本可选中/含标签 |

---

## 11. 待确认问题（Open Questions）

| 编号 | 问题 | 影响 | 状态 |
|---|---|---|---|
| Q1 | 合规属性与备案要求（是否按医疗器械/互联网诊疗管理） | 影响免责声明、数据留存、报告签署流程 | `[TBD]` |
| Q2 | 图像质量分与置信度的具体阈值 | 影响重采提示与低可信判定 | `[TBD]` |
| Q3 | 问诊互斥/条件显隐规则集（题目全集已定义，见 §6.3.1、§9.4.1） | 影响表单校验与条件显示 | 题目已定，规则集 `[TBD]` |
| Q4 | 合参权重与缺诊权重分摊算法 | 影响整体置信度与结论 | `[TBD]` |
| Q5 | 数据留存期限、用户删除权响应时限 | 影响隐私实现 | `[TBD]` |
| Q7 | 是否需要机构/科室多级权限 | 影响 P1 范围与数据模型 | `[TBD]` |

---

## 附录 A：模块与需求 ID 索引

| 模块 | 需求 ID 前缀 | 关键能力 |
|---|---|---|
| 舌诊分析 | FR-TONGUE | 采集与质量校验、舌体提取、特征识别（舌色/苔色/苔质/舌形）、AI 分析（舌象总结/主证/次证/治则/建议） |
| 面诊分析 | FR-FACE | 采集与质量校验、面部检测、特征识别（面色/光泽/痘痘/斑点）、AI 分析（面象总结/主证/次证/治则/建议） |
| 问诊 | FR-INQUIRY | 分组表单（基础信息/寒热/汗出/睡眠/饮食口味/二便/胸腹/其他）、校验、localStorage 草稿、AI 分析（症状总结/主证/次证/治则/建议） |
| 三诊合参 | FR-FUSION | 数据融合、一致性校验、AI 分析、三诊齐备校验（用户确认后触发） |
| 报告管理 | FR-REPORT | 预览、PDF 导出、A4 打印、历史查询、归档 |

## 附录 B：接口清单速查

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/auth/register | 注册 |
| POST | /api/v1/auth/login | 登录 |
| POST | /api/v1/auth/logout | 登出 |
| POST | /api/v1/auth/refresh | 刷新令牌 |
| GET | /api/v1/auth/me | 当前用户信息 |
| PATCH | /api/v1/auth/me | 更新个人资料 |
| POST | /api/v1/auth/verify-code | 发送验证码 |
| POST | /api/v1/auth/password/change | 修改密码 |
| POST | /api/v1/auth/password/forgot | 发起找回 |
| POST | /api/v1/auth/password/reset | 重置密码 |
| POST | /api/v1/auth/avatar | 上传头像 |
| GET | /api/v1/health | 健康检查 |
| GET | /api/v1/inquiry/template | 获取问诊模板 |
| POST | /api/v1/sessions/{session_id}/tongue/image | 上传舌象 |
| POST | /api/v1/sessions/{session_id}/tongue/extract | 舌体区域提取 |
| POST | /api/v1/sessions/{session_id}/tongue/analyze | 舌象特征识别 |
| POST | /api/v1/sessions/{session_id}/tongue/ai-analysis | 舌象 AI 分析 |
| GET | /api/v1/sessions/{session_id}/tongue/analysis | 查询舌象分析结果 |
| GET | /api/v1/tongue/media/{record_no}/{filename} | 舌象媒体访问 |
| POST | /api/v1/sessions/{session_id}/face/image | 上传面象 |
| POST | /api/v1/sessions/{session_id}/face/detect | 面部区域检测 |
| POST | /api/v1/sessions/{session_id}/face/analyze | 面象特征识别 |
| POST | /api/v1/sessions/{session_id}/face/ai-analysis | 面象 AI 分析 |
| GET | /api/v1/sessions/{session_id}/face/analysis | 查询面象分析结果 |
| GET | /api/v1/face/media/{record_no}/{filename} | 面象媒体访问 |
| PUT | /api/v1/sessions/{session_id}/inquiry/draft | 保存问诊草稿 |
| POST | /api/v1/sessions/{session_id}/inquiry/submit | 提交问诊 |
| POST | /api/v1/sessions/{session_id}/inquiry/ai-analysis | 问诊 AI 分析 |
| GET | /api/v1/sessions/{session_id}/inquiry/analysis | 查询问诊分析结果 |
| GET | /api/v1/sessions/{session_id}/fusion/readiness | 三诊完成度校验 |
| POST | /api/v1/sessions/{session_id}/fusion/analyze | 触发合参 |
| GET | /api/v1/sessions/{session_id}/fusion/result | 查询合参结果 |
| GET | /api/v1/reports/{report_id} | 报告详情 |
| GET | /api/v1/reports/{report_id}/pdf | 导出 PDF |
| GET | /api/v1/reports | 历史记录查询 |
| GET | /api/v1/reports/compare | 报告对比 |
| POST | /api/v1/reports/{report_id}/archive | 归档报告 |
| DELETE | /api/v1/reports/{report_id} | 删除报告 |