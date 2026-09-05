# 轻印 · Quick Photo Print

一个离线的 Windows / macOS 单张照片打印小工具。支持常见相纸及自定义尺寸，内置 Brother-T735DW-Kodak-Glossy（提亮 165）ICC，也可导入其他 RGB 输出 ICC / ICM。

[下载 Windows / Apple Silicon Mac / Intel Mac 版本](https://github.com/Godles-lab/Brother-T735DW-Kodak-Glossy/releases/tag/quickprint-v0.1.0)

## 使用

1. 打开或拖入 JPG、PNG、TIFF、BMP、WebP 照片。照片只在本机读取，不上传，也不会写入程序目录。RAW / HEIC 请先导出为带色彩配置的 JPG。
2. 选择相纸尺寸或输入毫米数，必要时横竖切换。
3. 选择“铺满区域”或“完整显示”。拖动照片调整位置，滑块或滚轮调整缩放，旋转按钮每次顺时针 90°。
4. 设置四边白边并点“应用白边”，或输入距左、距上、区域宽和区域高。Shift + 拖动移动区域，拖绿色右下角方块调整区域大小。区域外不打印照片。
5. 选择 ICC、渲染意图和黑点补偿，或者选择由打印机管理颜色。
6. 点“打印”，在系统窗口核对打印机、纸张尺寸、相纸类型、质量、份数和无边距选项。纸张尺寸与预览不一致时，工具会停止提交，避免错误缩放。

“保存当前预设”会记住一套尺寸、构图和 ICC 参数，下次启动恢复；不记录或自动重开照片。自定义 ICC 路径只保存在本机系统设置中。预设不保存打印驱动内的相纸类型和质量，请在系统窗口核对。

导出 PNG 用于查看排版，文件为 sRGB，**未应用打印 ICC**，并清除源照片 EXIF 元数据。界面预览也是排版预览，不是纸张色彩打样。

## 颜色与无边距

- 内嵌源 ICC 会先转换为 sRGB；无源 ICC 的 RGB 照片按 sRGB 处理。
- 选择输出 ICC 时，Little CMS 实际执行颜色转换，再提交 RGB 光栅给系统打印引擎。仅支持 RGB 输出 ICC，CMYK 输出配置会拒绝加载。
- 使用 ICC 时，请关闭驱动额外的色彩增强，避免与之前的 Windows 红绿蓝调整叠加。
- 不同系统/驱动可能继续进行颜色处理，尤其 macOS ColorSync / AirPrint。**目前尚未验证实物打印与 Photoshop 完全一致，先用一张相纸对比。** 不能把软件数值测试通过当成实物色准保证。
- “铺满区域”表示排版裁切。真正打印到纸边，需要打印机/驱动支持该相纸尺寸的无边距模式；本工具不能绕过硬件不可打印边距。
- v0.1 是首个试用版，自动测试涵盖几何、ICC、EXIF、界面控制及 PDF 输出；实物打印需用户验证。

## 下载与运行

在 GitHub Releases 下载对应平台 ZIP。Windows 解压整个目录后运行 `QuickPhotoPrint.exe`，不要只拷走 exe。Mac 解压后将 `QuickPhotoPrint.app` 放入“应用程序”。首版没有商业代码签名或 Apple 公证；macOS 如阻止打开，可在“系统设置 → 隐私与安全性”中核对来源后允许打开，无需关闭系统安全保护。

支持目标：Windows 10/11 x64、macOS 13+ Apple Silicon / Intel。GitHub 构建分别在目标操作系统运行测试和打包；无需安装 Python。

## 开发

需要 Python 3.12。在此目录运行：

```sh
python -m pip install -r requirements.txt
python app.py
```

测试与构建：

```sh
python -m pip install pytest==9.0.2 pypdf==6.7.1 pyinstaller==6.19.0
python -m pytest -q
python build.py
```

Windows exe 必须在 Windows 构建，macOS app 必须在 macOS 构建。无需提交个人照片作为样本；测试使用程序生成的纯色图。

源代码使用 MIT 许可；第三方库及 ICC 说明见 `THIRD_PARTY.md` 和仓库根目录 README。
