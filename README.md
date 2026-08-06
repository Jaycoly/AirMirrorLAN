# AirMirrorLAN

AirMirrorLAN 0.4.0 是一款面向 Windows 10/11 的免费开源局域网工具：它可以接收 iPhone 的 AirPlay 屏幕镜像与声音，并通过浏览器在 iPhone 和电脑之间传输文件。所有功能均设计为在同一可信局域网内使用，iPhone 无需安装额外 App。

## 主要功能

- AirPlay 屏幕镜像和音频接收。
- 自动获取 Windows 当前默认路由所使用的局域网 IPv4，不保存固定 IP 地址。
- 两种显示方式：保持完整手机画面，或强制拉伸到整个窗口。
- 高清阅读模式：请求 3840×2160、HEVC、30 fps，并保留 H.264 回退。
- 随机或固定的 4 位 AirPlay PIN。
- 可选 MP4 录制。
- 局域网文件快传：浏览、读取、下载、新建文件夹和上传文件。
- Windows 防火墙配置、网络诊断和 GStreamer 插件诊断。

## 使用方法

首次在一台电脑上使用前，请先按“安装运行时”一节安装 UxPlay、GStreamer 和相关依赖。

1. 确认电脑和 iPhone 连接同一路由器，且 Windows 网络类型为“专用网络”。
2. 启动 `AirMirrorLAN.exe`。
3. 点击“配置防火墙（镜像+快传）”，接受 Windows 管理员权限提示。
4. 软件通常会自动启动接收；若状态为“已停止”，点击“启动接收”。
5. 在 iPhone 控制中心打开“屏幕镜像”，选择 `AirMirrorLAN`，并按提示输入 PIN。
6. 在独立投屏窗口中按 `Alt+Enter` 切换全屏。

“保持完整手机画面”会保留 iPhone 原始宽高比；窗口比例不同时会出现黑边。“强制拉伸到窗口”会铺满渲染窗口，但文字和图形可能变形。切换画质或显示方式后，需要停止并重新启动接收，再让 iPhone 重新连接。

录屏文件默认保存在 `%USERPROFILE%\Videos\AirMirrorLAN-v0.4`。

## 局域网文件快传

1. 在“局域网快传”区域选择允许 iPhone 访问的 Windows 文件夹。
2. 点击“启动快传”。
3. 在 iPhone Safari 中打开软件现场显示的地址，例如 `http://<电脑当前局域网IP>:8788`。
4. 输入窗口显示的 6 位访问码，即可浏览、读取、下载和上传文件。
5. 使用完毕后点击“停止快传”。

访问码每次启动都会改变，连续输错会触发频率限制。网页只能访问所选文件夹及其子目录，不提供删除功能；同名上传会自动生成新文件名；单个上传文件上限为 20 GB。

AirPlay 广播和快传都会在每次启动时重新获取当前默认路由对应的局域网 IPv4。若运行中切换 Wi-Fi、网线或 VPN，请停止并重新启动相应服务。

## 安装运行时

解压后在该目录中运行 PowerShell ：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup-runtime.ps1
```

脚本会从 MSYS2 官方仓库安装 UCRT64、GStreamer 和编译依赖，校验随包提供的 UxPlay 1.74 源码归档，然后构建 UxPlay。首次安装约占用 2.5 GB。

## 从源码构建程序

需要 Python 3.11 或更高版本。如果 `python.exe` 不在 PATH，可通过 `$env:PYTHON` 指定：

```powershell
$env:PYTHON = 'C:\path\to\python.exe'
.\scripts\test.ps1
.\scripts\build-app.ps1
```

## 常见问题

### iPhone 找不到电脑

- 确认两个设备在同一局域网，未使用访客 Wi-Fi、VPN 或蜂窝网络。
- 确认 Windows 网络类型为“专用”，并运行一次防火墙配置。
- 关闭路由器的 AP 隔离、客户端隔离或访客网络隔离。
- 某些企业或校园网络会阻止 mDNS 和设备间通信，建议改用自己的可信路由器。

### 有声音但没有画面

- 先使用普通主屏幕内容测试。Apple TV、部分会员视频 App 等 DRM 内容通常无法由 UxPlay 解密。
- 运行诊断，确认 `d3d11videosink` 和 `avdec_h264` 可用。

### 画面延迟或卡顿

- 优先使用 5 GHz Wi-Fi；电脑有条件时用网线连接路由器。
- 如果旧设备在高清阅读模式下连接失败或卡顿，可关闭该模式，恢复 1920×1080 H.264 兼容模式。

### iPhone 无法打开快传地址

- 确认快传正在运行，且两个设备在同一局域网。
- 输入软件显示的完整地址，包括 `http://` 和端口 `8788`。
- 重新配置防火墙，并确认未启用访客网络或客户端隔离。

## 隐私与安全

- AirMirrorLAN 不包含遥测、用户账户或云端上传功能；镜像和快传数据只在本地网络中处理。
- 快传使用 HTTP 而非 HTTPS，访问码和会话可降低误访问风险，但不能抵御不可信局域网中的监听者。只应在可信的家庭或个人网络使用。
- 不要在路由器上把 AirPlay 或 TCP 8788 端口转发到互联网。
- 配置、共享文件夹路径和可选固定 PIN 会明文保存在本机 `%APPDATA%\AirMirrorLAN-v0.4`。请妥善保护 Windows 账户。
- 共享前请确认所选文件夹不含隐私文件；使用完毕后停止快传。

## 上游项目与致谢

AirMirrorLAN 的接收核心基于 [UxPlay](https://github.com/FDH2/UxPlay)，感谢 FDH2 及所有 UxPlay 贡献者。UxPlay 的实现继承或借鉴了 RPiPlay、AirplayServer、ShairPlay、PlayFair 等开源项目的工作；各项目及其贡献者保留原有著作权。

同时感谢 [GStreamer](https://gstreamer.freedesktop.org/) 提供多媒体框架、[MSYS2](https://www.msys2.org/) 提供 Windows 构建和软件包环境，以及 Python、PyInstaller 和其他开源依赖的维护者。

固定版本的 UxPlay 源码归档、补丁说明和许可证随本项目保留。更完整的依赖与许可信息见 `THIRD_PARTY_NOTICES.md`。

## 许可证与非商业使用倡议

AirMirrorLAN 以 [GNU GPL v3](https://www.gnu.org/licenses/gpl-3.0.html)（GPL-3.0-only）发布，完整条款见 `LICENSE`。发布包同时提供程序源代码，以便检查、修改和重新构建。

本项目的定位是个人学习、研究和非商业使用。维护者倡议不要将其直接转售、收费捆绑、用于付费投屏/文件服务，或以误导方式宣称获得 Apple 或上游项目授权。

上述内容是社区倡议，不是对 GPLv3 权利的额外法律限制。根据 [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#DoesTheGPLAllowMoney)，GPLv3 允许收费分发及商业使用；任何再分发者仍须遵守 GPLv3 关于许可证、版权声明、对应源代码等要求，并分别遵守所有第三方组件的许可证和适用法律。

## 知识产权与侵权声明

- AirMirrorLAN 是独立的开源兼容性项目，与 Apple Inc. 无关联，也未获得 Apple Inc. 的认可或背书。
- Apple、iPhone、Apple TV 和 AirPlay 是 Apple Inc. 的商标；文中名称仅用于说明兼容对象。
- 本项目不声称包含 Apple 的专有源代码。AirPlay 兼容能力来自 UxPlay 及公开的兼容性研究。
- UxPlay 上游明确提示，其使用的第三方 FairPlay 兼容库的法律状态并不清晰。使用者和再分发者应自行确认所在司法辖区的法律要求；本项目不用于规避付费内容、DRM 或访问控制。
- 如果权利人认为发布内容侵犯其合法权利，请通过本软件的发布页面联系发布者并提供权利证明、具体文件或代码位置及处理请求，以便及时核查、下架或调整。

## 免责声明

本软件按“现状”提供，不作任何明示或默示保证，包括但不限于适销性、特定用途适用性、持续可用性、兼容性或不侵权保证。在法律允许的最大范围内，作者、贡献者和发布者不对数据丢失、隐私泄露、网络安全事件、服务中断、设备或账户损害，以及任何直接或间接损失承担责任。

用户须自行确保有权镜像、读取、复制或分享相关内容，并遵守当地法律、网络政策和第三方服务条款。DRM/FairPlay 保护内容不受支持；未来 iOS、Windows、UxPlay 或 GStreamer 更新也可能影响兼容性。

## 已知边界

- 仅支持同一基础局域网，不实现 Apple 的点对点 AWDL AirPlay。
- 不保证 DRM/FairPlay 保护内容可播放。
- 视频由 GStreamer 打开为独立窗口，不嵌入控制面板。
- 快传是可信局域网内的 HTTP 服务，不适合公网或不可信网络。
