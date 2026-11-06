# 本机实机调试后台

这是独立于在线流程演示的真实 SSH 后台和界面。Python 3.9+，支持 macOS、Windows、Linux；运行时依赖见 `requirements.txt`。首次安装需要联网下载 Python 依赖。

## 下载后启动

- macOS / Linux：在项目根目录执行 `bash start.command`。macOS 也可双击 `start.command`。
- Windows：安装 Python 并启用 Python Launcher 后，双击根目录 `start.cmd`。
- 浏览器打开启动器给出的 `http://127.0.0.1:8098/`，用自己的机器人地址登录。
- SSH 支持当前用户的密钥、SSH Agent 或密码；密码仅在登录时使用，不保存到文件。
- 首次连接需核对并确认 SSH 主机公钥指纹。可在机器人终端执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 核对 Ed25519 公钥；若协商的是另一种主机公钥，核对对应 `.pub` 文件。主机密钥变化时拒绝连接。

手动启动：

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python backend/server.py --no-browser
```

Windows 手动运行时，将解释器路径替换为 `backend\.venv\Scripts\python.exe`。

## 机器人端要求

机器人需有 Python 3、SSH 和支持下列 JSON-RPC 方法的飞特版 robotd，默认 Unix socket 为 `/run/robotd.sock`：

- `robot.busStatus`：读取真实总线反馈。
- `robot.busCommand`，`action=calibration-status`：读取已保存标定。
- `robot.busCommand` 的 `capture`、`verify-imu`、`relax` 和 `move`：分别采集标定、记录 IMU 安装确认、卸力、单颗回中位。

接口参照社区飞特版 robotd commissioning 协议编写。本后台不包含机器人固件，不自动安装、重启或切换服务；不支持这些方法的固件会显示原始错误，不回退为模拟成功。机器人需按所用固件说明进入 `commissioning` 模式，才能执行标定相关写操作。

SSH 登录用户必须具有访问该 Unix socket 的权限。如果提示 Permission denied，请按机器人固件说明配置正确用户/权限；本工具不修改 sudoers，不在命令行传密码，不要求关闭 SSH 身份校验。

## 真实功能和边界

1. 连接先读取 robotd 总线状态，成功才显示已连接；显示实时位置、温度、电压、IMU 原始反馈和已保存标定。
2. 单关节标定：支撑机身、停止运动、卸力并手摆到已知角度；填写实测方向和限位。后台检查反馈，robotd 再校验并写入机器人配置的标定文件；其他关节保留。
3. 单颗回中位：只对已配置的 ID 操作，必须确认已拆下舵盘并脱离骨架，2 秒移至 2048。此操作会真实运动。装配偏移按该关节说明处理，2048 不是所有关节的标定零位。
4. IMU：展示真实原始反馈、允许保存已经人工核验的安装确认，不自动估算安装四元数。
5. “停止并卸力”不受普通操作锁阻塞；超时和连接中断均不自动重发运动指令。实际卸力是否成功以 robotd 回执和硬件状态为准。
6. 当前后台不提供策略启用、行走、摄像头视频、ToF 服务或手柄配对。网站七步页面是独立的模拟演示，不能把其模拟结果当作本后台的真机结果。
7. 本程序不接管灵影 USB 串口。装配前用 `tools/feetech/` 的官方 FD 软件和灵影 TTL Adapter(A) 给单颗舵机设置 ID，详见该目录说明。

关闭网页不会关闭本地后台；终端按 `Ctrl+C` 退出。退出和 SSH 断开不保证机器人卸力，退出前要明确卸力并核对结果。

## 本机接口保护

只监听 `127.0.0.1`；校验 Host、Origin 和随机会话令牌；API 只接受固定操作，不提供任意 shell 命令执行入口。没有 CORS 放行、没有外部脚本。SSH 主机公钥记录保存在 `.state/known_hosts`，密码不写磁盘；该目录被 Git 忽略。

## 测试

```bash
python3 -m unittest discover -s backend/tests -v
```

自动测试覆盖 HTTP 来源/会话保护、真实 IPC 转发格式、固件错误、标定参数校验和持久化主机密钥逻辑。它不能替代你的机器人实机验收；本次开发未向实机发送运动或标定写入指令。
