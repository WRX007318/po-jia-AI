# scrcpy（Windows x64）

此目录保存 scrcpy v5.0.1 的 Windows x64 便携发行包，方便在其他 Windows 电脑上部署。scrcpy 可通过 USB 或 TCP/IP 镜像并控制已授权的 Android 设备。

## 安装

在仓库根目录打开 PowerShell，运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_scrcpy.ps1
```

脚本会将程序解压到当前用户的 `%LOCALAPPDATA%\Programs\scrcpy\scrcpy-win64-v5.0.1`，将目录加入当前用户的 PATH，并在桌面创建 scrcpy 直启和“scrcpy 功能面板”两个快捷方式。无需管理员权限。安装后新开的终端可直接运行 `scrcpy`。

功能面板可刷新设备状态、USB 投屏、无线连接并投屏、录屏和保存截图。窗口大小可选适配屏幕、小窗、标准、大窗或自定义宽高；默认保持手机画面比例，也可解除比例锁定。清晰度可选原始、1080p 或 720p；全屏模式下窗口尺寸设置不生效。录屏文件保存在“视频”目录，截图保存在“图片”目录。无线首次连接需要先插 USB、开启 USB 调试并授权，再填手机 IP；后续同网段连接可直接用无线方式。

尺寸选项使用 scrcpy 的官方窗口宽高、比例锁定和最大分辨率参数；画面默认等比例适配窗口，不会拉伸变形。详见 [scrcpy 窗口文档](https://github.com/Genymobile/scrcpy/blob/master/doc/window.md)。

使用 USB 投屏时，在 Android 设置中开启开发者选项和 USB 调试，连接手机并在手机上确认授权，然后运行 `scrcpy`。无线连接方式和更多参数见[官方文档](https://github.com/Genymobile/scrcpy)。

## 上游与许可

- 上游项目及唯一官方发布来源：[Genymobile/scrcpy](https://github.com/Genymobile/scrcpy)
- 对应发布：[v5.0.1](https://github.com/Genymobile/scrcpy/releases/tag/v5.0.1)
- scrcpy 按 GNU GPL v3.0 许可发布；随包提供上游的 `LICENSE` 文件。请以压缩包中的许可文本为准。
- 本仓库保存的是未经修改的上游 Windows x64 发行文件，供个人设备部署使用。
