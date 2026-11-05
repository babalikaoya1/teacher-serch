# Windows 微信同步助手

这是现有项目的电脑端组件。网站、助手和服务器分工如下：网页管理自己的群和订单；助手只读电脑微信中已选群的文本；服务器识别、去重、入库并补坐标。助手不发送消息，不使用微信数据库解密或进程注入。

## 当前可用边界

本机微信 4.1.15.56 的只读检测仅发现一个窗口容器，没有消息列表控件，状态为 `unsupported`。因此尚未验证真实群目录、三天历史、新消息和三群 30 秒入库。兼容性失败时请用网站手动导入；安装包成功启动不等于微信可读取。

## 用户操作

1. 注册并登录网站，在导入页选择“下载 Windows 助手”和“生成配对码”。
2. 双击 `微信同步助手.exe`，填写网站地址、配对码和电脑名称。公网地址必须为 HTTPS；本机调试可用 `http://127.0.0.1:8000`。
3. 登录官方电脑微信，助手先检测读取能力。不支持时显示原因，不伪报成功。
4. 支持时，网页显示可选择的群。如果未列出群，在微信打开该群，助手输入准确名称，点击“核对当前群并加入网页列表”。同名群必须由本人核对；无法唯一确认时拒绝自动打开。
5. 在网页该群下点击“同步近三天并持续同步”。网页关闭不影响助手；关闭助手或关机后不再采集，手机可继续查看服务器中未过期订单。
6. 历史不完整时网页明确显示覆盖时间；暂停后重新开启会重新补读三天。缺少可靠消息时间或订单字段的内容进入“需要你确认的消息”。

助手需要能访问微信主窗口，可能切换所选聊天并滚动历史。锁屏、退出微信或窗口不可访问会暂停；不要把显示“在线”理解为“微信可读”。网页同时显示设备连接状态和读取原因。

## 数据保存与撤销

- 设备凭证运行时生成，保存在 `%LOCALAPPDATA%\TeacherSearchSync\binding.bin`，使用当前 Windows 用户的 DPAPI 加密。它不包含网站密码、地图或模型密钥。
- 本机未上传消息保存在同目录的 `queue-设备编号.db`；上传确认后清空队列正文，保留短期去重指纹。不要把这个目录随安装包分发。
- 同步按群来源、原消息时间、发送人、文本及同分钟重复次数生成指纹。UIA 不提供稳定官方消息 ID，真实环境中的重复片段与历史覆盖仍须专门验收。
- 网站“解除绑定”会使旧设备凭证立即失效。更换微信账号或网站账号前先暂停并解除旧绑定，再重新配对和选群；首版尚未验证微信账号切换的自动识别。

## 独立环境、测试和打包

在本目录执行（首次安装要求 Python 自带 Tcl/Tk 组件）：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe build.py
```

产物在 `dist/微信同步助手.exe`。构建过程中必须能读取 Python 的 Tcl/Tk 资源；若出现 `tkinter installation is broken`，先检查资源访问权限，不能分发该次构建。安装包尚未代码签名，发布前需按实际分发环境安排签名和第二台电脑验证。

验证打包依赖（不连接网站、不读取微信）：

```powershell
$helperCheck = Start-Process -FilePath '.\dist\微信同步助手.exe' -ArgumentList '--self-test-report', 'build/package-self-test.json' -WindowStyle Hidden -Wait -PassThru
$helperCheck.ExitCode
Get-Content build/package-self-test.json -Encoding UTF8
```

只检查微信兼容性，不读取聊天正文：

```powershell
.\.venv\Scripts\python.exe main.py --diagnose
```

不要复制 `.venv` 到其他电脑。普通使用者只需要 exe；开发者根据锁文件重建依赖。
