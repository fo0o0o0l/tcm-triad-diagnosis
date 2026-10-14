"""认证业务逻辑（《开发任务文档》§4.3 A1~A11）。

分层：endpoint（HTTP） → service（业务规则/事务） → repository（SQL）。
审计日志：当前以结构化日志记录 `action`，`audit_logs` 表接入后改为持久化（全局表，归属后续模块）。
"""

from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.core.response import BusinessError
from app.core.security import (
    access_expire_delta,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_numeric_code,
    generate_urlsafe_token,
    hash_password,
    hash_token,
    refresh_expire_delta,
    verify_password,
)
from app.models.user import User, UserRole, UserStatus
from app.repositories.user import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
    UserRepository,
    VerificationCodeRepository,
)
from app.schemas.auth import (
    CODE_EXPIRE_SECONDS,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotRequest,
    ForgotResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SendCodeRequest,
    SendCodeResponse,
    UpdateProfileRequest,
)
from app.schemas.user import UserBrief, UserProfile, UserStats
from app.services import history_service, image_storage

logger = get_logger(__name__)

# ---- 登录限流参数（PRD §7.3 / UI/UX §5.1.3）----
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 900

# ---- 头像约束（《开发任务文档》§4.3 A11）----
AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class _LoginAttemptLimiter:
    """登录失败计数（进程内实现，开发期使用）。

    生产环境应替换为 Redis 计数（跨实例共享）；此处保持最小实现，
    仅在连续失败达到阈值时锁定账号一段时间。
    """

    def __init__(self) -> None:
        self._failures: dict[str, tuple[int, datetime]] = {}
        self._lock = asyncio.Lock()

    async def check(self, account: str) -> None:
        async with self._lock:
            record = self._failures.get(account)
            if record is None:
                return
            count, first_at = record
            if datetime.now(timezone.utc) - first_at > timedelta(seconds=LOGIN_LOCK_SECONDS):
                self._failures.pop(account, None)
                return
            if count >= LOGIN_MAX_FAILURES:
                raise BusinessError(ErrorCode.TOO_MANY_REQUESTS, "登录失败次数过多，请稍后再试")

    async def record_failure(self, account: str) -> None:
        async with self._lock:
            record = self._failures.get(account)
            now = datetime.now(timezone.utc)
            if record is None or now - record[1] > timedelta(seconds=LOGIN_LOCK_SECONDS):
                self._failures[account] = (1, now)
            else:
                self._failures[account] = (record[0] + 1, record[1])

    async def reset(self, account: str) -> None:
        async with self._lock:
            self._failures.pop(account, None)


_limiter = _LoginAttemptLimiter()


def _avatar_public_path(user_no: str, ref: str | None) -> str | None:
    """把 `img://avatar/{user_no}/avatar.{ext}` 转为客户端可访问路径。

    媒体接口为免签读取（开发期），路径相对 `/api/v1` 拼接即可访问；
    引用为空或格式不符时返回 `None`，避免把内部引用格式暴露给前端。

    头像按固定路径就地覆盖：若 URL 不变，`<img>` 的 `src` 就不变，React 不会
    触碰该 DOM 节点，浏览器也就不会重新请求（即使响应带 `no-store`），旧位图会
    一直显示到手动刷新。故附加文件修改时间作为版本参数，使每次更换头像后 URL
    必然变化，前端无需刷新即可加载新图。
    """
    if not ref or not ref.startswith("img://avatar/"):
        return None
    filename = ref.rsplit("/", 1)[-1]
    path = f"/auth/avatar/media/{user_no}/{filename}"
    try:
        version = image_storage.resolve(user_no, filename, module="avatar").stat().st_mtime_ns
    except (ValueError, OSError):
        return path
    return f"{path}?v={version}"


def _to_brief(user: User) -> UserBrief:
    return UserBrief(
        user_no=user.user_no,
        username=user.username,
        name=user.name,
        role=user.role,
        avatar_url=_avatar_public_path(user.user_no, user.avatar_ref),
    )


# ---- 验证码投递（开发期 MailHog；短信渠道在 dev 下镜像到 MailHog）----
#: 开发环境短信镜像邮箱域名（MailHog 收件人形如 sms-<手机号>@tcm-triad.local）
SMS_MIRROR_DOMAIN = "tcm-triad.local"


def _send_code_email(target: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = target
    message["Subject"] = "【中医三诊合一分析系统】验证码"
    message.set_content(f"您的验证码为 {code}，{CODE_EXPIRE_SECONDS // 60} 分钟内有效。")
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as smtp:
        smtp.send_message(message)


def _send_code_sms_mirror(target: str, code: str) -> None:
    """开发环境把短信验证码镜像投递到 MailHog，便于联调（无真实短信网关）。"""
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = f"sms-{target}@{SMS_MIRROR_DOMAIN}"
    message["Subject"] = f"【中医三诊合一分析系统】短信验证码（{target}）"
    message.set_content(
        f"【开发环境短信通道镜像】\n手机号 {target} 的验证码为 {code}，"
        f"{CODE_EXPIRE_SECONDS // 60} 分钟内有效。"
    )
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as smtp:
        smtp.send_message(message)


async def _dispatch_code(target: str, code: str, channel: str) -> None:
    if channel == "email":
        try:
            await asyncio.to_thread(_send_code_email, target, code)
        except OSError as exc:  # 邮件服务不可用不应阻断流程（验证码已入库）
            logger.warning("verify_code_email_failed", target=target, error=str(exc))
        return

    logger.info("verify_code_sms_dev", target=target, code=code)
    if settings.APP_ENV == "dev":
        # 开发环境无真实短信网关：短信验证码镜像投递到 MailHog（方案二）
        try:
            await asyncio.to_thread(_send_code_sms_mirror, target, code)
        except OSError as exc:
            logger.warning("verify_code_sms_mirror_failed", target=target, error=str(exc))


async def _consume_code(db: AsyncSession, *, target: str, scene: str, code: str) -> None:
    """校验并一次性消费验证码，失败抛 40001。"""
    record = await VerificationCodeRepository.get_latest_active(db, target=target, scene=scene)
    if record is None or record.expires_at < datetime.now(timezone.utc):
        raise BusinessError(ErrorCode.PARAM_INVALID, "验证码无效或已过期")
    if hash_token(code) != record.code_hash:
        raise BusinessError(ErrorCode.PARAM_INVALID, "验证码不正确")
    await VerificationCodeRepository.mark_used(db, record.id)


# ---- A6 发送验证码 ----
async def send_verification_code(db: AsyncSession, payload: SendCodeRequest) -> SendCodeResponse:
    code = generate_numeric_code()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CODE_EXPIRE_SECONDS)
    await VerificationCodeRepository.create(
        db,
        target=payload.target,
        scene=payload.scene,
        code_hash=hash_token(code),
        expires_at=expires_at,
    )
    await _dispatch_code(payload.target, code, payload.channel)
    await db.commit()
    return SendCodeResponse(sent=True)


# ---- A1 注册 ----
async def register(db: AsyncSession, payload: RegisterRequest) -> RegisterResponse:
    if await UserRepository.exists_username(db, payload.username):
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            data={"fields": [{"field": "username", "error": "用户名已存在"}]},
        )
    if payload.email and await UserRepository.exists_email(db, payload.email):
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            data={"fields": [{"field": "email", "error": "邮箱已被注册"}]},
        )
    if payload.phone and await UserRepository.exists_phone(db, payload.phone):
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            data={"fields": [{"field": "phone", "error": "手机号已被注册"}]},
        )

    target = payload.email or payload.phone
    assert target is not None  # schema 已保证至少提供一个
    await _consume_code(db, target=target, scene="register", code=payload.verify_code)

    user = User(
        username=payload.username,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        name=payload.name,
        department=payload.department,
        role=UserRole.DOCTOR,
        status=UserStatus.ACTIVE,
        email_verified=payload.email is not None,
    )
    await UserRepository.create(db, user)
    await db.commit()
    logger.info("auth.register", user_no=user.user_no, username=user.username)
    return RegisterResponse.model_validate(user)


# ---- 令牌签发（登录 / 刷新共用）----
async def _issue_tokens(
    db: AsyncSession,
    *,
    user: User,
    remember: bool,
    device_info: str | None,
    ip: str | None,
) -> LoginResponse:
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id, remember=remember)
    await RefreshTokenRepository.create(
        db,
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + refresh_expire_delta(remember=remember),
        device_info=device_info,
        ip=ip,
    )
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(access_expire_delta().total_seconds()),
        user=_to_brief(user),
    )


# ---- A2 登录 ----
async def login(
    db: AsyncSession,
    payload: LoginRequest,
    *,
    device_info: str | None = None,
    ip: str | None = None,
) -> LoginResponse:
    await _limiter.check(payload.account)

    user = await UserRepository.get_by_account(db, payload.account)
    if user is None or not verify_password(payload.password, user.password_hash):
        await _limiter.record_failure(payload.account)
        raise BusinessError(ErrorCode.UNAUTHORIZED, "账号或密码错误")
    if user.status != UserStatus.ACTIVE:
        raise BusinessError(ErrorCode.FORBIDDEN, "账号已被禁用")

    result = await _issue_tokens(
        db, user=user, remember=payload.remember, device_info=device_info, ip=ip
    )
    await UserRepository.touch_last_login(db, user.id)
    await db.commit()
    await _limiter.reset(payload.account)
    logger.info("auth.login", user_no=user.user_no, username=user.username)
    return result


# ---- A3 刷新令牌（旋转）----
async def refresh(
    db: AsyncSession,
    payload: RefreshRequest,
    *,
    device_info: str | None = None,
    ip: str | None = None,
) -> LoginResponse:
    claims = decode_token(payload.refresh_token, expected_type="refresh")
    record = await RefreshTokenRepository.get_active_by_hash(db, hash_token(payload.refresh_token))
    if record is None or record.expires_at < datetime.now(timezone.utc):
        raise BusinessError(ErrorCode.UNAUTHORIZED, "刷新令牌无效或已失效")

    user = await UserRepository.get_by_id(db, int(claims["sub"]))
    if user is None or user.status != UserStatus.ACTIVE:
        raise BusinessError(ErrorCode.UNAUTHORIZED)

    # 旋转：旧令牌立即吊销，签发新令牌
    await RefreshTokenRepository.revoke(db, record.token_hash)
    result = await _issue_tokens(
        db, user=user, remember=False, device_info=device_info, ip=ip
    )
    await db.commit()
    logger.info("auth.refresh", user_no=user.user_no)
    return result


# ---- A4 登出 ----
async def logout(db: AsyncSession, payload: LogoutRequest) -> LogoutResponse:
    revoked = await RefreshTokenRepository.revoke(db, hash_token(payload.refresh_token))
    await db.commit()
    return LogoutResponse(revoked=revoked)


# ---- A5 当前用户 ----
def _month_start_utc() -> datetime:
    """当前自然月起点（按服务器本地时区）对应的 UTC 时刻，用于「本月报告」统计。"""
    now_local = datetime.now().astimezone()
    return now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


async def get_profile(db: AsyncSession, user: User) -> UserProfile:
    profile = UserProfile.model_validate(user)
    # ORM 字段名为 avatar_ref，需显式转换为客户端可访问路径
    profile.avatar_url = _avatar_public_path(user.user_no, user.avatar_ref)
    # 报告统计：口径与 P7 历史列表一致（reports 暂无医生归属字段，故统计全部未软删报告；
    # 归档计入、软删排除；「本月」按服务器本地时区的自然月）。
    profile.stats = UserStats(
        total_reports=await history_service.count_reports(db),
        month_reports=await history_service.count_reports(db, generated_from=_month_start_utc()),
    )
    return profile


# ---- A7 发起找回（防账号枚举，恒返回 sent=true）----
async def forgot_password(db: AsyncSession, payload: ForgotRequest) -> ForgotResponse:
    user = await UserRepository.get_by_account(db, payload.account)
    if user is not None:
        target = user.email if payload.channel == "email" else user.phone
        if target:
            code = generate_numeric_code()
            await VerificationCodeRepository.create(
                db,
                target=target,
                scene="reset_password",
                code_hash=hash_token(code),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=CODE_EXPIRE_SECONDS),
            )
            reset_token = generate_urlsafe_token()
            await PasswordResetTokenRepository.create(
                db,
                user_id=user.id,
                token_hash=hash_token(reset_token),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=CODE_EXPIRE_SECONDS),
            )
            await _dispatch_code(target, code, payload.channel)
    await db.commit()
    return ForgotResponse(sent=True)


# ---- A8 重置密码 ----
async def reset_password(db: AsyncSession, payload: ResetPasswordRequest) -> ResetPasswordResponse:
    user = await UserRepository.get_by_account(db, payload.account)
    if user is None:
        raise BusinessError(ErrorCode.PARAM_INVALID, "账号不存在或校验失败")

    if payload.reset_token:
        record = await PasswordResetTokenRepository.get_active_by_hash(
            db, hash_token(payload.reset_token)
        )
        if (
            record is None
            or record.user_id != user.id
            or record.expires_at < datetime.now(timezone.utc)
        ):
            raise BusinessError(ErrorCode.PARAM_INVALID, "重置令牌无效或已过期")
        await PasswordResetTokenRepository.mark_used(db, record.id)
    else:
        assert payload.verify_code is not None
        target = user.email or user.phone
        if not target:
            raise BusinessError(ErrorCode.PARAM_INVALID, "账号未绑定邮箱或手机号")
        await _consume_code(
            db, target=target, scene="reset_password", code=payload.verify_code
        )

    await UserRepository.update_password_hash(db, user.id, hash_password(payload.new_password))
    await RefreshTokenRepository.revoke_all_for_user(db, user.id)
    await db.commit()
    logger.info("auth.password.reset", user_no=user.user_no)
    return ResetPasswordResponse(reset=True)


# ---- A9 修改密码（登录态）----
async def change_password(
    db: AsyncSession, user: User, payload: ChangePasswordRequest
) -> ChangePasswordResponse:
    if not verify_password(payload.old_password, user.password_hash):
        raise BusinessError(ErrorCode.PARAM_INVALID, "原密码不正确")
    await UserRepository.update_password_hash(db, user.id, hash_password(payload.new_password))
    await RefreshTokenRepository.revoke_all_for_user(db, user.id)
    await db.commit()
    logger.info("auth.password.change", user_no=user.user_no)
    return ChangePasswordResponse(changed=True)


# ---- A10 更新个人资料（登录态）----
async def update_profile(
    db: AsyncSession, user: User, payload: UpdateProfileRequest
) -> UserProfile:
    # 仅更新本次提交的字段：未提交的字段保持原值，显式空串已在 schema 归一化为 None（清空）
    fields = payload.model_dump(exclude_unset=True)
    phone = fields.get("phone")
    if isinstance(phone, str):
        owner = await UserRepository.get_by_phone(db, phone)
        if owner is not None and owner.id != user.id:
            raise BusinessError(
                ErrorCode.PARAM_INVALID,
                data={"fields": [{"field": "phone", "error": "手机号已被注册"}]},
            )
    if fields:
        await UserRepository.update_profile(db, user.id, fields)
        await db.commit()
        await db.refresh(user)
        logger.info("auth.profile.update", user_no=user.user_no, fields=sorted(fields))
    return await get_profile(db, user)


# ---- A11 上传头像（登录态）----
async def set_avatar(
    db: AsyncSession,
    user: User,
    *,
    content: bytes,
    filename: str,
    content_type: str | None,
) -> UserProfile:
    if not content:
        raise BusinessError(ErrorCode.PARAM_INVALID, "头像文件为空")
    if len(content) > AVATAR_MAX_BYTES:
        limit_mb = AVATAR_MAX_BYTES // (1024 * 1024)
        raise BusinessError(ErrorCode.PARAM_INVALID, f"头像超过大小上限（{limit_mb}MB）")
    if content_type not in settings.ALLOWED_IMAGE_TYPES and (
        Path(filename).suffix.lower() not in AVATAR_SUFFIXES
    ):
        raise BusinessError(ErrorCode.PARAM_INVALID, "仅支持 jpg/jpeg/png/webp 格式")

    old_ref = user.avatar_ref
    ref = image_storage.save_avatar(user.user_no, content, filename, content_type)
    if old_ref and old_ref != ref:
        # 扩展名变化时新旧文件不同路径，需显式删除旧图，避免残留孤儿文件
        image_storage.delete_ref(old_ref)
    await UserRepository.update_avatar_ref(db, user.id, ref)
    await db.commit()
    await db.refresh(user)
    logger.info("auth.avatar.update", user_no=user.user_no)
    return await get_profile(db, user)