"""认证接口（《开发任务文档》§4.3 A1~A11）。"""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ErrorCode
from app.core.response import BusinessError, success
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SendCodeRequest,
    UpdateProfileRequest,
)
from app.services import auth as auth_service
from app.services import image_storage

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _device_info(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/register", summary="A1 注册")
async def register(payload: RegisterRequest, db: DbSession) -> dict:
    return success((await auth_service.register(db, payload)).model_dump(mode="json"))


@router.post("/login", summary="A2 登录")
async def login(payload: LoginRequest, request: Request, db: DbSession) -> dict:
    result = await auth_service.login(
        db, payload, device_info=_device_info(request), ip=_client_ip(request)
    )
    return success(result.model_dump(mode="json"))


@router.post("/refresh", summary="A3 刷新令牌")
async def refresh(payload: RefreshRequest, request: Request, db: DbSession) -> dict:
    result = await auth_service.refresh(
        db, payload, device_info=_device_info(request), ip=_client_ip(request)
    )
    return success(result.model_dump(mode="json"))


@router.post("/logout", summary="A4 登出")
async def logout(payload: LogoutRequest, db: DbSession) -> dict:
    return success((await auth_service.logout(db, payload)).model_dump(mode="json"))


@router.get("/me", summary="A5 当前用户信息")
async def me(current_user: CurrentUser, db: DbSession) -> dict:
    return success((await auth_service.get_profile(db, current_user)).model_dump(mode="json"))


@router.post("/verify-code", summary="A6 发送验证码")
async def send_verify_code(payload: SendCodeRequest, db: DbSession) -> dict:
    return success((await auth_service.send_verification_code(db, payload)).model_dump(mode="json"))


@router.post("/password/forgot", summary="A7 发起找回")
async def forgot_password(payload: ForgotRequest, db: DbSession) -> dict:
    return success((await auth_service.forgot_password(db, payload)).model_dump(mode="json"))


@router.post("/password/reset", summary="A8 重置密码")
async def reset_password(payload: ResetPasswordRequest, db: DbSession) -> dict:
    return success((await auth_service.reset_password(db, payload)).model_dump(mode="json"))


@router.post("/password/change", summary="A9 修改密码（登录态）")
async def change_password(
    payload: ChangePasswordRequest, current_user: CurrentUser, db: DbSession
) -> dict:
    return success((await auth_service.change_password(db, current_user, payload)).model_dump(mode="json"))


@router.patch("/me", summary="A10 更新个人资料（登录态）")
async def update_me(
    payload: UpdateProfileRequest, current_user: CurrentUser, db: DbSession
) -> dict:
    profile = await auth_service.update_profile(db, current_user, payload)
    return success(profile.model_dump(mode="json"))


@router.post("/avatar", summary="A11 上传头像（登录态）")
async def upload_avatar(
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(..., description="jpg/jpeg/png/webp，≤5MB"),
) -> dict:
    content = await file.read()
    profile = await auth_service.set_avatar(
        db,
        current_user,
        content=content,
        filename=file.filename or "avatar.jpg",
        content_type=file.content_type,
    )
    return success(profile.model_dump(mode="json"))


# ---- 头像读取（开发期免签；生产改为临时签名 URL）----
@router.get("/avatar/media/{user_no}/{filename}", summary="读取用户头像")
async def get_avatar_media(user_no: str, filename: str) -> FileResponse:
    try:
        path = image_storage.resolve(user_no, filename, module="avatar")
    except ValueError as exc:
        raise BusinessError(ErrorCode.NOT_FOUND, "资源不存在") from exc
    if not path.is_file():
        raise BusinessError(ErrorCode.NOT_FOUND, "资源不存在")
    # 头像固定同路径覆盖，必须禁用缓存，否则更换头像后浏览器仍显示旧图
    return FileResponse(path, headers={"Cache-Control": "no-store"})