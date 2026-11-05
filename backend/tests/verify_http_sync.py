"""通过真实本机 HTTP 服务验证两账号同步链路，使用临时数据库与模拟消息。"""
from datetime import datetime, timezone
import asyncio
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def verify():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="teacher-http-") as directory:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment = {**os.environ, "DATABASE_URL": f"sqlite:///{Path(directory).as_posix()}/test.db",
            "APP_ENV": "development", "SYNC_WORKER_ENABLED": "true", "MAP_WEB_SERVICE_KEY": "",
            "LLM_API_KEY": "", "PYTHONIOENCODING": "utf-8"}
        log_path = Path(directory) / "server.log"
        stop_path = Path(directory) / "stop.request"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", str(port), str(stop_path)],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as a, \
                     httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as b:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            if a.get("/api/health").is_success:
                                break
                        except httpx.ConnectError:
                            pass
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("临时服务未能启动")
                        time.sleep(0.2)
                    devices = []
                    for index, client in enumerate((a, b)):
                        response = client.post("/api/auth/register", json={"username": f"联调用户{index}", "password": secrets.token_urlsafe(24)})
                        assert response.status_code == 201, response.text
                        code = client.post("/api/wechat-sync/pairing-code").json()["code"]
                        device = client.post("/api/wechat-sync/claim", json={"code": code, "name": f"模拟电脑{index}"}).json()
                        headers = {"Authorization": f"Bearer {device['token']}"}
                        assert client.post("/api/wechat-sync/catalog", headers=headers, json={"groups": [{"external_key": "模拟来源", "name": "模拟同名群"}]}).is_success
                        source = client.get("/api/wechat-sync/status").json()["sources"][0]
                        assert client.patch(f"/api/wechat-sync/sources/{source['id']}", json={"enabled": True, "city": "北京"}).is_success
                        payload = {"source_id": source["id"], "messages": [{"message_key": "模拟同一编号", "sent_at": datetime.now(timezone.utc).isoformat(),
                            "text": "初中数学家教，周末上课，薪资180元/小时，地址在海淀区"}]}
                        assert client.post("/api/wechat-sync/messages", headers=headers, json=payload).json()["accepted"] == 1
                        assert client.post("/api/wechat-sync/messages", headers=headers, json=payload).json()["duplicates"] == 1
                        devices.append((device, headers))
                    deadline = time.monotonic() + 20
                    while True:
                        first, second = a.get("/api/jobs").json(), b.get("/api/jobs").json()
                        if len(first) == len(second) == 1:
                            break
                        assert time.monotonic() < deadline, "后台工作队列未按时处理模拟消息"
                        time.sleep(0.2)
                    assert first[0]["id"] != second[0]["id"]
                    assert b.patch(f"/api/jobs/{first[0]['id']}/status", params={"status": "closed"}).status_code == 404
                    device, headers = devices[0]
                    assert a.delete(f"/api/wechat-sync/devices/{device['device_id']}").is_success
                    assert a.post("/api/wechat-sync/heartbeat", headers=headers, json={"status": "ready"}).status_code == 401
            except Exception:
                log.flush()
                print(log_path.read_text(encoding="utf-8"))
                raise
            finally:
                # 通过专属停止文件让服务正常退出，避开 Windows 启动器和强制结束权限差异。
                stop_path.touch()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print("本机 HTTP 联调通过：两账号独立入库、后台队列、重复上传去重、越权拒绝、解绑失效。")
    print("使用模拟消息和临时 SQLite；未读取真实微信，未连接地图或模型服务。临时服务已正常退出。")


async def serve(port, stop_path):
    import uvicorn
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=int(port)))

    async def watch_stop():
        while not Path(stop_path).exists():
            await asyncio.sleep(0.1)
        server.should_exit = True

    watcher = asyncio.create_task(watch_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        asyncio.run(serve(sys.argv[2], sys.argv[3]))
    else:
        verify()
