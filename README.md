# 中医三诊合一分析系统

面向中医诊疗场景的 Web 应用：把「**舌诊 + 面诊 + 问诊**」三诊数据采集、AI 分析、合参推理与标准化报告输出串成一条完整会话流。

采集环节做图像质量校验，分析环节输出结构化特征项 + 置信度，合参环节做跨诊一致性校验与规则加权，报告环节支持预览、PDF 导出、A4 打印、归档与历史检索（含两次报告趋势对比）。

**免责声明**：本系统输出为**辅助参考**，不构成最终诊断，请结合临床判断。

## 技术栈与实测环境

| 层 | 技术 | 本项目验证版本 |
|---|---|---|
| 前端 | React + TypeScript + Vite，React Router + Zustand，CSS 变量设计令牌 | Node 24.14.1 / npm 11.11.0（React 19.2.5、TS 6.0.2、Vite 8.0.9） |
| 后端 | FastAPI + SQLAlchemy 2.0(async) + Alembic，structlog 结构化日志 | Python 3.13.9（FastAPI 0.115） |
| 算法服务 | 独立 FastAPI 进程，调用阿里云通义千问（`qwen-plus` 生成结论、`qwen3-vl-plus` 看图取特征） | 端口 8100 |
| 基础设施 | PostgreSQL / Redis / MinIO / MailHog（`backend/docker-compose.yml` 编排） | 开发期按下方说明可降级 |

## 设计文档（需求的唯一来源）

| 文档 | 内容 |
|---|---|
| [中医三诊合一分析系统-PRD.md](中医三诊合一分析系统-PRD.md) | 产品需求：功能规则、状态机、接口通用约定、异常与边界 |
| [中医三诊合一分析系统-UIUX设计文档.md](中医三诊合一分析系统-UIUX设计文档.md) | 视觉规范、Design Token、主题系统、页面与交互、动效、可访问性 |
| [中医三诊合一分析系统-开发任务文档.md](中医三诊合一分析系统-开发任务文档.md) | 工程落地：环境、数据库设计、模块任务分解、接口契约 |
| [docs/测试用例.html](docs/测试用例.html) | 测试用例清单 |

> 三者若有分歧，以文档为准；实现与文档不一致时应先改文档或改实现，不允许长期双轨。

## 快速开始（推荐：一键启动）

```powershell
python run.py                  # 启动 后端 + 算法服务 + 前端（MailHog 视 Docker 情况自动处理）
```

启动后会打印各服务网址（可直接 Ctrl+点击打开）与日志文件路径，并自动打开前端页面。

| 服务 | 端口 | 地址 |
|---|---|---|
| 前端 Vite | 5173 | <http://localhost:5173> |
| 后端 FastAPI | 8000 | <http://localhost:8000/docs> |
| 算法服务 | 8100 | <http://localhost:8100/health> |
| MailHog（验证码镜像邮箱） | 8025 | <http://localhost:8025> |

常用参数：

```powershell
python run.py --no-mailhog     # 不启动 MailHog
python run.py --no-algo        # 不启动算法服务（AI 分析降级为本地规则 mock）
python run.py --no-frontend    # 只起后端 + 算法服务
python run.py --no-force       # 不清理占用端口的旧进程
python run.py --no-logs        # 服务已在运行时，不把日志刷到当前终端
```

约定行为：

- **默认先清理端口**：启动前结束占用 8000/8100/5173 的旧进程，并等端口真正释放再启动，因此重复运行不会再出现「端口已被占用 → 跳过启动」；端口占用者若是僵死的父进程，会按命令行兜底清理。
- **日志随时可见**：自己启动时日志转发到当前终端；若服务已在别处运行，则改为**实时跟踪两份日志文件**（Ctrl+C 退出）。
- 按 Ctrl+C 一键停止全部子进程。

## 手动启动（分步）

```powershell
# 1) 基础设施（可选，需 Docker）
docker compose -f backend/docker-compose.yml up -d

# 2) 后端
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env          # 按需修改
alembic upgrade head                 # 建表
uvicorn app.main:app --reload --port 8000

# 3) 算法服务（AI 大模型解读；未配置密钥时后端会自动降级，主链路不受影响）
cd algorithm-service
Copy-Item .env.example .env          # 填入 DASHSCOPE_API_KEY
uvicorn main:app --reload --port 8100

# 4) 前端
cd frontend
npm install
npm run dev
```

> 未启动 PG/Redis/MinIO 时：`backend/.env` 保持 `HEALTH_CHECK_DEPENDENCIES=false`（默认），`/health` 正常返回，依赖项标记为 `skipped`，不影响功能调试。

## 日志与运行期数据

日志**同时输出到终端与滚动文件**（按 10MB 滚动、保留 5 份），结构化日志每行带 `trace_id`，与响应头 `X-Trace-Id` 一致，可用于串联一次请求的全链路。

```powershell
Get-Content backend\logs\backend.log -Tail 50 -Wait            # 后端
Get-Content algorithm-service\logs\alg.log -Tail 50 -Wait      # 算法服务
Select-String -Path backend\logs\backend.log -Pattern '<trace_id>'   # 回溯某次请求
```

以下运行期数据**不入版本库**（见 `.gitignore`）：`logs/`、`backend/media/`（患者原图与头像）、`.venv/`、`node_modules/`、`dist/`、真实 `.env`。

## 主要能力

| 模块 | 已实现 |
|---|---|
| M0 公共基础层 | 统一响应 `{code, message, data, trace_id}`、trace_id 中间件、全局异常与错误码映射、结构化日志落盘、配置与依赖探测 |
| M1 用户认证 | 注册（邮箱/短信验证码）、登录（失败限流）、刷新/登出（令牌旋转）、找回与重置、改密（成功后吊销该账号全部刷新令牌）、资料更新、头像上传 |
| M2 舌诊 | 本地上传 / 摄像头采集、质量校验（不达标阻断重拍）、舌体区域提取、舌色/苔色/苔质/舌形特征识别、AI 解读 |
| M3 面诊 | 复用 M2 链路，替换术语；额外正脸 / 遮挡 / 多脸校验 |
| M4 问诊 | 模板驱动动态渲染、分组导航、必填进度、条件显隐、匿名、本地 + 服务端双草稿、AI 证候判读 |
| M5 三诊合参 | 三诊输入归一、跨诊一致性校验、规则加权置信度、健康等级映射、大模型结论生成 |
| M6 报告管理 | 8 个 Tab 的报告数据、PDF 导出、A4 打印、归档、历史检索、双报告趋势对比 |
| 个人中心 | 资料（姓名/手机/科室）、头像、外观（三套主题）、修改密码、我的报告、退出登录 |

页面路由：`/login`、`/register`、`/tongue`、`/face`、`/inquiry`、`/analysis`、`/report`、`/reports`、`/compare`、`/profile`。

几处值得注意的交互约定：

- **合参需用户显式触发且三诊齐全**：进入分析页只做前置校验，不自动开始；缺任一一诊即阻断，并逐项列出未完成诊位、给出一键直达采集页的入口。
- **AI 结果标注来源**：结果卡上会显示实际调用方（如「通义千问 qwen-plus」）或「本地规则（已降级）」，降级是静默兜底、接口仍返回成功，据此即可判断是否真的调用了大模型。
- **主题三套**：白色（默认，不跟随系统）/ 蓝紫 / 深色，通过 `html[data-theme]` + 设计令牌切换，持久化于 `localStorage['ui_theme']`，组件不硬编码颜色。
- **会话编号展示**为「患者姓名_月日」，当天第 2 个及以后追加 `#序号`；未填姓名 / 匿名分别显示「待补姓名」「匿名患者」。
- **头像更换即时生效**：媒体接口带 `no-store`，且头像 URL 附带文件版本参数（`?v=…`），避免同址覆盖导致界面仍显示旧图。

## 已知限制

| 项 | 说明 |
|---|---|
| 报告无归属字段 | `reports` 表只存不透明 `session_id`，没有医生外键，因此历史列表与个人中心统计均为「全部未软删报告」口径，P7 的「我的报告」快捷筛选为禁用占位 |
| 会话标识由前端生成 | 独立的会话服务（M0-6）未落地，`session_id` 现由前端生成并随 `?session_id=` 传递 |
| 开发期简化实现 | 登录限流与合参并发锁为进程内实现；图像存本地磁盘（对外统一 `img://` 引用，生产切换 S3/MinIO）；短信验证码在开发期镜像投递到 MailHog |
| 患者分享页 | 未实现（按 PRD 属后续迭代） |

## 测试与自检

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest        # 115 项，全通过
cd frontend; npm run build; npm run lint                  # 构建与 eslint 无 error/warning
```

| 检查项 | 通过标准 |
|---|---|
| `GET /api/v1/health` | 返回 `{code: 0, message: "ok", data: {...}, trace_id: "..."}` |
| trace_id 贯穿 | 响应头 `X-Trace-Id` 与响应体 `trace_id` 一致；日志可反查同一 id |
| 错误码映射 | 40100 → 前端跳登录；42201 → 展示 suggestions；50300 → AI 降级可重试 |
| 合参前置校验 | 三诊未齐 → `40001` + `missing_modules`；分析中重复触发 → `40901` |

## 目录结构

```
中医三诊合一分析系统/
├─ run.py                        # 一键启动入口（清理端口 / 日志可见 / Ctrl+C 全停）
├─ backend/                      # FastAPI 后端
│  ├─ app/{api,core,models,repositories,schemas,services}/
│  ├─ migrations/                # Alembic 迁移
│  ├─ tests/                     # pytest 用例
│  ├─ docker-compose.yml         # PG / Redis / MinIO / MailHog
│  ├─ media/ · logs/             # 运行期数据（不入版本库）
│  └─ alembic.ini · requirements.txt · .env.example
├─ algorithm-service/            # 独立算法服务（通义千问调用与结果归一）
│  └─ main.py · llm_client.py · prompts.py · parsing.py · schemas.py
├─ frontend/                     # React + TypeScript + Vite
│  └─ src/{assets,components,pages,router,services,stores,styles,types,utils}/
├─ docs/                         # 测试用例等附属材料
└─ *.md                          # PRD / UIUX / 开发任务文档
```

## 开发规范

- 提交信息：`feat|fix|refactor|test|docs|chore(scope): 描述`，例 `feat(fusion): 合参前置校验收紧为三诊全齐`
- 前端组件**禁止硬编码颜色与尺寸**，一律引用 `src/styles/tokens.css`（Design Token）
- 阈值、规则集、模型版本一律「可配置 + 版本化」，不写死在代码里
- 接口契约变更须先改《开发任务文档》再改代码
