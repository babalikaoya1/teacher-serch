"""可双击的 Windows 助手，界面线程与串行采集线程分离。"""
import argparse
import json
import platform
import queue
import threading
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse

import httpx

from storage import Outbox, data_home, load_binding, save_binding
from wechat_uia import ReadUnavailable, WeChatReader


def normalize_server(value):
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("网站地址不能包含账号、密码或查询参数")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
        raise ValueError("公网网站必须使用 HTTPS；本机调试允许 localhost 或 127.0.0.1")
    if not parsed.hostname:
        raise ValueError("请填写完整网站地址")
    return value if value.endswith("/api") else f"{value}/api"


class Remote:
    def __init__(self, binding):
        self.binding = binding
        self.client = httpx.Client(timeout=20, follow_redirects=False)

    def request(self, path, payload):
        response = self.client.post(f"{self.binding['server']}/wechat-sync{path}", json=payload,
            headers={"Authorization": f"Bearer {self.binding['token']}"})
        if response.status_code == 401:
            raise PermissionError("设备绑定已失效，请在网页重新生成配对码")
        if not response.is_success:
            detail = response.json().get("detail")
            raise RuntimeError(detail if isinstance(detail, str) else "服务器未接受本次请求，请稍后重试")
        return response.json()

    def close(self):
        self.client.close()


class Helper:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.thread = None
        self.binding = None
        root.title("课遇 · 微信同步助手")
        root.geometry("600x490")
        panel = ttk.Frame(root, padding=22)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="连接你的网站账号", font=("Microsoft YaHei UI", 16)).pack(anchor="w")
        ttk.Label(panel, text="只读取你选定的群。请在官方电脑微信完成登录。", wraplength=540).pack(anchor="w", pady=10)
        self.server = tk.StringVar()
        self.code = tk.StringVar()
        self.name = tk.StringVar(value=platform.node()[:80] or "我的电脑")
        self.group = tk.StringVar()
        for label, value in (("网站地址（例如 https://你的域名）", self.server), ("配对码（网页中生成）", self.code), ("电脑名称", self.name)):
            ttk.Label(panel, text=label).pack(anchor="w", pady=(8, 0))
            ttk.Entry(panel, textvariable=value).pack(fill="x")
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=12)
        self.pair_button = ttk.Button(buttons, text="配对并连接", command=self.pair)
        self.pair_button.pack(side="left")
        ttk.Button(buttons, text="开始／重新检测", command=self.start).pack(side="left", padx=10)
        ttk.Button(buttons, text="暂停助手", command=self.pause).pack(side="left")
        ttk.Label(panel, text="未自动列出群时，在微信打开目标群，再填写准确群名核对：").pack(anchor="w")
        ttk.Entry(panel, textvariable=self.group).pack(fill="x", pady=5)
        ttk.Button(panel, text="核对当前群并加入网页列表", command=self.add_group).pack(anchor="w")
        self.status = tk.StringVar(value="等待连接")
        ttk.Label(panel, textvariable=self.status, wraplength=545, foreground="#566139").pack(anchor="w", pady=15)
        root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.binding = load_binding()
            if self.binding:
                self.server.set(self.binding["server"].removesuffix("/api"))
                self.start()
        except RuntimeError as error:
            self.status.set(str(error))
        root.after(200, self.pump)

    def pump(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "bound":
                self.binding = value
                self.code.set("")
                self.pair_button.configure(state="normal")
                self.start()
            else:
                self.status.set(value)
                if kind == "pair_error":
                    self.pair_button.configure(state="normal")
        self.root.after(200, self.pump)

    def pair(self):
        if self.thread and self.thread.is_alive():
            self.status.set("请先暂停助手，待当前读取结束后再重新配对")
            return
        try:
            server = normalize_server(self.server.get())
            code, name = self.code.get().strip().upper(), self.name.get().strip()
            if not code or not name:
                raise ValueError("请填写配对码和电脑名称")
        except ValueError as error:
            self.status.set(str(error))
            return
        self.pair_button.configure(state="disabled")

        def bind():
            try:
                with httpx.Client(timeout=20, follow_redirects=False) as client:
                    response = client.post(f"{server}/wechat-sync/claim", json={"code": code, "name": name})
                    if not response.is_success:
                        detail = response.json().get("detail")
                        raise RuntimeError(detail if isinstance(detail, str) else "配对失败")
                    binding = {**response.json(), "server": server}
                    save_binding(binding)
                    self.events.put(("bound", binding))
            except Exception as error:
                detail = str(error) if isinstance(error, RuntimeError) else "配对连接失败，请检查网站地址和网络"
                self.events.put(("pair_error", detail))

        threading.Thread(target=bind, daemon=True).start()

    def start(self):
        if not self.binding:
            self.status.set("请先完成网站账号配对")
            return
        if self.thread and self.thread.is_alive():
            self.status.set("助手仍在运行，等待本轮读取结束")
            return
        self.stop.clear()
        self.commands = queue.Queue()
        self.thread = threading.Thread(target=self.loop, args=(dict(self.binding),), daemon=True)
        self.thread.start()

    def pause(self):
        self.stop.set()
        self.status.set("正在暂停，本轮读取结束后停止；网页稍后显示助手离线")

    def add_group(self):
        name = self.group.get().strip()
        if not name or len(name) > 120:
            self.status.set("请填写不超过120字的准确群名")
            return
        if not self.thread or not self.thread.is_alive():
            self.status.set("请先连接助手")
            return
        if messagebox.askyesno("核对群来源", f"请确认微信当前打开的是“{name}”，并已排除同名群。只读取此来源，不会发送消息。"):
            self.commands.put(name)

    def loop(self, binding):
        import pythoncom
        pythoncom.CoInitialize()
        remote = Remote(binding)
        outbox = Outbox(data_home() / f"queue-{binding['device_id']}.db")
        reader = WeChatReader()
        try:
            while not self.stop.is_set():
                try:
                    state = reader.probe()
                    config = remote.request("/heartbeat", state)
                    self.events.put(("status", state["detail"]))
                    if state["status"] == "ready":
                        groups = reader.catalog()
                        while not self.commands.empty():
                            name = self.commands.get_nowait()
                            try:
                                groups.append(reader.verify_current_group(name))
                            except ReadUnavailable as error:
                                self.events.put(("status", str(error)))
                        if groups:
                            remote.request("/catalog", {"groups": groups})
                        for source in config["sources"]:
                            if self.stop.is_set():
                                break
                            try:
                                # 首次读取三天历史，后续保留五分钟重叠以补读和去重。
                                since = datetime.fromisoformat(source["since"])
                                checkpoint = outbox.checkpoint(source["id"])
                                if checkpoint and checkpoint.get("revision") != source["revision"]:
                                    checkpoint = None
                                if checkpoint and checkpoint.get("last_sent_at"):
                                    since = max(since, datetime.fromisoformat(checkpoint["last_sent_at"]) - timedelta(minutes=5))
                                remote.request("/progress", {"source_id": source["id"], "status": "reading"})
                                messages, progress = reader.read_recent(source["name"], since)
                                outbox.remember(source["id"], messages)
                                while batch := outbox.batch(source["id"]):
                                    remote.request("/messages", {"source_id": source["id"], "messages": batch})
                                    outbox.acknowledge(source["id"], batch)
                                times = [datetime.fromisoformat(m["sent_at"]) for m in messages if m["sent_at"]]
                                full_history = checkpoint.get("complete", False) if checkpoint else progress["status"] == "live"
                                earliest = checkpoint.get("earliest_at") if checkpoint else progress.get("earliest_at")
                                progress["earliest_at"] = earliest
                                if not full_history:
                                    progress.update(status="partial", earliest_at=earliest,
                                        detail="新消息持续同步，首次三天历史尚不完整；可在网页暂停后重新开启补读")
                                outbox.save_checkpoint(source["id"], {"revision": source["revision"],
                                    "last_sent_at": max(times).isoformat() if times else (checkpoint or {}).get("last_sent_at"),
                                    "complete": full_history, "earliest_at": earliest})
                                remote.request("/progress", {"source_id": source["id"], **progress})
                            except ReadUnavailable as error:
                                remote.request("/progress", {"source_id": source["id"], "status": "error", "detail": str(error)[:240]})
                                self.events.put(("status", str(error)))
                    self.stop.wait(10)
                except PermissionError as error:
                    self.events.put(("status", str(error)))
                    break
                except Exception:
                    self.events.put(("status", "连接或读取失败，消息保留在本机队列，十秒后重试"))
                    self.stop.wait(10)
        finally:
            remote.close()
            outbox.close()
            pythoncom.CoUninitialize()

    def close(self):
        self.stop.set()
        self.root.destroy()


def self_test(report_path):
    """验证打包后的界面和凭证加密组件，不连接网站、不读取微信或现有绑定。"""
    import win32crypt
    import pythoncom
    result = {}
    try:
        root = tk.Tk()
        root.withdraw()
        ttk.Frame(root).pack()
        root.update_idletasks()
        root.destroy()
        result["界面资源"] = "通过"
        sample = "助手本机加密自检".encode()
        encrypted = win32crypt.CryptProtectData(sample, None, None, None, None, 0)
        assert win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1] == sample
        result["设备凭证加密"] = "通过"
        pythoncom.CoInitialize()
        try:
            from pywinauto import Desktop
            Desktop(backend="uia")
            result["界面自动化组件加载"] = "通过"
        finally:
            pythoncom.CoUninitialize()
        result["成功"] = True
    except Exception as error:
        result.update({"成功": False, "错误类别": type(error).__name__, "说明": str(error)})
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result["成功"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="课遇 Windows 微信同步助手")
    parser.add_argument("--diagnose", action="store_true", help="只读检查兼容性并退出，不读取消息")
    parser.add_argument("--self-test-report", help="验证安装包依赖并将结果写入指定文件，不读取微信")
    options = parser.parse_args()
    if options.self_test_report:
        raise SystemExit(0 if self_test(options.self_test_report) else 1)
    elif options.diagnose:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            print(json.dumps(WeChatReader().probe(), ensure_ascii=True))
        finally:
            pythoncom.CoUninitialize()
    else:
        app = tk.Tk()
        Helper(app)
        app.mainloop()
