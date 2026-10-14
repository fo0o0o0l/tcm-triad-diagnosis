# 中医三诊合一分析系统

基于「舌诊 + 面诊 + 问诊」三诊合参的 AI 辅助分析系统。前端 React 18+ / TypeScript，
后端 FastAPI（Python 3.11+），数据库 PostgreSQL 15。

| 文档 | 说明 |
|---|---|
| 《中医三诊合一分析系统 PRD》 | 产品需求规格说明书（功能、规则、接口通用约定） |
| 《中医三诊合一分析系统 UI/UX 设计文档》 | 视觉规范、Design Token、页面与交互 |
| 《中医三诊合一分析系统 开发任务文档》 | 工程落地层：环境搭建、数据库设计、模块任务与接口契约 |

---

## 1. 目录结构

```
中医三诊合一分析系统/
├─ frontend/                     # React + TypeScript + Vite
│  ├─ src/
│  │  ├─ components/             # 通用组件
│  │  ├─ pages/                  # 页面（P1~P10）
│  │  ├─ router/                 # 路由表与守卫
│  │  └─ styles/                 # tokens.css（Design Token）、global.css
│  ├─ package.json
│  └─ vite.config.ts
├─ backend/                      # FastAPI + Python
│  ├─ app/
│  │  ├─ api/v1/                 # API 路由（health / 后续 M1~M6）
│  │  ├─ core/                   # 配置、日志、统一响应、错误码
│  │  └─ main.py                 # 应用入口
│  ├─ tests/                     # 测试
│  ├─ requirements.txt
│  ├─ .env.example
│  └─ docker-compose.yml         # PG / Redis / MinIO / MailHog
├─ README.md
└─ *.md                          # PRD / UIUX / 开发任务文档
```

## 2. 环境要求

| 软件 | 版本 | 校验 |
|---|---|---|
| Git | ≥ 2.40 | `git --version` |
| Node.js | 18+ | `node -v` |
| npm | ≥ 10 | `npm -v` |
| Python | 3.11+ | `python --version` |
| Docker Desktop | ≥ 24（含 Compose v2） | `docker compose version` |

核心组件基线版本（与《开发任务文档》§2.1 一致）：React 19.2.5、TypeScript 6.0.2、
Vite 8.0.9、FastAPI 0.115.0、PostgreSQL 15+、Redis 7+。

## 3. 快速开始

### 3.1 基础设施（可选，需 Docker）

```powershell
docker compose -f backend/docker-compose.yml up -d
docker compose -f backend/docker-compose.yml ps      # 确认 healthcheck 通过
```

> 未安装 Docker 时可跳过：后端 `HEALTH_CHECK_DEPENDENCIES=false`（默认）时
> `/health` 仍可正常返回，依赖项标记为 `skipped`，不影响脚手架自检。

### 3.2 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env                          # 按需修改
uvicorn app.main:app --reload --port 8000
```

- 接口文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/v1/health>

### 3.3 前端

```powershell
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

环境变量见 `.env.development`（`VITE_API_BASE_URL` 指向后端 `/api/v1`）。

## 4. 测试与自检

```powershell
# 后端单元测试
cd backend; .\.venv\Scripts\python.exe -m pytest

# 前端类型检查 + 构建 + 静态检查
cd frontend; npm run build; npm run lint
```

| 检查项 | 通过标准 |
|---|---|
| `GET /api/v1/health` | 返回 `{code: 0, message: "ok", data: {...}, trace_id: "..."}` |
| 统一响应结构 | 所有接口返回 `{code, message, data, trace_id}` |
| trace_id 贯穿 | 响应头 `X-Trace-Id` 与响应体 `trace_id` 一致，可透传 |
| 错误码映射 | 未知路由 → `40400`（HTTP 404）；参数错误 → `40001`（HTTP 400） |
| 前端可构建 | `npm run build` 通过，`npm run lint` 无 error |

## 5. 开发规范

- 分支：`main`（生产）/ `develop`（集成）/ `feature/M{n}-{desc}` / `hotfix/{desc}`
- 提交：`feat|fix|refactor|test|docs|chore(scope): 描述`，例 `feat(tongue): 舌象上传接口`
- 统一响应与错误码：见《开发任务文档》§4.1；阈值/规则集/模型版本一律「可配置 + 版本化」，不写死
- 前端组件禁止硬编码颜色与尺寸，一律引用 `src/styles/tokens.css`（UI/UX §3）

## 6. 模块进度

| 顺序 | 模块 | 状态 |
|---|---|---|
| — | 模块一：项目初始化、环境搭建 | ✅ 已完成（前后端脚手架 + 统一响应 + trace_id + 健康检查 + 测试） |
| M0 | 公共基础层（会话服务、存储、异步任务、鉴权基座、迁移） | ⏳ 待开发 |
| M1 | 用户认证（登录 / 注册 / 密码找回） | ⏳ 待开发 |
| M2 | 舌诊采集 | ⏳ 待开发 |
| M3 | 面诊采集 | ⏳ 待开发 |
| M4 | 智能问诊 | ⏳ 待开发 |
| M5 | 三诊合参 | ⏳ 待开发 |
| M6 | 报告管理 | ⏳ 待开发 |
