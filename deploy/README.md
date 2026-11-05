# 公网部署说明

交付方式是同域网站、FastAPI API、PostgreSQL 和 Windows 助手。现有架构保持不变。本轮没有服务器或域名，仅准备部署文件；容器、HTTPS、真实 PostgreSQL 和两台实体电脑联调尚待运行验证。

## 文件与配置

| 位置 | 用途 |
| --- | --- |
| `deploy/compose.yaml` | 数据库、后端和 Caddy 网站服务 |
| `deploy/.env` | 从 `.env.example` 复制，填写 `APP_DOMAIN`、`POSTGRES_PASSWORD` |
| `backend/.env` | 地图和模型私密配置；通过环境变量注入容器 |
| `desktop_helper/dist/微信同步助手.exe` | 网页登录后下载的安装包，需要随部署文件上传 |
| `backend/app/bootstrap.py` | 明确指定历史订单归属账号 |
| `backend/app/migrate_database.py` | SQLite 快照迁入空 PostgreSQL |
| `deploy/backup.sh` | PostgreSQL 备份 |

`APP_DOMAIN` 只填域名，不带协议和路径。数据库密码请使用足够长的随机字母数字组合，避免连接 URL 中特殊字符需要额外编码。不要把真实 `.env` 放入 Git 或前端构建目录。地图私密 Key、JS 安全码及模型 Key 继续放 `backend/.env`，助手只拿设备凭证。公开地图 Key 仍按地图 SDK 用途返回浏览器。

## 新部署

准备安装 Docker Engine 和 Compose 插件的 Linux 主机、已解析到主机的域名，以及可用的 80/443 端口。代码、锁文件和已构建的助手 exe 上传到同一项目目录，不上传本机 `.venv`、队列和 `node_modules`。

首次创建配置，已有配置时不要覆盖：

```sh
cd deploy
cp -n .env.example .env
cp -n ../backend/.env.example ../backend/.env
```

手工填写两个配置文件，再运行：

```sh
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

Compose 会覆盖数据库地址为内部 PostgreSQL、环境为 `production`，允许来源为正式 HTTPS 域名。API 和数据库不直接发布公网端口。Caddy 提供 HTTPS 和同域 `/api` 代理；生产会话 Cookie 为 HttpOnly、Secure、SameSite=Lax。

打开网站注册两个独立账号，先验证手动导入、查询、AI、地图和助手配对。公网地址填入助手，用户不用配置电脑入站端口。首次启动失败时检查 `docker compose logs --tail=100 api web`，不要把包含个人数据或凭证的日志公开粘贴。

## 已有 SQLite 数据搬迁

不要先公开网站再搬历史数据。停止本地后端，保留原 SQLite 文件及备份。下列步骤针对尚无业务数据的目标 PostgreSQL；已经使用过的目标库需要另建空库，不允许覆盖。

1. 将 SQLite 备份放到项目 `deploy/legacy/teacher_search.db`，该目录不入 Git。
2. 只启动数据库，构建服务镜像；然后以只读方式挂载备份执行迁移。

```sh
docker compose build
docker compose up -d db
docker compose run --rm -v "$PWD/legacy:/migration:ro" api python -m app.migrate_database --source /migration/teacher_search.db
docker compose run --rm api python -m app.bootstrap
docker compose up -d
```

初始化命令交互询问账号和密码；旧订单只归属到指定账号，绝不交给第一个注册者。已有归属关系保留。迁移对源文件只读，在临时副本补字段；目标非空则拒绝复制，复制事务失败会回滚。PostgreSQL 序列同步逻辑已实现，但仍需要目标环境实测。旧订单的三天有效期不因搬迁重置，启动后会清理过期项。

如果仅在当前电脑升级、不搬库：停止后端并备份，在 `backend` 中运行 `.\.venv\Scripts\python.exe -m app.bootstrap`，再按根目录 README 启动。当前真实数据库未在本轮测试中修改或归属。

## 备份、恢复与升级

在 `deploy` 执行 `sh backup.sh`，将生成的 `backups/*.dump` 再复制到独立存储。建议每日定时运行。备份包含私人订单及凭证校验信息，应限制访问。恢复必须先在独立测试库验证：

```sh
docker compose exec -T db createdb -U teacher teacher_restore_check
docker compose exec -T db pg_restore -U teacher -d teacher_restore_check --exit-on-error < backups/实际备份文件.dump
```

上述恢复库不要替换在线库，核对记录数与账号归属后再制定切换。升级前先备份，再 `docker compose up -d --build`；不要执行 `docker compose down -v`，它会删除数据库和证书卷。备份脚本与恢复步骤本轮未在真实 PostgreSQL 执行。

## 限额与运行方式

首版使用单个 API 进程和数据库持久化工作队列，不把重试任务留在浏览器内存中。租约失效后可恢复，去重靠数据库唯一约束。暂不扩成多副本；扩容前需另行验证清理任务和队列并发。

`backend/.env` 可设置 `AI_REQUESTS_PER_MINUTE`（默认每用户 10）、`MAP_REQUESTS_PER_MINUTE`（默认每用户 60）、`SYNC_BATCHES_PER_MINUTE`（默认每设备 120 次设备接口请求）。注册、登录、配对也有限额。地图失败不阻止同步订单入库，订单卡片保留失败原因。

## 必须补做的公网验收

1. 两账号分别导入不同订单；搜索、AI、地图修改和补坐标不得串号；更换他人订单/设备编号返回拒绝。
2. 两台电脑配对、独立选群；断网恢复、重启、重复上传不重复入库；解绑后旧令牌上传返回 401。
3. 在能读取控件的微信环境核对三天历史和新增消息；三个测试群新增文本订单以 30 秒内可查询为目标，记录实际耗时，不用模拟数据代替。
4. 锁屏、微信退出、助手关闭和历史不完整均展示真实状态；手机能查询自己的订单及最后同步时间。
5. 验证 HTTPS、Cookie、PostgreSQL 迁移与备份恢复、下载 exe 及第二台 Windows 启动。

当前本机微信控件不可读，因此第 3 项尚无通过证据。详情见 [验收记录](验收记录.md)。
