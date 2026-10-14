"""三诊合一分析系统一键启动入口（单文件 main）。

用法：
    python run.py              # 启动后端 + 算法服务 + 前端（含可选 MailHog）
    python run.py --no-mailhog # 不启动 MailHog
    python run.py --no-algo    # 不启动算法服务（AI 分析将降级到本地规则 mock）
    python run.py --no-frontend
    python run.py --no-force   # 不清理占用端口的旧进程（默认会先清理，避免「端口已被占用」）

默认行为：启动前先结束占用 8000 / 8100 / 5173 的旧进程，并等端口真正释放后再启动，
因此重复运行本脚本不会再出现「端口已被占用 → 跳过启动」的情况（`--force` 仍可传，含义相同）。

按 Ctrl+C 可一键停止全部子进程。

启动完成后会打印各服务的访问网址（前端 5173 / 后端 8000 / 算法服务 8100 / MailHog 8025），
并自动用默认浏览器打开前端页面；若服务已在别处运行，则把后端 / 算法服务的日志文件内容
实时显示在当前终端（Ctrl+C 退出，--no-logs 可跳过），同样会展示网址并打开前端。

说明：
- 后端使用 backend/.venv 内的 Python 解释器（若不存在则回退到当前解释器）。
- 算法服务（algorithm-service，AI 大模型解读）优先使用其自带 .venv，不存在则复用
  backend/.venv；未配置 DASHSCOPE_API_KEY 时其后端会自动降级到规则 mock，不影响主链路。
- MailHog 复用 backend/docker-compose.yml 中的 mailhog 服务。仅在 Docker 守护
  进程「已就绪」时才调用 docker；探测使用命名管道而非 `docker info`，避免在
  Docker Desktop 尚未就绪时触发其读取自身日志（可能被运行环境沙箱拦截）。
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
ALGO_DIR = ROOT / "algorithm-service"

# 各服务端口
PORT_BACKEND = 8000
PORT_ALGO = 8100
PORT_FRONTEND = 5173
PORT_MAILHOG_UI = 8025

# MailHog 由项目自带的 compose 编排提供（见 backend/docker-compose.yml）
COMPOSE_FILE = BACKEND_DIR / "docker-compose.yml"
# Docker 守护进程探测目标：不启动 docker 可执行文件即可判断是否已就绪
DOCKER_PIPE = r"\\.\pipe\docker_engine"  # Windows 命名管道
DOCKER_SOCK = "/var/run/docker.sock"  # Linux / macOS unix socket


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检测端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def kill_port(port: int) -> list[str]:
    """强制结束占用指定端口的进程（含其子进程），返回被清理的进程描述列表。"""
    killed: list[str] = []
    if os.name != "nt":
        # 非 Windows：尝试 lsof + kill
        try:
            res = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-s", "TCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            )
            for pid in {x.strip() for x in res.stdout.split()}:
                if pid.isdigit():
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    killed.append(f"PID {pid}")
        except Exception:
            pass
        return killed

    # Windows：用 Get-NetTCPConnection 找出监听进程，再 taskkill /T 结束进程树
    ps_cmd = (
        f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess -Unique"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        pids = {int(x) for x in res.stdout.split() if x.strip().isdigit()}
    except Exception:
        pids = set()

    for pid in pids:
        if pid <= 0 or pid == os.getpid():
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
            killed.append(f"PID {pid}")
        except Exception:
            pass
    return killed


def tail_logs(targets: list[tuple[str, Path]], *, tail_lines: int = 20) -> None:
    """把各服务日志文件的新增内容实时打印到当前终端（Ctrl+C 退出）。

    用于服务已在别处运行时：本脚本不接管子进程，改为跟踪落盘日志，
    让「每次运行 run.py 都能在当前终端直接看到日志」。
    """
    print("\n实时显示日志（Ctrl+C 退出）...\n", flush=True)
    files: list[tuple[str, Any]] = []
    for name, path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        handle = path.open("r", encoding="utf-8", errors="replace")
        files.append((name, handle))
        # 先补最近若干行，避免只看到「此刻之后」的内容
        for line in handle.readlines()[-tail_lines:]:
            sys.stdout.write(f"[{name}] {line}")
    sys.stdout.flush()
    try:
        while True:
            printed = False
            for name, handle in files:
                line = handle.readline()
                if line:
                    sys.stdout.write(f"[{name}] {line}")
                    printed = True
            if printed:
                sys.stdout.flush()
            else:
                time.sleep(0.5)
    finally:
        for _, handle in files:
            handle.close()


def wait_port_free(port: int, timeout: float = 8.0, host: str = "127.0.0.1") -> bool:
    """等待端口真正释放，返回是否已空闲。

    仅 kill 进程后立刻复查会出现「进程已结束但端口仍被占用」的竞态（句柄尚未回收），
    故轮询等待，避免误判为「无法清理」而跳过启动。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_in_use(port):
            return True
        time.sleep(0.3)
    return not port_in_use(port)


def kill_leftovers_by_cmdline() -> list[str]:
    """兜底清理：按命令行匹配本项目的后端 / 算法服务进程。

    端口占用者有时是**已僵死的父进程**（其子进程仍持有监听套接字），
    此时按监听 PID 结束无效，需要按命令行把残留进程一并清掉。
    """
    if os.name != "nt":
        return []
    ps_cmd = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
        "($_.CommandLine -like '*app.main:app*' -or $_.CommandLine -like '*uvicorn*main:app*') } "
        "| Select-Object -ExpandProperty ProcessId"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=15,
        )
        pids = {int(x) for x in res.stdout.split() if x.strip().isdigit()}
    except Exception:
        pids = set()

    killed: list[str] = []
    for pid in pids:
        if pid <= 0 or pid == os.getpid():
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            killed.append(f"PID {pid}")
        except Exception:
            pass
    return killed


def backend_python() -> str:
    """返回后端应使用的 Python 解释器路径。"""
    venv_py = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    venv_py_unix = BACKEND_DIR / ".venv" / "bin" / "python"
    if venv_py_unix.exists():
        return str(venv_py_unix)
    return sys.executable


def algo_python() -> str:
    """返回算法服务应使用的 Python 解释器路径（优先自带 venv，回退后端 venv）。"""
    for base in (ALGO_DIR, BACKEND_DIR):
        venv_py = base / ".venv" / "Scripts" / "python.exe"
        if venv_py.exists():
            return str(venv_py)
        venv_py_unix = base / ".venv" / "bin" / "python"
        if venv_py_unix.exists():
            return str(venv_py_unix)
    return sys.executable


def stream_output(name: str, proc: subprocess.Popen[str]) -> None:
    """把子进程输出按前缀转发到当前终端。"""
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(f"[{name}] {line}")
        sys.stdout.flush()


def spawn(name: str, cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen[str] | None:
    print(f"[启动] {name} ...", flush=True)
    # Windows 下 .cmd/.bat（如 npm.cmd）无法直接由 CreateProcess 执行，需经 cmd.exe 包装
    if os.name == "nt" and cmd and cmd[0].lower().endswith((".cmd", ".bat")):
        cmd = ["cmd.exe", "/c", *cmd]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        print(f"[错误] {name} 启动失败：{exc}", flush=True)
        return None
    threading.Thread(target=stream_output, args=(name, proc), daemon=True).start()
    return proc


def find_mailhog_exe() -> str | None:
    """在 PATH 中查找独立 mailhog 可执行文件（不依赖 Docker）。"""
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        for candidate in ("mailhog.exe", "mailhog"):
            p = Path(path_dir) / candidate
            if p.exists():
                return str(p)
    return None


def docker_daemon_ready() -> bool:
    """探测 Docker 守护进程是否已就绪，且不启动 docker 可执行文件。

    直接执行 `docker info` 之类命令，在 Docker Desktop 未就绪时会触发其读取
    自身日志目录（如 AppData\\Local\\Docker\\log\\...），可能被运行环境沙箱
    拦截并连带中断其它服务；因此改为探测守护进程的监听端点（命名管道 /
    unix socket），只判断「是否已在监听」，不产生任何 docker 进程。
    """
    if os.name != "nt":
        return Path(DOCKER_SOCK).exists()
    # 注意：PowerShell 中 `exit ($true)` 的退出码是 1，故必须显式分支
    ps_cmd = f"if (Test-Path '{DOCKER_PIPE}') {{ exit 0 }} else {{ exit 1 }}"
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


def start_mailhog_via_docker() -> bool:
    """用项目自带的 compose 启动 mailhog 服务（幂等，复用 tcm-mailhog 容器）。"""
    try:
        res = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "mailhog"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except Exception as exc:
        print(f"[提示] MailHog：Docker 启动失败（{exc}）")
        return False
    if res.returncode != 0:
        output = (res.stderr or res.stdout or "").strip().splitlines()
        print(f"[提示] MailHog：compose 启动失败（{output[-1] if output else '未知错误'}）")
        return False
    return True


def _which(name: str) -> str | None:
    # Windows 上 Node 会同时提供无扩展名的 `npm`(bash 脚本) 与 `npm.cmd`，
    # 必须优先匹配可执行扩展名，否则会误选到无法执行的 bash 脚本。
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        for ext in (".cmd", ".exe", ".bat", ""):
            p = Path(path_dir) / (name + ext)
            if p.exists():
                return str(p)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="三诊合一分析系统一键启动")
    parser.add_argument("--no-mailhog", action="store_true", help="不启动 MailHog")
    parser.add_argument("--no-frontend", action="store_true", help="不启动前端")
    parser.add_argument("--no-backend", action="store_true", help="不启动后端")
    parser.add_argument(
        "--no-algo",
        action="store_true",
        help="不启动算法服务（AI 分析将降级到本地规则 mock）",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="启动前清理占用端口的旧进程（已是默认行为，保留以兼容旧用法）",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="不清理占用端口的旧进程（默认会先清理）",
    )
    parser.add_argument(
        "--no-logs",
        action="store_true",
        help="服务已在运行时，不在当前终端实时显示日志（默认显示）",
    )
    args = parser.parse_args()

    print("=" * 56)
    print("        三诊合一分析系统  一键启动")
    print("=" * 56)

    # 默认清理：先结束占用目标端口的旧进程，并等端口真正释放后再启动，
    # 避免出现「端口已被占用 → 跳过启动」。
    # 说明：MailHog 端口由 Docker 端口映射提供（监听者是 Docker 代理进程），
    # 强行 taskkill 会破坏 Docker 网络，故不纳入「清理」范围，只做探测与复用。
    if not args.no_force:
        targets: list[tuple[str, int]] = []
        if not args.no_backend:
            targets.append(("后端", PORT_BACKEND))
        if not args.no_algo:
            targets.append(("算法服务", PORT_ALGO))
        if not args.no_frontend:
            targets.append(("前端", PORT_FRONTEND))
        for name, port in targets:
            if not port_in_use(port):
                continue
            killed = kill_port(port)
            if killed:
                print(f"[清理] {name}：已结束占用端口 {port} 的进程 {', '.join(killed)}")
            if wait_port_free(port):
                continue
            # 端口仍未释放：占用者可能是僵死的父进程，改按命令行兜底清理一次
            leftovers = kill_leftovers_by_cmdline()
            if leftovers:
                print(f"[清理] {name}：兜底结束残留服务进程 {', '.join(leftovers)}")
            if wait_port_free(port, timeout=10):
                continue
            print(f"[警告] {name}：端口 {port} 仍被占用，将跳过启动")

    # (名称, 进程, 是否关键)：关键进程退出则整体停止；可选进程（MailHog）退出只提示
    procs: list[tuple[str, subprocess.Popen[str], bool]] = []
    # MailHog 以 compose 容器方式启动时不属于本进程子进程，单独记录以便打印状态
    mailhog_via_compose = False

    # 1. 后端 FastAPI
    if not args.no_backend:
        if port_in_use(PORT_BACKEND):
            print(f"[跳过] 后端：端口 {PORT_BACKEND} 已被占用")
        else:
            proc = spawn(
                "后端",
                [
                    backend_python(), "-m", "uvicorn", "app.main:app",
                    "--reload", "--port", str(PORT_BACKEND), "--host", "0.0.0.0",
                ],
                cwd=BACKEND_DIR,
            )
            if proc:
                procs.append(("后端", proc, True))

    # 2. 算法服务（AI 大模型解读，algorithm-service；非关键：异常仅降级，不中断全局）
    if not args.no_algo:
        if not ALGO_DIR.exists():
            print(f"[跳过] 算法服务：未找到 {ALGO_DIR.name} 目录")
        elif port_in_use(PORT_ALGO):
            print(f"[跳过] 算法服务：端口 {PORT_ALGO} 已被占用")
        else:
            proc = spawn(
                "算法服务",
                [
                    algo_python(), "-m", "uvicorn", "main:app",
                    "--reload", "--port", str(PORT_ALGO), "--host", "127.0.0.1",
                ],
                cwd=ALGO_DIR,
            )
            if proc:
                procs.append(("算法服务", proc, False))

    # 3. 前端 Vite
    if not args.no_frontend:
        if port_in_use(PORT_FRONTEND):
            print(f"[跳过] 前端：端口 {PORT_FRONTEND} 已被占用")
        else:
            npm = _which("npm")
            if npm:
                proc = spawn("前端", [npm, "run", "dev"], cwd=FRONTEND_DIR)
                if proc:
                    procs.append(("前端", proc, True))
            else:
                print("[错误] 前端：未找到 npm，请先安装 Node.js")

    # 4. MailHog（开发环境验证码镜像邮箱，可选；失败不影响主服务）
    #    由 backend/docker-compose.yml 的 mailhog 服务提供，复用 tcm-mailhog 容器
    if not args.no_mailhog:
        if port_in_use(PORT_MAILHOG_UI):
            print(f"[跳过] MailHog：端口 {PORT_MAILHOG_UI} 已被占用（已在运行）")
        else:
            mailhog_exe = find_mailhog_exe()
            if mailhog_exe:
                proc = spawn("MailHog", [mailhog_exe], cwd=ROOT)
                if proc:
                    procs.append(("MailHog", proc, False))
            elif docker_daemon_ready():
                print("[启动] MailHog ...（docker compose）", flush=True)
                if start_mailhog_via_docker():
                    print("[就绪] MailHog：tcm-mailhog 容器已启动", flush=True)
                    mailhog_via_compose = True
            else:
                compose_rel = COMPOSE_FILE.relative_to(ROOT)
                print("[提示] MailHog：未检测到 mailhog 可执行文件，且 Docker 守护进程未就绪，已跳过")
                print("        需要验证码邮箱时：先启动 Docker Desktop，再执行")
                print(f"        docker compose -f {compose_rel} up -d mailhog")
                print("        （验证码同样会打到后端日志）")

    if procs:
        # 就绪探活
        print("\n等待服务就绪 ...")
        time.sleep(5)
    else:
        print("\n检测到服务已在运行，无需重复启动，直接展示访问地址。")

    print("\n" + "=" * 56)
    print("        服务状态")
    print("=" * 56)
    endpoints = [
        ("后端 FastAPI", PORT_BACKEND, "http://localhost:8000/docs"),
        ("算法服务", PORT_ALGO, "http://localhost:8100/health"),
        ("前端 Vite", PORT_FRONTEND, "http://localhost:5173"),
        ("MailHog", PORT_MAILHOG_UI, "http://localhost:8025"),
    ]
    for name, port, url in endpoints:
        running = port_in_use(port)
        mark = "运行中" if running else "未启动"
        print(f"  {name:<14} 端口 {port:<6} {mark}")
        if running:
            # 网址单独一行、不加前后缀，便于终端识别为可点击链接
            print(url)
    print("=" * 56)

    # 日志落盘位置；服务已在别处运行时，默认在本终端实时显示这两份日志
    log_targets: list[tuple[str, Path]] = [
        ("后端", BACKEND_DIR / "logs" / "backend.log"),
        ("算法服务", ALGO_DIR / "logs" / "alg.log"),
    ]
    print("\n日志文件（可按住 Ctrl 点击路径；亦可自行跟踪：Get-Content <路径> -Tail 50 -Wait）")
    for log_name, log_path in log_targets:
        print(f"  {log_name:<10}{log_path}")

    # 主入口就是前端页面：就绪后自动用默认浏览器打开
    if not args.no_frontend and port_in_use(PORT_FRONTEND):
        frontend_url = "http://localhost:5173"
        print(f"前端主入口：{frontend_url}")
        try:
            if webbrowser.open(frontend_url):
                print("已自动在默认浏览器中打开前端页面。")
            else:
                print("未能自动打开浏览器，请手动访问上面的前端地址。")
        except Exception as exc:  # noqa: BLE001 - 打开浏览器失败不应中断启动
            print(f"自动打开浏览器失败（{exc}），请手动访问上面的前端地址。")
    else:
        print("提示：按住 Ctrl 并点击上面的网址即可在浏览器打开。")

    if not procs and not mailhog_via_compose:
        print("\n（以上服务已在别处运行，本脚本不启动新进程。）")
        if args.no_logs:
            print("（已跳过日志显示，退出。）")
            return 0
        # 不接管子进程时改为跟踪落盘日志，保证每次运行本脚本都能在当前终端看到日志
        try:
            tail_logs(log_targets)
        except KeyboardInterrupt:
            print("\n已停止日志显示。")
        return 0
    if not procs:
        # 仅以容器方式启动了 MailHog：容器自后台常驻，本脚本无子进程需要守护
        print("\n（MailHog 以容器方式在后台常驻运行，本脚本退出后仍可用。）")
        return 0
    print("\n按 Ctrl+C 停止全部服务。\n")

    # 主循环：关键进程退出则停止全部；可选进程退出仅提示
    reported: set[str] = set()

    def stop_all() -> None:
        for _, proc, _ in procs:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        for _, proc, _ in procs:
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    try:
        while True:
            time.sleep(1)
            for name, proc, critical in procs:
                if proc.poll() is None or name in reported:
                    continue
                reported.add(name)
                if critical:
                    print(f"\n[退出] {name} 已结束（退出码 {proc.returncode}），停止全部服务")
                    stop_all()
                    return 1
                print(f"[提示] {name} 已结束（退出码 {proc.returncode}），不影响主服务，继续运行")
    except KeyboardInterrupt:
        print("\n\n正在停止全部服务 ...")
        stop_all()
        print("已全部停止。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
