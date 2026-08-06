"""Tk based Windows front-end for the UxPlay AirPlay receiver."""

from __future__ import annotations

import ctypes
import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from airmirror_core import (
    APP_NAME,
    APP_VERSION,
    FIREWALL_RULE_NAME,
    QUICKSHARE_FIREWALL_RULE_NAME,
    QUICKSHARE_PORT,
    ReceiverConfig,
    build_uxplay_command,
    diagnostics,
    find_uxplay,
    load_config,
    preferred_ipv4,
    quickshare_default_dir,
    recordings_dir,
    runtime_environment,
    save_config,
    validate_fixed_pin,
    validate_display_mode,
    validate_receiver_name,
)
from quickshare import QuickShareServer


BG = "#F4F6F8"
CARD = "#FFFFFF"
TEXT = "#17202A"
MUTED = "#65717E"
BLUE = "#1976D2"
GREEN = "#1B8A5A"
RED = "#C43D3D"
DISPLAY_MODE_LABELS = {
    "保持完整手机画面": "fit",
    "强制拉伸到窗口": "stretch",
}


class AirMirrorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("880x860")
        self.minsize(760, 740)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.process: subprocess.Popen[str] | None = None
        self.quickshare: QuickShareServer | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.uxplay_path = find_uxplay()
        self.config_data = load_config()

        self.receiver_name = tk.StringVar(value=self.config_data.receiver_name)
        self.require_pin = tk.BooleanVar(value=self.config_data.require_pin)
        self.fixed_pin = tk.StringVar(value=self.config_data.fixed_pin)
        self.record_sessions = tk.BooleanVar(value=self.config_data.record_sessions)
        self.high_resolution = tk.BooleanVar(value=self.config_data.high_resolution)
        current_display_label = next(
            (label for label, value in DISPLAY_MODE_LABELS.items() if value == self.config_data.display_mode),
            "保持完整手机画面",
        )
        self.display_mode = tk.StringVar(value=current_display_label)
        share_folder = self.config_data.share_folder or str(quickshare_default_dir())
        self.share_folder = tk.StringVar(value=share_folder)
        self.status_text = tk.StringVar(value="已停止")
        self.runtime_text = tk.StringVar()
        self.share_status_text = tk.StringVar(value="快传已停止")
        self.share_url_text = tk.StringVar(value="启动后会显示供 iPhone Safari 打开的地址")
        self.share_access_text = tk.StringVar(value="访问码：------")

        self._configure_styles()
        self._build_ui()
        self._refresh_runtime_text()
        self._toggle_pin_entry()
        self.after(100, self._drain_log_queue)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", background=CARD, foreground=GREEN, font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(22, 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(10, 6))
        style.configure("TCheckbutton", background=CARD, font=("Microsoft YaHei UI", 10))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="让 iPhone 通过同一局域网镜像到这台 Windows 电脑",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        status_card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        status_card.pack(fill="x")
        status_row = ttk.Frame(status_card, style="Card.TFrame")
        status_row.pack(fill="x")
        ttk.Label(status_row, textvariable=self.status_text, style="Status.TLabel").pack(side="left")
        self.start_button = ttk.Button(status_row, text="启动接收", style="Primary.TButton", command=self.toggle_receiver)
        self.start_button.pack(side="right")
        ttk.Label(status_card, textvariable=self.runtime_text, style="Card.TLabel", foreground=MUTED).pack(
            anchor="w", pady=(8, 0)
        )

        settings = ttk.Frame(outer, style="Card.TFrame", padding=18)
        settings.pack(fill="x", pady=(14, 0))
        ttk.Label(settings, text="接收设置", style="Card.TLabel", font=("Microsoft YaHei UI", 12, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12)
        )
        ttk.Label(settings, text="iPhone 中显示的名称", style="Card.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.receiver_name, width=30).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(14, 0))

        pin_check = ttk.Checkbutton(
            settings,
            text="要求 PIN 验证",
            variable=self.require_pin,
            command=self._toggle_pin_entry,
        )
        pin_check.grid(row=2, column=0, sticky="w", pady=(14, 0))
        ttk.Label(settings, text="固定 PIN（可留空）", style="Card.TLabel").grid(row=2, column=1, sticky="e", pady=(14, 0))
        self.pin_entry = ttk.Entry(settings, textvariable=self.fixed_pin, width=9, show="•")
        self.pin_entry.grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(14, 0))
        ttk.Checkbutton(settings, text="录制为 MP4", variable=self.record_sessions).grid(
            row=2, column=3, sticky="e", pady=(14, 0)
        )
        ttk.Checkbutton(
            settings,
            text="高清阅读模式（4K/HEVC，30 fps）",
            variable=self.high_resolution,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Label(settings, text="窗口显示方式", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Combobox(
            settings,
            textvariable=self.display_mode,
            values=tuple(DISPLAY_MODE_LABELS),
            state="readonly",
            width=24,
        ).grid(row=4, column=1, columnspan=3, sticky="w", padx=(14, 0), pady=(12, 0))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        share_card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        share_card.pack(fill="x", pady=(14, 0))
        ttk.Label(share_card, text="局域网快传", style="Card.TLabel", font=("Microsoft YaHei UI", 12, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        ttk.Label(
            share_card,
            text="iPhone 用 Safari 打开地址，即可上传、浏览和下载所选文件夹中的文件",
            style="Card.TLabel",
            foreground=MUTED,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(3, 12))
        ttk.Entry(share_card, textvariable=self.share_folder, state="readonly").grid(
            row=2, column=0, columnspan=3, sticky="ew"
        )
        ttk.Button(share_card, text="选择文件夹", command=self.select_share_folder).grid(
            row=2, column=3, sticky="e", padx=(10, 0)
        )
        ttk.Label(share_card, textvariable=self.share_status_text, style="Card.TLabel", foreground=GREEN).grid(
            row=3, column=0, sticky="w", pady=(12, 0)
        )
        self.quickshare_button = ttk.Button(share_card, text="启动快传", command=self.toggle_quickshare)
        self.quickshare_button.grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(12, 0))
        ttk.Button(share_card, text="复制地址", command=self.copy_share_url).grid(
            row=3, column=2, sticky="e", pady=(12, 0)
        )
        ttk.Button(share_card, text="打开文件夹", command=self.open_share_folder).grid(
            row=3, column=3, sticky="e", padx=(10, 0), pady=(12, 0)
        )
        ttk.Label(
            share_card,
            textvariable=self.share_url_text,
            style="Card.TLabel",
            foreground=BLUE,
            wraplength=790,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(
            share_card,
            textvariable=self.share_access_text,
            style="Card.TLabel",
            foreground=RED,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).grid(row=4, column=3, sticky="e", padx=(10, 0), pady=(10, 0))
        share_card.columnconfigure(0, weight=1)
        share_card.columnconfigure(2, weight=1)

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(12, 10))
        ttk.Button(action_row, text="配置防火墙（镜像+快传）", command=self.configure_firewall).pack(side="left")
        ttk.Button(action_row, text="运行诊断", command=self.show_diagnostics).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="打开录制目录", command=self.open_recordings).pack(side="left", padx=(8, 0))
        ttk.Label(action_row, text="投屏窗口按 Alt+Enter 切换全屏", style="Sub.TLabel").pack(side="right")

        ttk.Label(outer, text="运行日志", style="Sub.TLabel").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(
            outer,
            height=9,
            wrap="word",
            bg="#101820",
            fg="#DAE3EA",
            insertbackground="#FFFFFF",
            relief="flat",
            font=("Consolas", 9),
            padx=10,
            pady=8,
            state="disabled",
        )
        self.log.pack(fill="both", expand=True, pady=(5, 0))
        self._append_log("准备就绪。首次使用请点击“配置防火墙”。镜像与快传可以同时运行。\n")

    def _refresh_runtime_text(self) -> None:
        if self.uxplay_path:
            broadcast_ip = preferred_ipv4() or "未找到"
            self.runtime_text.set(f"接收核心已就绪；AirPlay 广播网卡：{broadcast_ip}")
        else:
            self.runtime_text.set("接收核心未安装；请先运行 scripts\\setup-runtime.ps1")

    def _toggle_pin_entry(self) -> None:
        self.pin_entry.configure(state="normal" if self.require_pin.get() else "disabled")

    def current_config(self) -> ReceiverConfig:
        return ReceiverConfig(
            receiver_name=validate_receiver_name(self.receiver_name.get()),
            require_pin=self.require_pin.get(),
            fixed_pin=validate_fixed_pin(self.fixed_pin.get()),
            record_sessions=self.record_sessions.get(),
            high_resolution=self.high_resolution.get(),
            share_folder=self.share_folder.get(),
            display_mode=validate_display_mode(DISPLAY_MODE_LABELS.get(self.display_mode.get(), "fit")),
        )

    def toggle_receiver(self) -> None:
        if self.process and self.process.poll() is None:
            self.stop_receiver()
        else:
            self.start_receiver()

    def start_receiver(self) -> None:
        self.uxplay_path = find_uxplay()
        if not self.uxplay_path:
            self._refresh_runtime_text()
            messagebox.showerror("缺少接收核心", "没有找到 uxplay.exe。请先以 PowerShell 运行 scripts\\setup-runtime.ps1。")
            return
        try:
            config = self.current_config()
            save_config(config)
            work_dir = recordings_dir()
            work_dir.mkdir(parents=True, exist_ok=True)
            command = build_uxplay_command(self.uxplay_path, config, work_dir)
        except (OSError, ValueError) as error:
            messagebox.showerror("设置无效", str(error))
            return

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        environment = runtime_environment(self.uxplay_path)
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
                cwd=str(work_dir),
                creationflags=flags,
            )
        except OSError as error:
            self.process = None
            messagebox.showerror("启动失败", f"无法启动 UxPlay：\n{error}")
            return

        self.status_text.set("正在启动…")
        self.start_button.configure(text="停止接收")
        self._append_log("\n> " + subprocess.list2cmdline(command) + "\n")
        self._append_log(f"AirPlay mDNS 广播网卡：{environment.get('UXPLAY_MDNS_IPV4', '自动选择')}\n")
        self._append_log(
            "镜像质量：" + ("高清阅读模式 3840×2160 / HEVC（支持 H.264 回退）" if config.high_resolution else "兼容模式 1920×1080 / H.264") + "\n"
        )
        display_description = {
            "fit": "保持完整手机画面",
            "stretch": "强制拉伸到窗口（可能改变文字宽高比例）",
        }[config.display_mode]
        self._append_log(f"窗口显示：{display_description}\n")
        threading.Thread(target=self._read_process_output, daemon=True).start()
        self.after(1200, self._confirm_started)

    def _confirm_started(self) -> None:
        if self.process and self.process.poll() is None:
            self.status_text.set("等待 iPhone 连接")
            self._append_log("接收器已启动。请在 iPhone 控制中心选择“屏幕镜像”。\n")
        elif self.process:
            self._process_finished(self.process.returncode)

    def _read_process_output(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for line in process.stdout:
            self.log_queue.put(line)
            lowered = line.lower()
            if "connection" in lowered or "client" in lowered or "mirroring" in lowered:
                self.log_queue.put("@@STATUS_CONNECTED@@")
        return_code = process.wait()
        self.log_queue.put(f"@@PROCESS_EXIT:{return_code}@@")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == "@@STATUS_CONNECTED@@":
                    self.status_text.set("iPhone 已连接")
                elif item.startswith("@@PROCESS_EXIT:"):
                    code = int(item.split(":", 1)[1].split("@@", 1)[0])
                    self._process_finished(code)
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _process_finished(self, return_code: int | None) -> None:
        self.process = None
        self.status_text.set("已停止")
        self.start_button.configure(text="启动接收")
        self._append_log(f"接收进程已退出（代码 {return_code}）。\n")

    def stop_receiver(self) -> None:
        process = self.process
        if not process or process.poll() is not None:
            self._process_finished(process.returncode if process else None)
            return
        self.status_text.set("正在停止…")
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        self._process_finished(process.returncode)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def select_share_folder(self) -> None:
        if self.quickshare and self.quickshare.running:
            messagebox.showinfo("快传正在运行", "请先停止快传，再更换共享文件夹。")
            return
        initial = Path(self.share_folder.get()).expanduser()
        if not initial.is_dir():
            initial = quickshare_default_dir().parent
        selected = filedialog.askdirectory(title="选择用于 iPhone 快传的文件夹", initialdir=str(initial))
        if selected:
            self.share_folder.set(str(Path(selected).resolve()))
            try:
                save_config(self.current_config())
            except (OSError, ValueError):
                pass

    def toggle_quickshare(self) -> None:
        if self.quickshare and self.quickshare.running:
            self.stop_quickshare()
        else:
            self.start_quickshare()

    def start_quickshare(self) -> None:
        host = preferred_ipv4()
        if not host:
            messagebox.showerror("无法启动快传", "没有找到当前局域网 IPv4 地址。请先连接 WLAN 或网线。")
            return
        try:
            folder = Path(self.share_folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if not folder.is_dir():
                raise ValueError("所选路径不是文件夹。")
            config = self.current_config()
            config.share_folder = str(folder)
            save_config(config)
            access_code = os.environ.get("AIRMIRROR_QUICKSHARE_CODE") or None
            if access_code and (len(access_code) != 6 or not access_code.isdigit()):
                raise ValueError("预设快传访问码必须是 6 位数字。")
            server = QuickShareServer(
                folder,
                host,
                QUICKSHARE_PORT,
                log_callback=lambda message: self.log_queue.put(message + "\n"),
                token=access_code,
            )
            server.start()
        except (OSError, ValueError) as error:
            messagebox.showerror("无法启动快传", f"{error}\n\n若端口被占用，可关闭其他快传程序后重试。")
            return
        self.quickshare = server
        self.share_folder.set(str(folder))
        self.share_status_text.set("快传正在运行")
        self.share_url_text.set(server.url)
        self.share_access_text.set(f"访问码：{server.access_code}")
        self.quickshare_button.configure(text="停止快传")
        self._append_log(f"快传已启动：{server.url}\n共享文件夹：{folder}\n")

    def stop_quickshare(self) -> None:
        server = self.quickshare
        self.quickshare = None
        if server:
            server.stop()
        self.share_status_text.set("快传已停止")
        self.share_url_text.set("启动后会显示供 iPhone Safari 打开的地址")
        self.share_access_text.set("访问码：------")
        self.quickshare_button.configure(text="启动快传")
        self._append_log("快传已停止。\n")

    def copy_share_url(self) -> None:
        if not self.quickshare or not self.quickshare.running:
            messagebox.showinfo("快传未启动", "请先启动快传。")
            return
        self.clipboard_clear()
        self.clipboard_append(self.quickshare.url)
        self.update_idletasks()
        self._append_log("快传地址已复制到剪贴板。\n")

    def open_share_folder(self) -> None:
        try:
            target = Path(self.share_folder.get()).expanduser().resolve()
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(target)
        except OSError as error:
            messagebox.showerror("无法打开文件夹", str(error))

    def configure_firewall(self) -> None:
        self.uxplay_path = find_uxplay()
        if not self.uxplay_path:
            messagebox.showerror("缺少接收核心", "请先安装 UxPlay 运行环境。")
            return
        path = str(self.uxplay_path).replace("'", "''")
        name = FIREWALL_RULE_NAME.replace("'", "''")
        share_path = str(Path(sys.executable).resolve()).replace("'", "''")
        share_name = QUICKSHARE_FIREWALL_RULE_NAME.replace("'", "''")
        script = (
            f"$n='{name}';$p='{path}';$sn='{share_name}';$sp='{share_path}';"
            "$old=Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue;if($old){$old|Remove-NetFirewallRule};"
            "$sold=Get-NetFirewallRule -DisplayName $sn -ErrorAction SilentlyContinue;if($sold){$sold|Remove-NetFirewallRule};"
            "New-NetFirewallRule -DisplayName $n -Direction Inbound -Program $p -Action Allow -Profile Private -Protocol Any | Out-Null;"
            f"New-NetFirewallRule -DisplayName $sn -Direction Inbound -Program $sp -Action Allow -Profile Private "
            f"-Protocol TCP -LocalPort {QUICKSHARE_PORT} -RemoteAddress LocalSubnet | Out-Null"
        )
        parameters = subprocess.list2cmdline(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", parameters, None, 1)
        if result <= 32:
            messagebox.showerror("配置失败", "没有获得管理员权限，或无法启动 PowerShell。")
        else:
            self._append_log("已请求管理员权限配置镜像与快传的专用网络防火墙规则。\n")
            messagebox.showinfo("防火墙", "已提交防火墙配置。若出现系统提示，请选择“是”。")

    def show_diagnostics(self) -> None:
        self.uxplay_path = find_uxplay()
        report = diagnostics(self.uxplay_path)
        window = tk.Toplevel(self)
        window.title(f"{APP_NAME} 诊断")
        window.geometry("760x560")
        text = scrolledtext.ScrolledText(window, wrap="word", font=("Consolas", 9), padx=10, pady=10)
        text.pack(fill="both", expand=True)
        text.insert("1.0", report)
        text.configure(state="disabled")

    def open_recordings(self) -> None:
        target = recordings_dir()
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(target)

    def on_close(self) -> None:
        try:
            save_config(self.current_config())
        except (OSError, ValueError):
            pass
        if self.process and self.process.poll() is None:
            self.stop_receiver()
        if self.quickshare and self.quickshare.running:
            self.stop_quickshare()
        self.destroy()


if __name__ == "__main__":
    application = AirMirrorApp()
    if "--no-autostart" not in sys.argv:
        application.after(500, application.start_receiver)
    if "--start-quickshare" in sys.argv:
        application.after(700, application.start_quickshare)
    application.mainloop()
