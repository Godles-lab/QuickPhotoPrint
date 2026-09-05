<p align="center">
  <img src="quickprint/assets/app-icon.png" alt="轻印图标" width="112">
</p>

<h1 align="center">轻印 QuickPhotoPrint</h1>

<p align="center">改善兄弟打印机照片打印体验，让照片排版和 ICC 配置管理更简单。</p>

<p align="center">
  <a href="https://github.com/Godles-lab/QuickPhotoPrint/releases/latest">下载最新版本</a> ·
  <a href="quickprint/README.md">使用说明</a> ·
  <a href="https://github.com/Godles-lab/QuickPhotoPrint/issues">反馈问题</a>
</p>

轻印是一款适用于 **Windows 和 macOS** 的轻量照片打印工具，主要围绕兄弟打印机的照片打印需求设计。可以在一个窗口中完成相纸设置、照片构图、打印预览，以及简单的 ICC 配置文件管理。照片在本机处理。

## 下载

当前版本：**0.2.11**。解压即可使用，无需安装 Python。

| 平台 | 下载 |
| --- | --- |
| Windows 10 / 11 · x64 | [QuickPhotoPrint-Windows-x64.zip](https://github.com/Godles-lab/QuickPhotoPrint/releases/download/quickprint-v0.2.11/QuickPhotoPrint-Windows-x64.zip) |
| macOS 13+ · Apple Silicon（M 系列） | [QuickPhotoPrint-macOS-arm64.zip](https://github.com/Godles-lab/QuickPhotoPrint/releases/download/quickprint-v0.2.11/QuickPhotoPrint-macOS-arm64.zip) |
| macOS 13+ · Intel | [QuickPhotoPrint-macOS-x86_64.zip](https://github.com/Godles-lab/QuickPhotoPrint/releases/download/quickprint-v0.2.11/QuickPhotoPrint-macOS-x86_64.zip) |

Windows 请完整解压，运行 `QuickPhotoPrint.exe`，保留同目录的 `_internal` 文件夹。Mac 将 `QuickPhotoPrint.app` 放入“应用程序”；更新时先退出旧版。当前应用尚未进行商业代码签名或 Apple 公证，如系统阻止打开，请核对下载来源后按系统提示处理。

## 可以做什么

- **照片排版**：常见相纸与自定义毫米尺寸，铺满或完整显示，拖动构图、缩放、旋转和四边留白。
- **打印预览**：检查照片在纸上的位置与裁切；可用“预览尺寸补偿”按试印结果校准预览大小。
- **ICC 配置管理**：导入、选择和移除 RGB ICC / ICM，内置 Brother DCP-T735DW 搭配柯达高光相纸的个人经验配置。
- **简单颜色微调**：亮度、对比度、红、绿、蓝五项相对调节，可另存为独立 ICC 文件，在其他支持 ICC 的软件中使用。
- **更顺畅的操作**：照片载入和打印准备显示进度，设置可保存为预设，滚轮不会误改参数，设置页按需显示滚动条。

## 开始打印

1. 打开照片，选择打印机与实际使用的相纸尺寸。
2. 在预览中调整构图、照片大小和留白。
3. 选择由打印机管理颜色，或选择需要的 ICC。已有 ICC 可从颜色列表末尾导入。
4. 点击“打印照片”，核对驱动中的纸张类型、质量和无边框设置。

Windows 的纸张类型和质量在系统打印窗口中选择；Mac 可在应用中选择驱动提供的介质和质量。

## ICC 与预览

**预览始终保留原照片色彩；ICC 和颜色微调作用于打印输出。** “预览尺寸补偿”只校准预览中的大小和裁切，不缩放打印照片。

微调默认全部为 **0**，表示在所选 ICC 基础上不再额外调整。另存的 ICC 已包含微调，导入后无需重复输入相同数值；另存后由用户自行导入，不自动加入列表。

内置 ICC 是个人试印形成的经验配置。其他兄弟机型、纸张、墨水或驱动可能需要不同配置；首次使用请先试印。使用应用管理颜色时，请核对驱动额外的颜色调整，避免重复调色。支持 RGB ICC，暂不支持 CMYK ICC。

更多说明：[应用使用指南](quickprint/README.md) · [内置 ICC 说明](docs/ICC.md) · [更新记录](CHANGELOG.md)

## 开发与构建

使用 Python 3.12，在项目根目录运行：

```sh
python -m venv .venv
# macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python quickprint/app.py
```

测试与打包：

```sh
cd quickprint
python -m pytest -q
python build.py
```

在目标操作系统构建，输出位于 `quickprint/release/`。GitHub Actions 会对 Windows x64、Mac Apple Silicon 和 Intel Mac 分别运行测试、构建应用并执行打包后自检。测试使用合成图像，不发送实物打印任务。

## 许可与来源

应用源码使用 [MIT 许可](LICENSE)。第三方组件许可见 [THIRD_PARTY.md](quickprint/THIRD_PARTY.md)。内置 ICC 保留原有版权与来源说明，不适用应用源码的 MIT 许可。本项目与 Brother、Kodak、Apple 无隶属关系。
