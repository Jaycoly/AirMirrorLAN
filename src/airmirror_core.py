"""Core process and configuration helpers for AirMirrorLAN."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


APP_NAME = "AirMirrorLAN"
APP_VERSION = "0.4.0"
FIREWALL_RULE_NAME = "AirMirrorLAN (UxPlay)"
QUICKSHARE_FIREWALL_RULE_NAME = "AirMirrorLAN (Quick Share)"
QUICKSHARE_PORT = 8788


@dataclass
class ReceiverConfig:
    receiver_name: str = "AirMirrorLAN"
    require_pin: bool = True
    fixed_pin: str = ""
    record_sessions: bool = False
    high_resolution: bool = True
    share_folder: str = ""
    display_mode: str = "fit"


def config_dir() -> Path:
    override = os.environ.get("AIRMIRROR_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "AirMirrorLAN-v0.4"


def config_path() -> Path:
    return config_dir() / "config.json"


def recordings_dir() -> Path:
    videos = Path(os.environ.get("USERPROFILE", Path.home())) / "Videos"
    return videos / "AirMirrorLAN-v0.4"


def quickshare_default_dir() -> Path:
    profile = Path(os.environ.get("USERPROFILE", Path.home()))
    return profile / "Downloads" / "AirMirrorLAN-v0.4-Share"


def load_config(path: Path | None = None) -> ReceiverConfig:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {field for field in ReceiverConfig.__dataclass_fields__}
        return ReceiverConfig(**{key: value for key, value in raw.items() if key in allowed})
    except (OSError, ValueError, TypeError):
        return ReceiverConfig()


def save_config(config: ReceiverConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def uxplay_candidates(app_dir: Path | None = None) -> Iterable[Path]:
    app_dir = app_dir or application_dir()
    configured = os.environ.get("UXPLAY_PATH")
    if configured:
        yield Path(configured)
    yield app_dir / "runtime" / "bin" / "uxplay.exe"
    yield app_dir / "uxplay.exe"
    yield Path(r"C:\msys64\ucrt64\bin\uxplay.exe")
    yield Path(r"C:\msys64\mingw64\bin\uxplay.exe")


def find_uxplay(app_dir: Path | None = None) -> Path | None:
    for candidate in uxplay_candidates(app_dir):
        if candidate.is_file():
            return candidate.resolve()
    return None


def validate_receiver_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("接收器名称不能为空。")
    if len(value) > 64:
        raise ValueError("接收器名称不能超过 64 个字符。")
    if any(ord(char) < 32 for char in value):
        raise ValueError("接收器名称不能包含控制字符。")
    return value


def validate_fixed_pin(value: str) -> str:
    value = value.strip()
    if value and not re.fullmatch(r"\d{4}", value):
        raise ValueError("固定 PIN 必须恰好是 4 位数字；留空则每次随机生成。")
    return value


def validate_display_mode(value: str) -> str:
    if value not in {"fit", "stretch"}:
        raise ValueError("窗口显示方式必须是 fit 或 stretch。")
    return value


def build_uxplay_command(
    uxplay_path: Path,
    config: ReceiverConfig,
    record_dir: Path | None = None,
) -> list[str]:
    receiver_name = validate_receiver_name(config.receiver_name)
    fixed_pin = validate_fixed_pin(config.fixed_pin)
    display_mode = validate_display_mode(config.display_mode)
    video_sink = "d3d11videosink"
    if display_mode == "stretch":
        video_sink += (
            " force-aspect-ratio=false"
            " fullscreen-toggle-mode=GST_D3D11_WINDOW_FULLSCREEN_TOGGLE_MODE_ALT_ENTER"
        )
    args = [
        str(uxplay_path),
        "-n",
        receiver_name,
        "-nh",
        "-nohold",
        "-vs",
        video_sink,
        "-as",
        "wasapisink",
    ]
    if config.require_pin:
        args.append("-pin")
        if fixed_pin:
            args.append(fixed_pin)
    if config.high_resolution:
        args.extend(["-h265", "-s", "3840x2160", "-fps", "30"])
    if config.record_sessions:
        target = record_dir or recordings_dir()
        target.mkdir(parents=True, exist_ok=True)
        args.extend(["-mp4", str(target / "AirMirror")])
    return args


def runtime_environment(uxplay_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    runtime_bin = str(uxplay_path.parent)
    environment["PATH"] = runtime_bin + os.pathsep + environment.get("PATH", "")
    environment["LANG"] = "zh_CN.UTF-8"
    lan_address = preferred_ipv4()
    if lan_address:
        environment["UXPLAY_MDNS_IPV4"] = lan_address
    else:
        environment.pop("UXPLAY_MDNS_IPV4", None)
    return environment


def preferred_ipv4() -> str | None:
    """Return the IPv4 selected by the default route without sending data."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("1.1.1.1", 53))
        address = probe.getsockname()[0]
        if address and not address.startswith("127.") and not address.startswith("169.254."):
            return address
    except OSError:
        return None
    finally:
        probe.close()
    return None


def powershell(command: str, timeout: int = 8) -> str:
    completed = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = (completed.stdout + completed.stderr).strip()
    return output or "（无输出）"


def diagnostics(uxplay_path: Path | None) -> str:
    lines = [f"{APP_NAME} {APP_VERSION}", f"Windows: {sys.getwindowsversion() if os.name == 'nt' else sys.platform}"]
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
        lines.append("本机 IPv4: " + (", ".join(addresses) if addresses else "未找到"))
    except OSError as error:
        lines.append(f"本机 IPv4: 检测失败（{error}）")
    lines.append(f"AirPlay 广播 IPv4: {preferred_ipv4() or '未找到默认路由地址'}")

    if uxplay_path:
        lines.append(f"UxPlay: {uxplay_path}")
        gst_inspect = uxplay_path.parent / "gst-inspect-1.0.exe"
        lines.append(f"GStreamer: {'已找到' if gst_inspect.is_file() else '缺失'}")
        if gst_inspect.is_file():
            for plugin in ("d3d11videosink", "avdec_h264", "wasapisink"):
                result = subprocess.run(
                    [str(gst_inspect), plugin],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    env=runtime_environment(uxplay_path),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                lines.append(f"插件 {plugin}: {'正常' if result.returncode == 0 else '不可用'}")
    else:
        lines.append("UxPlay: 未安装")

    if os.name == "nt":
        profiles = powershell(
            "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory,IPv4Connectivity | Format-Table -AutoSize | Out-String"
        )
        lines.extend(["", "网络配置：", profiles])
        firewall = powershell(
            f"Get-NetFirewallRule -DisplayName '{FIREWALL_RULE_NAME}','{QUICKSHARE_FIREWALL_RULE_NAME}' "
            "-ErrorAction SilentlyContinue | "
            "Select-Object DisplayName,Enabled,Profile,Direction,Action | Format-Table -AutoSize | Out-String"
        )
        lines.extend(["", "防火墙规则：", firewall])

    lines.extend(
        [
            "",
            "检查提示：电脑网络应为“专用”，iPhone 与电脑应连接同一局域网，路由器不应开启 AP/客户端隔离。",
        ]
    )
    return "\n".join(lines)
