"""应用配置：基于 pydantic-settings 从环境变量 / `.env` 读取。

字段与环境变量一一对应，详见 `backend/.env.example` 与《开发任务文档》§2.4。
所有阈值、密钥均通过环境变量注入，禁止在代码中写死。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。字段名即环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 应用 ----
    APP_ENV: str = "dev"
    APP_NAME: str = "中医三诊合一分析系统"
    APP_VERSION: str = "0.1.0"
    APP_PORT: int = 8000
    API_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # ---- 日志（终端 + 滚动文件双输出，便于回溯请求链路）----
    LOG_TO_FILE: bool = True
    LOG_DIR: str = "logs"
    LOG_FILE: str = "backend.log"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    # ---- CORS（前端开发服务器）----
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # ---- 数据库 / 缓存（M0-2 起启用）----
    DATABASE_URL: str = "postgresql+asyncpg://tcm:tcm_dev_pwd@localhost:5432/tcm_triad"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---- 鉴权（M0-3 起启用）----
    JWT_SECRET: str = "please-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 120
    JWT_REFRESH_EXPIRE_DAYS: int = 14
    PASSWORD_HASH_ROUNDS: int = 12

    # ---- 对象存储（M0-4 起启用）----
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_PRIVATE: str = "tcm-private"
    S3_SIGNED_URL_EXPIRE_SECONDS: int = 900

    # ---- 算法服务（开发期指向 algorithm-mock）----
    ALGO_BASE_URL: str = "http://localhost:8100"
    ALGO_TIMEOUT_SECONDS: int = 60

    # ---- 图像存储（M2 舌诊；开发期落本地磁盘，生产可切换 S3/MinIO）----
    MEDIA_ROOT: str = "media"
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    ALLOWED_IMAGE_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]

    # ---- 邮件（MailHog）----
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_FROM: str = "no-reply@tcm-triad.local"

    # ---- 业务默认值（PRD §7.1 [TBD]，可配置 + 版本化）----
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7

    # ---- 健康检查 ----
    # 本地未启动 PG/Redis/MinIO 时保持 false，`/health` 将依赖项标记为 skipped。
    HEALTH_CHECK_DEPENDENCIES: bool = False


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置（便于测试时 `get_settings.cache_clear()` 覆盖）。"""
    return Settings()


settings = get_settings()
