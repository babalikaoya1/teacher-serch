# 家教接单筛选平台

面向手机浏览器的私人家教订单库，支持账号登录、TXT/CSV 或粘贴导入、解析预览、人工修正、条件筛选、通勤半径和 AI 查单。新增 Windows 微信同步助手及服务器同步队列；浏览器本身不能读取微信聊天记录。

公网部署步骤见 [部署说明](deploy/README.md)，助手操作见 [助手说明](desktop_helper/README.md)，本轮验收与未完成项见 [验收记录](deploy/验收记录.md)。当前本机微信未通过控件兼容性检测，不能承诺自动读取真实群聊；仍可使用手动导入。

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

聊天记录格式因微信版本和导出方式不同而异，识别不完整的同步消息需人工确认。账号、订单、设备、群来源和 AI 候选已按用户隔离；AI 只发送当前账号最多 30 条候选的必要字段。同步订单按原消息发布时间保留三天，手动订单按导入时间保留三天。微信账号或版本未提供可读控件时，助手会报告不兼容，不能靠网页登录取得读取权限。

升级后必须先登录。旧数据库中没有归属账号的订单不会向新注册用户展示；备份并停止服务后，在 `backend` 目录运行 `.\.venv\Scripts\python.exe -m app.bootstrap`，交互输入历史订单归属账号及密码，再启动服务。该命令只归属尚无所有者的旧订单；超过三天的订单仍会按既有规则清理。

## 依赖环境与移植

后端虚拟环境位于 `backend/.venv`，该目录已加入 Git 忽略列表，不应复制到其他电脑。移植时用目标电脑上的 Python 重新创建虚拟环境，并从 `requirements-lock.txt` 安装固定版本。前端依赖使用 `frontend/package-lock.json` 锁定，通过 `npm.cmd ci` 安装。锁文件用于复现当前依赖版本；升级依赖时需重新运行验收命令。

macOS/Linux 用户可在后端目录运行 `python3 -m venv .venv`，然后用 `./.venv/bin/python -m pip install -r requirements-lock.txt` 安装依赖；启动和测试时同样通过该虚拟环境中的 Python 执行。

## 地图与距离配置

地图配置保存在 `backend/.env`。`MAP_WEB_SDK_URL` 和 `MAP_WEB_PUBLIC_KEY` 用于网页地图；`MAP_WEB_SERVICE_KEY` 是后端地理编码专用 Web 服务 Key，只在后端读取，绝不通过 API 返回。`MAP_WEB_SECURITY_CODE` 也只保存在后端：JS 地图服务请求通过后端代理附加安全码，限制代理路径为地址地理编码与 POI 搜索，不发送安全码到浏览器。移植时在目标电脑单独填入这些值，不要把 `backend/.env` 提交到版本库；`backend/.env.example` 仅提供空变量模板。

顶部“所在地级市”用于补全模糊地址，也用于距离筛选时限定城市。导入预览和确认时由后端调用高德地理编码：优先使用 `MAP_WEB_SERVICE_KEY`；若该 Key 返回平台不匹配，则使用 `MAP_WEB_PUBLIC_KEY` 加 `MAP_WEB_SECURITY_CODE` 在服务端重试。先做地址地理编码，简称/小区/地标地址未命中时回退到 POI 关键字搜索；地级市作为区域约束。每次外部请求最多等待 3.5 秒，整批最多等待 12 秒，失败订单保留供应商错误码或超时原因，不阻断其他订单导入。已有订单在首次按距离筛选前按城市批量补坐标，后端保存结果后执行现有城市/坐标预筛和 Haversine 直线距离计算。地图弹窗仍使用网页 SDK，自动地址转坐标不依赖浏览器 SDK。路线规划/驾车通勤距离没有接入。

自动定位失败时，预览和已保存订单显示可读失败原因及手动地图选点入口。常规通勤半径筛选会先尝试补全当前地级市已有订单的坐标，再按用户设置的半径返回订单。订单保留导入时间，列表显示日期；应用启动及后续查询/导入时自动删除超过 3 天的订单，并显示清理数量提醒。连续粘贴多单时可按订单编号边界拆分，无需依赖空行。

后端预留路径：

- `GET /api/maps/config`：返回网页 SDK 地址、公开 key 与配置状态
- `GET /api/jobs?origin_lat=纬度&origin_lng=经度&max_distance_km=半径`：按直线距离筛选并返回 `distance_km`
- `POST /api/import/preview`：表单字段 `source_group` 和 `city`；后端返回已地理编码的草稿及失败原因
- `POST /api/jobs/geocode-missing?city=地级市`：距离筛选前按城市补全已有订单坐标
- `POST /api/maps/geocode`：后端地理编码单个地址，不返回或接收任何 Key
- `GET /api/maps/amap-service/{path}`：网页地图服务代理，只允许 Geocoder 和 POI 搜索路径，后端附加安全码
- `PATCH /api/jobs/{job_id}/location`：更新已有订单的地址坐标

城市设置保存在当前浏览器的本地存储中。距离筛选时前端会将所选城市传给后端；未设置城市时仍可使用坐标和半径筛选，只是不做城市分组预筛。

若地址定位显示高德 `10009 USERKEY_PLAT_NOMATCH`，表示 `MAP_WEB_SERVICE_KEY` 绑定的平台与 Web 服务接口不符（例如将 JS API Key 用作 Web 服务 Key）。后端会尝试使用 JS Key 和服务端安全码回退；若仍失败，请在高德控制台创建 Web 服务 API 类型 Key，替换 `MAP_WEB_SERVICE_KEY` 并重启后端。JS Key 和安全码不会返回浏览器。

订单地址会在预览和确认导入时自动定位；仍可在预览编辑区域手动填写坐标。来源群聊在导入和订单卡片中显示，并支持来源筛选。

## 大模型配置与自然语言查找

如果 `backend/.env` 不存在，可复制 `backend/.env.example` 创建；已有 `.env` 时只修改相应变量，避免覆盖其他配置。填写以下服务端配置后重启后端。密钥只保存在后端，不要添加到任何 `VITE_` 前端变量中：

- `LLM_CHAT_COMPLETIONS_URL`：OpenAI 兼容聊天补全接口，可填完整 `/chat/completions` 地址或 `/v1` 基础地址（后端会补全路径）
- `LLM_API_KEY`：服务端密钥
- `LLM_MODEL`：服务商要求的模型标识
- `LLM_TIMEOUT_SECONDS`：请求超时时间，默认 30 秒

自然语言查找界面位于首页订单列表上方；API 为 `POST /api/ai/search`，请求体为 `{"query":"顺义附近，初中英语，周末上课"}`。`GET /api/ai/config` 仅返回是否配置和模型名，不返回密钥。模型只从数据库现有开放订单中选择，后端会丢弃模型返回的未知订单 ID。兼容格式以外的厂商需要修改 `backend/app/services/ai_search.py` 的请求/响应适配。

AI 错误会区分鉴权（401/403）、路径（404）、模型/参数（400）、超时、连接失败和响应结构错误；诊断不会输出密钥或服务商原始响应内容。
