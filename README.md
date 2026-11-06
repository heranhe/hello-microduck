# hello-microduck

手把手做一只 MicroDuck。从买零件到标定好，一步一步来，每一步都有照片。

**在线教程：<https://hello-microduck.pages.dev>**

> 非官方教程。与 MicroDuck 官方团队 Pollen Robotics 无关，没有得到官方授权或认可。MicroDuck 是 Pollen Robotics 的[开源项目](https://github.com/pollen-robotics/microduck)。

## 选一个方案

| 方案 | 状态 | 说明 |
|---|---|---|
| [飞特 HD-1910](https://hello-microduck.pages.dev/feetech/) | 可以开始 | 用飞特 HD-1910 舵机代替官方 XL330，舵机便宜好买，装配多几步 |
| [官方 XL330](https://hello-microduck.pages.dev/xl330/) | 准备中 | 官方原版做法，装起来更简单 |

## 飞特方案一共五步

1. [准备材料和打印](https://hello-microduck.pages.dev/feetech/materials)：采购清单、打印外壳
2. [给舵机设 ID](https://hello-microduck.pages.dev/feetech/servo-id)：15 颗舵机各设一个编号，顺便转到中位
3. [主板、HAT 和接线](https://hello-microduck.pages.dev/feetech/boards)：摄像头排线、焊 ToF、舵机线序、装舵机
4. [写入系统、通电](https://hello-microduck.pages.dev/feetech/system)：写 TF 卡、插卡方向、哪个 C 口供电
5. [用调试工具标定](https://hello-microduck.pages.dev/feetech/calibrate)：系统写好以后再用调试工具标定

## 调试工具

[调试工具](https://hello-microduck.pages.dev/tool/)带着你完成标定：连接、检查舵机、摆零位、姿态传感器、试站、手柄，另外可以随时检查摄像头和 ToF。

**现在是演示版**：用模拟数据，可以先熟悉流程，还不会连接或控制真实的 MicroDuck。

## Hello 固件预览版

[固件构建与使用说明](firmware/README.md)包含启动配置写入修复、统一默认密码，以及在主板上保存并应用的摄像头实际像素标定。[固件下载](https://github.com/heranhe/hello-microduck/releases)见 Release。新镜像仍需实机刷卡和反复重启验收。

## 还在补充

- HD-1910 版打印文件的下载地址和打印参数
- 适配这套硬件的系统镜像和下载地址
- 官方 XL330 方案的教程

## 修改这个教程

页面正文在 `src/pages/` 里，改完运行：

```bash
python3 build.py
```

在本机预览：

```bash
python3 -m http.server 8000 --directory site
```

然后打开 <http://localhost:8000>。

```text
hello-microduck/
├── build.py              生成网站：给正文套上页头、步骤导航和页脚
├── src/
│   ├── style.css         网站样式
│   └── pages/            每一页的正文
├── tool/
│   └── calibration.html  调试工具（单文件）
└── site/                 生成好的网站，直接部署这个目录
    └── assets/img/       教程照片（已去掉位置等元数据）
```

部署到 Cloudflare Pages 时，输出目录填 `site`，不需要构建命令。

## 第三方资料和署名

- 调试工具里的 MicroDuck 3D 模型、关节范围、配色和地面网格算法来自 [pollen-robotics/microduck-simulator](https://huggingface.co/spaces/pollen-robotics/microduck-simulator) 和 [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck)，Apache-2.0。
- 调试工具里的手柄 3D 模型基于 “[Xbox Elite Controller](https://sketchfab.com/3d-models/xbox-elite-controller-32aad0ff25f7446b8afe649ea3cc9e43)”，作者 [Rusfort](https://sketchfab.com/Rusfort)，[CC-BY-4.0](http://creativecommons.org/licenses/by/4.0/)。已删除背部拨片和按键外层透明罩，去掉贴图和按键上的 logo。
- 3D 渲染库 three.js（MIT）；字体 Anton 和 Noto Sans SC（SIL OFL）。
- 第 3 步的图 6 截自飞特 HD-1910-C001 产品规格书，图 7 截自 Robot HAT 的 PCB 工程。
- 第 4 步“用 5 GHz Wi-Fi 避免和手柄干扰”的经验来自 [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)。
- 文中出现的 MicroDuck、Xbox、飞特、GameSir 等名称归各自所有者，只用来说明兼容关系。

## 许可

还没有选定许可证，选好后补上。
