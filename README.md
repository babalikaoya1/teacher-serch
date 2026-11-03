# 家教接单筛选平台

面向手机浏览器的家教信息整理工具。首版支持粘贴或上传 TXT/CSV 聊天文本、解析预览、人工修正、保存以及条件筛选。平台不直接读取微信聊天记录。

## 技术栈

- 前端：Vue 3、TypeScript、Vite
- 后端：Python、FastAPI、SQLAlchemy
- 本地数据库：SQLite；部署时可通过 `DATABASE_URL` 切换 PostgreSQL
- AI 查找：服务端调用可配置的 OpenAI 兼容聊天补全接口

## 启动

后端应用入口文件是 `backend/app/main.py`，前端启动入口文件是 `frontend/src/main.ts`（由 Vite 启动）。

### 后端

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```


### 前端

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```


## 验收

在 `backend` 目录运行 `.\.venv\Scripts\python.exe -m pytest`；在 `frontend` 目录运行 `npm.cmd run build`。手动验收流程：粘贴多行聊天文本，检查解析预览并修改字段，确认导入，再按科目、地点或薪资筛选结果。窄屏下导入、筛选和查看单子详情均应可操作。

## 首版限制

聊天记录格式因微信版本和导出方式不同而异。当前解析器是可人工校正的启发式初版，需用脱敏真实样例逐步补充格式规则。当前无用户账号与跨用户隔离；上线前需要补充认证、授权与数据保留策略。AI 模糊查找会把需求和最多 300 条最新开放订单发送到所配置的模型服务进行匹配。

## 依赖环境与移植

后端虚拟环境位于 `backend/.venv`，该目录已加入 Git 忽略列表，不应复制到其他电脑。移植时用目标电脑上的 Python 重新创建虚拟环境，并从 `requirements-lock.txt` 安装固定版本。前端依赖使用 `frontend/package-lock.json` 锁定，通过 `npm.cmd ci` 安装。锁文件用于复现当前依赖版本；升级依赖时需重新运行验收命令。

macOS/Linux 用户可在后端目录运行 `python3 -m venv .venv`，然后用 `./.venv/bin/python -m pip install -r requirements-lock.txt` 安装依赖；启动和测试时同样通过该虚拟环境中的 Python 执行。

## 地图与距离配置

地图配置只使用 `MAP_WEB_SDK_URL` 和 `MAP_WEB_PUBLIC_KEY`，保存在 `backend/.env`。当前工作区已将已有值放入本地配置；移植到其他电脑时，将这两项从本机安全配置复制到 `backend/.env`，不要将 key 提交到版本库。`backend/.env.example` 只提供空变量模板。公开 key 会由后端配置接口发送给浏览器以初始化地图 SDK，这是地图网页 SDK 的工作方式。

顶部“所在地级市”设置用于补全模糊地址，也用于距离筛选时先筛出同一城市的订单。订单保存地级市及坐标，并建立城市/坐标组合索引。地图弹窗支持搜索地点、地图点击选点和地址回显；导入预览和确认导入时会自动查询订单地址并保存坐标。每条地址最多查询 3.5 秒、每批最多 12 秒，超时或无结果时跳过坐标，订单仍全部导入；之后可在订单卡片中手动选点。距离筛选先按城市和半径外接矩形缩小候选订单，再批量计算精确 Haversine 直线距离。路线规划/驾车通勤距离没有接入，因为当前只使用网页 SDK 地址与公开 key，没有单独的路线服务接口。

后端预留路径：

- `GET /api/maps/config`：返回网页 SDK 地址、公开 key 与配置状态
- `GET /api/jobs?origin_lat=纬度&origin_lng=经度&max_distance_km=半径`：按直线距离筛选并返回 `distance_km`
- `POST /api/import/preview`：表单字段 `source_group` 保存来源群聊
- `PATCH /api/jobs/{job_id}/location`：更新已有订单的地址坐标

城市设置保存在当前浏览器的本地存储中。距离筛选时前端会将所选城市传给后端；未设置城市时仍可使用坐标和半径筛选，只是不做城市分组预筛。

订单地址会在预览和确认导入时自动定位；仍可在预览编辑区域手动填写坐标。来源群聊在导入和订单卡片中显示，并支持来源筛选。

## 大模型配置与自然语言查找

如果 `backend/.env` 不存在，可复制 `backend/.env.example` 创建；已有 `.env` 时只修改相应变量，避免覆盖其他配置。填写以下服务端配置后重启后端。密钥只保存在后端，不要添加到任何 `VITE_` 前端变量中：

- `LLM_CHAT_COMPLETIONS_URL`：OpenAI 兼容聊天补全接口，可填完整 `/chat/completions` 地址或 `/v1` 基础地址（后端会补全路径）
- `LLM_API_KEY`：服务端密钥
- `LLM_MODEL`：服务商要求的模型标识
- `LLM_TIMEOUT_SECONDS`：请求超时时间，默认 30 秒

自然语言查找界面位于首页订单列表上方；API 为 `POST /api/ai/search`，请求体为 `{"query":"顺义附近，初中英语，周末上课"}`。`GET /api/ai/config` 仅返回是否配置和模型名，不返回密钥。模型只从数据库现有开放订单中选择，后端会丢弃模型返回的未知订单 ID。兼容格式以外的厂商需要修改 `backend/app/services/ai_search.py` 的请求/响应适配。

AI 错误会区分鉴权（401/403）、路径（404）、模型/参数（400）、超时、连接失败和响应结构错误；诊断不会输出密钥或服务商原始响应内容。
