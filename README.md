# Brother-T735DW-Kodak-Glossy

用于 **Brother DCP-T735DW + 柯达高光照片纸** 的个人调色 ICC 配置文件，主要针对照片打印偏红、偏深的问题。

[下载正式版 ICC](https://github.com/Godles-lab/Brother-T735DW-Kodak-Glossy/releases/latest/download/Brother-T735DW-Kodak-Glossy.icc) · [查看版本](https://github.com/Godles-lab/Brother-T735DW-Kodak-Glossy/releases)

## 适用情况

本配置根据 macOS 上 Photoshop 的实际试印反馈逐步调整，使用的相纸尺寸为 89 × 127 mm。尺寸本身不限制 ICC 的使用，但纸张种类、墨水、打印质量和驱动会影响结果。

这是个人经验补偿配置，不是 Brother 或 Kodak 官方配置，也不是用测色仪建立的打印机校准文件。已获满意反馈的是前一阶段的颜色效果；本正式版在此基础上继续提亮至 165，尚未记录该最终亮度版本的实物试印反馈。其他设备或纸张批次请先小幅试印。

## macOS + Photoshop

1. 将 ICC 复制到 `~/Library/ColorSync/Profiles/`。如果目录不存在，可以自行创建；也可以放入 `/Library/ColorSync/Profiles/`（可能需要管理员权限）。
2. 如果安装过同名旧版，替换旧文件，重新启动 Photoshop。
3. 打开带有正确嵌入色彩描述文件的原图，进入“文件 → 打印”。
4. “颜色处理”选择 **Photoshop 管理颜色**，“打印机配置文件”选择 **Brother-T735DW-Kodak-Glossy**。
5. 本次调试使用相对比色、关闭黑点补偿。保持与试印一致的纸张类型、质量及驱动设置，不再叠加用于纠偏的曲线或颜色增强。

请将 ICC 选作打印输出配置，不要通过“指定配置文件”把原图的 sRGB 等源配置替换成它。

## Windows

右键 ICC 文件，选择“安装配置文件”，重启 Photoshop，按上面的 Photoshop 流程选择它。

ICC 文件可跨平台使用，但 Windows 驱动与 Mac 打印流程不同，不能保证直接得到相同颜色。先试印一张；使用 Photoshop 管理颜色时，关闭驱动额外的颜色调整（若驱动支持），不要叠加此前教程中的红 −20、绿 +15、蓝 +20 等补偿。仅安装 ICC 不会让所有应用自动使用它。

## Windows：直接使用 Brother 驱动调整颜色

如果希望按分享者此前满意的 Windows 设置打印，可以在 Brother 驱动的“色彩管理 / 颜色增强”调整页面输入以下数值（入口名称可能随驱动版本不同）：

| 选项 | 数值 |
| --- | ---: |
| 色彩浓度 | 0 |
| 白平衡 | 0 |
| 亮度 | +1 |
| 对比度 | +1 |
| 红（R） | −20 |
| 绿（G） | +15 |
| 蓝（B） | +20 |

以上数值按分享者提供的 Windows 设置截图逐项抄录，适用于其 Brother DCP-T735DW + 柯达高光照片纸的试印经验。纸张类型按实际高光相纸选择，先试印确认效果。

**这套驱动调整与本仓库 ICC 是两种可选用法，请勿叠加。** 使用上述数值时，让打印机驱动管理颜色，不再选择本仓库 ICC 做输出补偿；如果使用本仓库 ICC，则按前文 Photoshop 流程设置，关闭驱动额外的颜色调整。

## Mac 不使用 Photoshop

可以尝试系统自带的“色彩同步实用工具”：

1. 在“设备 → 打印机”中找到 Brother，记录原来的描述文件。如果支持修改“当前描述文件”，选择“其他”，指定此 ICC。
2. 用该工具的“文件 → 打开”打开照片，再选择“文件 → 打印”。
3. 在色彩同步实用工具的打印选项中，选择“预匹配至打印机描述文件”，意图选“相对比色”。
4. 保持纸张、质量一致，先与 Photoshop 试印结果对照。

具体选项取决于 macOS 和驱动；若 AirPrint 不提供自定义描述文件选项，可继续使用 Photoshop。更改设备默认描述文件可能影响其他采用该设备配置的应用，需要时恢复原设置。

参考：[Apple：更改设备描述文件](https://support.apple.com/zh-cn/guide/colorsync-utility/csync005/mac)、[Apple：直接打印图像](https://support.apple.com/zh-cn/guide/colorsync-utility/csync4a8f2e5/mac)、[Adobe：Photoshop 打印颜色管理](https://helpx.adobe.com/photoshop/using/printing-color-management-photoshop1.html)。

## 版本信息

- 文件及内部显示名称：`Brother-T735DW-Kodak-Glossy`
- 正式版：`v1.0.0`
- 调整曲线输入中点：128
- 提亮曲线输出中点：165
- 各通道补偿曲线输出中点：R 112 / G 131 / B 125
- 保留此前轻微对比度调整

这些数值是生成补偿曲线的参数，不是要求在打印驱动中再次输入的滑块数值。

文件已通过 macOS ICC 结构校验和生成转换的数值检查；这些检查不等于实物色准认证。下载后可用 `SHA256SUMS` 校验文件。

## 来源说明

配置生成过程使用了 Apple Generic RGB Profile 的色彩转换，ICC 内保留了相应来源说明（Copyright 2007 Apple Inc.）。仓库未附带 Apple 原始配置文件。本项目与 Brother、Kodak、Apple 无隶属关系。
