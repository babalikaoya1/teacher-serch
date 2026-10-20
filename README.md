# 家教接单筛选平台

面向手机浏览器的家教信息整理工具。首版支持粘贴或上传 TXT/CSV 聊天文本、解析预览、人工修正、保存以及条件筛选。平台不直接读取微信聊天记录。

## 技术栈

- 前端：Vue 3、TypeScript、Vite
- 后端：Python、FastAPI、SQLAlchemy
- 本地数据库：SQLite；部署时可通过 `DATABASE_URL` 切换 PostgreSQL
- AI 查找：预留接口边界，核心版本不依赖模型服务

## 启动

### 后端

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

API 文档：<http://127.0.0.1:8000/docs>

### 前端

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

前端默认请求 `http://127.0.0.1:8000/api`。可设置 `VITE_API_BASE_URL` 覆盖。

## 验收

在 `backend` 目录运行 `.\.venv\Scripts\python.exe -m pytest`；在 `frontend` 目录运行 `npm.cmd run build`。手动验收流程：粘贴多行聊天文本，检查解析预览并修改字段，确认导入，再按科目、地点或薪资筛选结果。窄屏下导入、筛选和查看单子详情均应可操作。

## 首版限制

聊天记录格式因微信版本和导出方式不同而异。当前解析器是可人工校正的启发式初版，需用脱敏真实样例逐步补充格式规则。当前无用户账号与跨用户隔离；上线前需要补充认证、授权与数据保留策略。AI 模糊查找目前只展示入口占位，尚未接入模型服务。

## 依赖环境与移植

后端虚拟环境位于 `backend/.venv`，该目录已加入 Git 忽略列表，不应复制到其他电脑。移植时用目标电脑上的 Python 重新创建虚拟环境，并从 `requirements-lock.txt` 安装固定版本。前端依赖使用 `frontend/package-lock.json` 锁定，通过 `npm.cmd ci` 安装。锁文件用于复现当前依赖版本；升级依赖时需重新运行验收命令。

macOS/Linux 用户可在后端目录运行 `python3 -m venv .venv`，然后用 `./.venv/bin/python -m pip install -r requirements-lock.txt` 安装依赖；启动和测试时同样通过该虚拟环境中的 Python 执行。
