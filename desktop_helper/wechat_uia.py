"""只读取可访问界面；不注入、不读取进程内存，不提供发送消息方法。"""
import hashlib
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone


class ReadUnavailable(RuntimeError):
    pass


def parse_time(text, now=None):
    now = now or datetime.now().astimezone()
    text = text.strip()
    full = re.fullmatch(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if full:
        year, month, day, hour, minute, second = full.groups()
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=now.tzinfo)
    partial = re.fullmatch(r"(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", text)
    if partial:
        month, day, hour, minute = map(int, partial.groups())
        result = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        return result.replace(year=result.year - 1) if result > now + timedelta(days=1) else result
    relative = re.fullmatch(r"(今天|昨天|前天|星期[一二三四五六日天]|周[一二三四五六日天])?\s*(\d{1,2}):(\d{2})", text)
    if relative:
        label, hour, minute = relative.groups()
        days = {None: 0, "今天": 0, "昨天": 1, "前天": 2}.get(label)
        if days is None:
            weekday = "一二三四五六日".index(label[-1].replace("天", "日"))
            days = (now.weekday() - weekday) % 7
        return (now - timedelta(days=days)).replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    return None


class WeChatReader:
    def __init__(self):
        self.window = None

    def probe(self):
        import ctypes
        import psutil
        import win32gui
        import win32process
        from pywinauto import Desktop
        ctypes.windll.user32.OpenInputDesktop.restype = ctypes.c_void_p
        ctypes.windll.user32.CloseDesktop.argtypes = [ctypes.c_void_p]
        desk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
        if not desk:
            return {"status": "locked", "detail": "桌面不可访问，解锁电脑后重试"}
        ctypes.windll.user32.CloseDesktop(desk)
        handles = []

        def inspect_window(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if psutil.Process(pid).name().lower() in ("weixin.exe", "wechat.exe"):
                    handles.append(hwnd)
            except (psutil.Error, OSError):
                return

        win32gui.EnumWindows(inspect_window, None)
        if not handles:
            return {"status": "wechat_offline", "detail": "请打开并登录官方电脑微信主窗口"}
        for hwnd in handles:
            window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
            controls = window.descendants()
            if len(controls) > 5 and any(c.element_info.control_type == "List" for c in controls):
                self.window = window
                return {"status": "ready", "detail": "界面控件可读；请先在助手核对目标群，再在网页开启同步"}
        self.window = None
        return {"status": "unsupported", "detail": "微信窗口存在，但没有可读取的消息列表。当前账号或版本不支持界面同步，请继续使用手动导入。"}

    def _lists(self):
        if self.window is None:
            raise ReadUnavailable("微信界面尚未通过兼容性检测")
        return self.window.descendants(control_type="List")

    def catalog(self):
        """只列出明确标为群聊的列表；无法确认时不把普通联系人当作群。"""
        groups = []
        for container in self._lists():
            if container.window_text().strip() not in ("群聊", "群聊列表"):
                continue
            names = [row.window_text().strip() for row in container.children(control_type="ListItem")]
            counts = Counter(names)
            for name in names:
                if name and counts[name] == 1 and len(name) <= 120:
                    groups.append({"external_key": hashlib.sha256(name.encode()).hexdigest(), "name": name})
        return groups

    def _message_list(self, name):
        if self.window is None:
            raise ReadUnavailable("微信未连接")
        lists = [c for c in self._lists() if c.window_text().strip() in ("消息", "消息列表", "聊天消息")]
        if len(lists) != 1:
            raise ReadUnavailable("未能唯一识别消息列表")
        bounds = lists[0].rectangle()
        title_matches = [c for c in self.window.descendants(control_type="Text") if c.window_text().strip() == name
            and c.rectangle().left >= bounds.left - 10 and c.rectangle().right <= bounds.right + 10
            and c.rectangle().bottom <= bounds.top]
        if len(title_matches) != 1:
            raise ReadUnavailable("无法确认当前消息窗口属于指定群，请在微信中打开该群后重试")
        return lists[0]

    def verify_current_group(self, name):
        self._message_list(name)
        return {"external_key": hashlib.sha256(name.encode()).hexdigest(), "name": name}

    def _open_group(self, name):
        try:
            return self._message_list(name)
        except ReadUnavailable:
            pass
        # 只操作明确标记为搜索框的控件，不向聊天输入框注入按键。
        searches = [c for c in self.window.descendants(control_type="Edit") if c.window_text().strip() == "搜索" or c.element_info.name == "搜索"]
        if len(searches) != 1:
            raise ReadUnavailable("无法唯一识别微信搜索框，请手动打开目标群")
        searches[0].set_edit_text(name)
        time.sleep(0.8)
        matches = [c for c in self.window.descendants(control_type="ListItem") if c.window_text().strip() == name]
        if len(matches) != 1:
            raise ReadUnavailable("目标群不存在或存在同名结果，请在微信中核对，不会自动选择")
        matches[0].click_input()
        time.sleep(0.5)
        return self._message_list(name)

    def _snapshot(self, container):
        result = []
        context_time = None
        for row in container.children():
            text = row.window_text().strip()
            try:
                stamp = parse_time(text)
            except ValueError:
                stamp = None
            if stamp:
                context_time = stamp
                continue
            if row.element_info.control_type != "ListItem":
                continue
            texts = [c.window_text().strip() for c in row.descendants(control_type="Text") if c.window_text().strip()]
            senders = [c.window_text().strip() for c in row.descendants(control_type="Button") if c.window_text().strip()]
            if not texts:
                continue
            body = "\n".join(texts)
            if body in ("[图片]", "[语音]", "[视频]", "[文件]", "[聊天记录]"):
                continue
            if len(body) > 10000:
                raise ReadUnavailable("消息超过文本长度限制，请通过手动导入分段处理")
            result.append({"text": body, "sender": senders[0][:120] if senders else None,
                "sent_at": context_time.astimezone(timezone.utc).isoformat() if context_time else None})
        return result

    def read_recent(self, name, since):
        container = self._open_group(name)
        try:
            container.set_focus()
            container.type_keys("^{END}")
        except Exception:
            raise ReadUnavailable("消息列表无法滚动，不能确认历史覆盖范围")
        collected = []
        started = time.monotonic()
        complete = False
        for _ in range(30):
            page = self._snapshot(container)
            if not page:
                raise ReadUnavailable("未取得可确认的文本消息，不能把空结果标为同步成功")
            if collected:
                overlap = 0
                for count in range(min(len(page), len(collected)), 0, -1):
                    if page[-count:] == collected[:count]:
                        overlap = count
                        break
                if not overlap:
                    raise ReadUnavailable("历史翻页没有连续重叠消息，已暂停以避免漏读或重复")
                merged = page[:-overlap] + collected
                if merged == collected:
                    break
                collected = merged
            else:
                collected = page
            times = [datetime.fromisoformat(m["sent_at"]) for m in collected if m["sent_at"]]
            if times and min(times) <= since:
                complete = True
                break
            if time.monotonic() - started > 20:
                break
            try:
                container.scroll("up", "page")
                time.sleep(0.15)
            except Exception:
                break
        messages = [m for m in collected if m["sent_at"] is None or datetime.fromisoformat(m["sent_at"]) >= since]
        return messages, {"status": "live" if complete else "partial", "earliest_at": min(times).isoformat() if times else None,
            "detail": None if complete else "仅同步到本机可读的部分历史，尚未覆盖完整三天；请检查电脑微信历史是否完整"}
