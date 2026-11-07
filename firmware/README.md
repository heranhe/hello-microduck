# Hello MicroDuck 固件 R1 预览版

本固件基于社区 `kissqy/Microduck-kissqy` 的 R1 系统镜像制作，适配 Radxa ZERO 3W 与该镜像对应的飞特 HD1910 装配。社区镜像基于 Pollen Robotics 官方 Microduck 0.15.1；这不是官方发布。

## 修改内容

1. **Boot 配置写入修复**：自动应用社区源码中原先未进入发布包的 `repair-armbian-env.py`。Armbian USB 存储优化函数只在内容变化时写入启动配置，并使用同步、原子替换，降低重启或掉电时配置变空的风险。此项不保证修复供电、TF 卡或其他启动故障。
2. **统一默认密码**：`radxa` 登录和首次配网热点均使用用户指定的统一密码；首次热点配网无需再设置新系统密码。登录密码哈希和热点派生密钥通过 GitHub Actions 加密 Secret 注入构建，源码不保存密码或派生密钥；刷卡后仍可自行用 `passwd` 更改系统密码。
3. **摄像头实际像素标定**：方向 0/90/180/270°、左右/上下镜像、±45° 细调。先方向、再镜像、最后细调。变换在媒体分流前完成，WebRTC、原始 `media.frame`、截图、JPEG/H264 流和检测使用同一画面；元数据报告变换后的尺寸及 `rotate=0`，避免重复旋转。

标定保存在 `/etc/robot/camera-calibration.json`，重启后继续读取。保存失败或摄像头重启失败时恢复原配置。细调保持画幅大小，可能产生黑边和裁切。变换后不继续发布传感器原始坐标系的相机内参；视觉定位应用需要重新标定内参。

基础镜像的运动服务仍为 R17 V164 / control.40；本次重新编译的是以 V167 源码为基础的 `mediad`，不声称整套运动固件已升级 V167。

## 刷写与使用

1. 从本项目 Release 下载 `hello-microduck-zero3w-r1-preview.img.xz` 和 `SHA256SUMS`，核对 SHA256。
2. 使用 Armbian Imager 的自定义镜像功能刷入 TF 卡。刷卡会覆盖所选卡的数据。
3. 开机后连接 `Microduck-kissqy` 热点，使用本次指定的统一默认密码；访问 `http://10.42.0.1:8088` 配置家庭 Wi-Fi。系统用户为 `radxa`，登录密码也使用同一默认密码。
4. 电脑通过 SSH 建立标定后台通道，将 `机器人IP` 换成实际地址：

   ```bash
   ssh -N -L 127.0.0.1:8091:127.0.0.1:8091 radxa@机器人IP
   ```

5. 保持 SSH 窗口打开，在浏览器进入 `http://127.0.0.1:8091`，保存并应用标定。页面直接操作主板文件，不保存为浏览器预览设置。SSH 使用同一系统密码，后台服务只监听主板回环地址。
6. 在原中控中重新连接摄像头，把原中控的**预览旋转设为 0°**。本固件默认对实际画面顺时针旋转 90°。

像素变换有额外计算成本，上游曾测得高分辨率软件旋转会导致温度升高与降帧。本镜像默认使用现有固件支持的 `360p30`，建议先验证温度与实际帧率，再提高画质。

## 构建与验证

GitHub Actions 的 `Hello firmware` 工作流会固定检出上游提交，应用补丁，执行 Linux 启动写入故障测试、标定持久化/恢复测试，以及真实 GStreamer 像素变换测试，编译 ARM64 `mediad` 后制作镜像。

固定输入：

- 源码：`kissqy/Microduck-kissqy@fc0cb40ad6c8da3628e0404abb45035b53bcbe16`
- 基础镜像：`microduck-zero3w-0.15.1-R1.img.xz`
- 基础镜像 SHA256：`75da978b5d56acd9e4146256431732381de84523bb683e4ab7ac9f0580a7bce5`
- Rust：1.99.1；输出：AArch64 Linux ELF。

镜像生成时检查启动文件、内核/设备树链接、密码哈希、配网页面、服务启用状态，在镜像自身用户态加载编译程序并检查插件，卸载后运行 ext4 只读检查。

**这是尚未经新镜像实机刷卡验收的预览版。** 软件测试、文件系统检查与动态库加载通过不能替代主板启动测试。刷卡后应确认：多次正常重启、合理受控的断电重启、网络与 SSH 恢复、标定保持、各画面消费者一致，以及温度/帧率。无法启动的现有卡不能靠用户态更新包自行修复，需要离线恢复或重刷。

## 来源与许可

保留社区与官方的许可边界。固件 Rust 工作区为 Apache-2.0；Armbian 启动脚本补丁为 GPL-2.0-only；基础镜像内社区原创配网、中控及部分模型按其原许可使用。本版本供个人非商业测试，不为上游内容重新授权。

- [社区项目与分项许可](https://github.com/kissqy/Microduck-kissqy/blob/main/LICENSE)
- [社区镜像 R1 说明](https://github.com/kissqy/Microduck-kissqy/blob/main/docs/releases/public-image-r1.md)
- [官方 Microduck](https://github.com/pollen-robotics/microduck)

本目录新编写的标定代码、构建脚本及测试按 Apache-2.0 发布；对既有上游文件的修改沿用其相应许可。
