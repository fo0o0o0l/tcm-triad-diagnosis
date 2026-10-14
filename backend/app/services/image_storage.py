"""图像存储（M2 舌诊 / M3 面诊）。

开发期落本地磁盘（`settings.MEDIA_ROOT`），对外统一使用 `img://` 引用，
避免业务层耦合具体后端；生产环境按同接口切换 S3/MinIO 即可。

目录结构：`{MEDIA_ROOT}/{module}/{record_no}/{filename}`
引用格式：`img://{module}/{record_no}/{filename}`

`module` 为资源归属标识（`tongue` / `face` / `avatar`），默认 `tongue` 以兼容既有调用。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

_REF_PREFIX = "img://"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SUPPORTED_MODULES = {"tongue", "face", "avatar"}


def media_root() -> Path:
    """媒体根目录（相对进程工作目录，必要时自动创建）。"""
    root = Path(settings.MEDIA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ext_of(filename: str, content_type: str | None) -> str:
    """由文件名后缀推断扩展名；缺失时按 MIME 兜底。"""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "webp"}:
        return suffix
    return {"image/png": "png", "image/webp": "webp"}.get(content_type or "", "jpg")


def _check_module(module: str) -> str:
    if module not in _SUPPORTED_MODULES:
        raise ValueError("不支持的诊位")
    return module


def save_raw_image(
    record_no: str,
    content: bytes,
    filename: str,
    content_type: str | None,
    *,
    module: str = "tongue",
) -> str:
    """保存原始采集图像，返回 `img://` 引用。

    同一记录固定使用 `raw.{ext}`，重复采集时**覆盖**同一路径，不产生多余文件；
    浏览器侧的旧图缓存由媒体接口的 `Cache-Control: no-store` 处理。
    """
    ext = _ext_of(filename, content_type)
    return _write(f"{_check_module(module)}/{record_no}", f"raw.{ext}", content)


def save_mask(record_no: str, content: bytes, *, module: str = "tongue") -> str:
    """保存舌体掩膜（PNG），返回 `img://` 引用。"""
    return _write(f"{_check_module(module)}/{record_no}", "mask.png", content)


def save_avatar(user_no: str, content: bytes, filename: str, content_type: str | None) -> str:
    """保存用户头像，返回 `img://` 引用。

    固定使用 `avatar.{ext}`：同一用户重复上传覆盖同一路径，不产生多余文件；
    扩展名变化时新旧路径不同，由调用方负责删除旧引用。
    """
    ext = _ext_of(filename, content_type)
    return _write(f"avatar/{user_no}", f"avatar.{ext}", content)


def _write(rel_dir: str, filename: str, content: bytes) -> str:
    target_dir = media_root() / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_bytes(content)
    return f"{_REF_PREFIX}{rel_dir}/{filename}"


def resolve(record_no: str, filename: str, *, module: str = "tongue") -> Path:
    """把 `(record_no, filename)` 解析为磁盘路径；越权/非法命名抛 `ValueError`。"""
    safe_module = _check_module(module)
    if not _SAFE_SEGMENT.match(record_no) or not _SAFE_SEGMENT.match(filename):
        raise ValueError("非法的资源路径")
    path = (media_root() / safe_module / record_no / filename).resolve()
    root = media_root().resolve()
    if root not in path.parents:
        raise ValueError("非法的资源路径")
    return path


def read_ref(ref: str) -> bytes:
    """按 `img://` 引用读取文件字节；非法或不存在抛 `ValueError`。"""
    path = _path_of_ref(ref)
    if not path.is_file():
        raise ValueError("资源不存在")
    return path.read_bytes()


def delete_ref(ref: str) -> None:
    """删除 `img://` 引用对应的文件；引用非法或文件不存在时静默忽略。"""
    try:
        path = _path_of_ref(ref)
    except ValueError:
        return
    path.unlink(missing_ok=True)


def _path_of_ref(ref: str) -> Path:
    """把 `img://{module}/{record_no}/{filename}` 解析为磁盘路径。"""
    if not ref.startswith(_REF_PREFIX):
        raise ValueError("非法的资源引用")
    parts = ref[len(_REF_PREFIX) :].split("/")
    if len(parts) != 3 or parts[0] not in _SUPPORTED_MODULES:
        raise ValueError("非法的资源引用")
    return resolve(parts[1], parts[2], module=parts[0])