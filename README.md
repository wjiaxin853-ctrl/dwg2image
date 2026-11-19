# dwg2image

**从 Python 读取 DWG 图纸，导出 DXF 或 PNG。**

[![PyPI](https://img.shields.io/pypi/v/dwg2image)](https://pypi.org/project/dwg2image/)
[![Python](https://img.shields.io/pypi/pyversions/dwg2image)](https://pypi.org/project/dwg2image/)

**0.2 开始提供独立 Python DWG 解码器**：直接解析对象索引、位流、句柄、基础实体、图层和文字样式，使用 ezdxf 输出 DXF、Matplotlib 渲染 PNG。

> **实验阶段，支持范围有限。** 独立解码器支持 AC1015（R2000）以及实验性的 AC1012（R13）、AC1014（R14）、AC1024（R2010）、AC1027（R2013）、AC1032（R2018）解析路径。样例验证不代表通用版本兼容；视觉结果也不保证与 ODA 完全一致。未支持的模型空间或被引用块内容会明确报错。

[安装](#安装) · [快速上手](#快速上手) · [支持范围](#支持范围) · [API](#api) · [验证](#验证与开发) · [问题反馈](https://github.com/wjiaxin853-ctrl/dwg2image/issues)

## 安装

需要 **Python 3.10+**：

```bash
pip install --upgrade dwg2image
```

项目代码是 Python，wheel 为 `py3-none-any`。ezdxf、Matplotlib、Pillow 及其依赖中仍有原生扩展，平台可用性还取决于这些依赖。

## 快速上手

### DWG → PNG

对于支持范围内的 AC1012、AC1014、AC1015、AC1024、AC1027 或 AC1032 图纸：

```python
from dwg2image import dwg_to_png

image = dwg_to_png("drawing.dwg", "drawing.png", dpi=300)
print(image)
```

### DWG → DXF

```python
from dwg2image import dwg_to_dxf

dwg_to_dxf("drawing.dwg", "drawing.dxf")
```

### DXF → PNG

```python
from dwg2image import dxf_to_png

dxf_to_png("drawing.dxf", "drawing.png", dpi=300, background="#FFFFFF")
```

### 检查支持范围

```python
from dwg2image import read_dwg

drawing = read_dwg("drawing.dwg")
print(drawing.object_count)
print(drawing.unsupported_modelspace)
for entity in drawing.modelspace():
    print(entity["type"], entity["handle"], entity["attributes"])
```

`read_dwg()` 返回已解析的事实和未支持类型的统计，允许检查部分结果。它不代表所有对象都已解码；导出接口还会检查被引用块，遇到未支持内容时抛出 `UnsupportedDwgError`。

## 支持范围

| 内容 | 独立 Python 路径 |
| --- | --- |
| AC1012（R13）、AC1014（R14） | 实验性读取；对象索引、公共实体头和 TEXT/LEADER/MTEXT 的 R13-R14 负载 |
| AC1015（R2000） | 对象索引、CRC、对象头、公共实体头与句柄 |
| LINE、CIRCLE、ARC、POINT | 坐标、半径、角度、厚度和拉伸方向 |
| RAY、XLINE | 起点和方向；PNG 渲染使用有限长度近似 |
| TEXT | 字符、位置、高度、旋转、对齐、样式引用 |
| MTEXT | 多行文字、位置、方向、尺寸、行距与样式引用 |
| ELLIPSE | 中心、主轴、轴比与参数范围 |
| HATCH | 多段线和直线边界、图案线、种子点与边界引用；曲线边界导出暂未支持 |
| LWPOLYLINE | 顶点、闭合、bulge、宽度和标高 |
| SOLID、TRACE | 四顶点和厚度 |
| INSERT | 基本块引用及嵌套块，支持带 ATTRIB 的引用 |
| WIPEOUT | R2018 剪裁边界和图块内实体；复杂取景与遮挡顺序仍可能影响视觉结果 |
| AC1024（R2010） | 实验性读取；部分文字和实体尚未支持 |
| AC1027（R2013） | 实验性读取；部分文字和实体尚未支持 |
| AC1032（R2018） | 实验性读取；对照 46 张本地样例完成解析和 PNG 输出，不代表其他 R2018 图纸均受支持 |
| 图层、文字样式、简单线型 | 名称、颜色、字体引用、线宽及简单虚线模式 |
| 常用标注、SPLINE、旧式 POLYLINE | 已实现线性/对齐/角度/半径/直径/坐标标注、SPLINE 和旧式 POLYLINE；未覆盖的变体仍明确报错 |
| 3DFACE、SHAPE、REGION、3DSOLID、MULTILEADER、IMAGE、PDFUNDERLAY 等 | 未实现，相关内容导出时明确报错 |
| 外部参照 | 导出 DWG 内缓存的块图元并保留 xref_path；块内实体未实现时明确报错 |
| 复杂线型、循环块引用 | 未实现，使用时明确报错 |
| 未实现实体（SHAPE/REGION/3DSOLID/MULTILEADER/IMAGE 等） | 默认 `strict=True` 报错；`strict=False` 时跳过并在 `read_dwg()` 计数 |
| 其他 DWG 版本 | 尚未独立实现 |

默认使用 **300 DPI、CAD 布局背景**，保留源颜色，并设置最小可见线宽。可显式传 `background="#FFFFFF"` 使用白底。

图片渲染**模型空间**。尚未恢复全局 Header 变量（包括源单位、全局线型比例）；独立 DXF 输出明确使用无单位，而非猜测物理单位。没有实现完整的图纸空间、视口、打印配置及所有 CAD 语义。自定义字体缺失时可能替换字体，不能据此承诺完整视觉保真。

R2018 文件中加密的 `AcDb:FileDepList` 未解码；依赖该清单的外部资源不会由本库加载。外部参照块若在 DWG 内缓存了图元，会随块一起导出并保留 `xref_path`；没有缓存或块内含未实现实体时明确报错。

目前明确支持的源代码页为 ASCII、Windows 1252、932、936、949、950；其他代码页会报错，不会猜测编码。

## API

转换接口接受字符串或 `pathlib.Path`，返回输出 `Path`。输出父目录自动创建，已有文件不会被覆盖。`dwg_to_png()` 的中间 DXF 自动清理。

| 参数 | 适用接口 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `source` | 三个转换接口 | 必填 | 输入文件 |
| `destination` | 三个转换接口 | 必填 | 输出文件；图片必须为 `.png` |
| `dpi` | PNG 接口 | `300` | 正整数；不是固定像素宽高 |
| `background` | PNG 接口 | `None` | 跟随 CAD 布局背景，通常为深色；传入颜色可覆盖 |
其他公开接口：`inspect_dwg(path)` 提供文件头与摘要，`inspect_dxf(path)` 提供实体统计和审计结果。

主要异常包括：

- `UnsupportedDwgError`：版本、实体或资源语义未支持。
- `DwgFormatError`：位流截断、对象身份不一致或 CRC 错误。
- `FileExistsError` / `FileNotFoundError`：目标已存在 / 输入不存在。
- `ValueError`：错误的 DPI、扩展名或参数组合。

## 命令行

```bash
dwg2image inspect drawing.dwg
dwg2image check-dxf drawing.dxf
dwg2image convert drawing.dwg drawing.dxf
```

`convert` 使用独立 Python 解码器输出 DXF。PNG 目前使用 Python API。

## 验证与开发

独立实现以指定 ODA AppImage 的 REA 目标/导出符号检查、公开 [DWG 格式规范](https://www.opendesign.com/files/guestdownloads/OpenDesign_Specification_for_.dwg_files.pdf)及真实样例对照为基础。REA 已定位转换和位流入口；受当前引擎环境限制，**尚未取得 Ghidra 函数伪代码**，不把符号定位等同于算法全部恢复。

当前验证：

- 25 份 AC1015 样例通过初版对象/已支持实体读取检查；这不等于 25 份都能完整导出。
- 46 份 AC1032（R2018）本地样例当前均可解析并生成 PNG；其中补上了 WIPEOUT 和一份 AcDs SAB 3DSOLID。`417. Free CAD Details of Glass and Metal Railings for House Design` 的取景与 ODA 图片仍有明显差异，成功生成不等于视觉等价。
- 3 份样例的 2384 个 LINE/CIRCLE/ARC/POINT 按句柄核对基础几何，最大数值差约 `6.9e-13`；ABB 对照中有 66 个图层名与 ODA 审计导出不同，保留源文件的图层事实。
- `1 刀开关.dwg` 的模型空间 62 个实体可完整导出，DXF 审计错误为 0。
- **macOS ARM64** 已验证独立解码与 PNG 渲染；**Linux x86-64、Linux ARM64** 已在没有 ODA 的环境中验证同一图纸解出 62 个实体（仅解码，未验证这些环境的 PNG 依赖）。Windows 尚未运行验证。CI 配置暂未上线（当前 GitHub 凭证缺少 workflow 权限），不据此宣称所有平台、格式及实体均已验证。

```bash
python3 -m venv .venv
.venv/bin/pip install -e . build twine
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

欢迎通过 [Issue](https://github.com/wjiaxin853-ctrl/dwg2image/issues) 提交可公开的最小样例、系统/CPU 架构、版本、调用代码及完整错误信息。Matplotlib 不保证多线程绘图安全，服务端并发建议使用独立进程。

## 许可证

当前仓库尚未声明开源许可证。

## 0.3.0 修复

- 修复 `decode_entity(..., legacy=...)` 参数缺失导致 R13/R14/R2000 文件直接 `TypeError` 的问题。
- 按 DWG 规范 20.4.3 / 20.4.46 / 20.4.47 补齐 R13/R14 的 TEXT、MTEXT、LEADER 负载；`v.dwg` 的文本坐标与 ODA DXF 逐字段一致。
- R2010+ LEADER 在 MTEXT/无标注时不再读取文本盒字段；AC1018/AC1021 仍保留该字段。
- 实现 R2018 MTEXT 背景填充（scale、CmColor、transparency），并映射到 ezdxf 的 `bg_fill*` 属性。
- 没有几何块的 DIMENSION 允许省略 `geometry`，与 ODA 导出一致。
- 外部参照块改为导出缓存图元和 `xref_path`，不再一律报错。
- 声明代码页解码失败时，对合法 UTF-8 文本做一次回退（不改变正常 GBK 文本）。
- 以 128 个历史失败样例回归：成功数 86 → 94（严格模式），无回归。
- 新增 `strict=False` 降级模式：跳过当前未实现实体而不是整份失败，`read_dwg()` 的未支持计数可查；降级模式下 117/128 可出图（94 个完整、23 个降级，11 个 pre-R13 老版本仍失败）。默认仍为 `strict=True`。
- 补充 3DFACE、SHAPE 字段读取（SHAPE 需外部 SHX，记录为未支持）、角度标注、R13/R14 DIMENSION/INSERT、R13/R14 REGION 保护。详见 `doc/ODA逆向与失败样例修复.md`。

## 0.2.1 修复

修复 DXF 写出接口默认值覆盖 LWPOLYLINE 闭合标志的问题，恢复方框和轮廓的闭合边；新增闭合/开放/plinegen 的序列化回归测试。默认预览改为 300 DPI、跟随 CAD 布局背景，并保持高 DPI 下线条可见。以用户提供的同名 PNG 做视觉核对；字体缺失导致的字形差异尚未消除。

## 当前开发进展

新增 AC1015 MTEXT、ELLIPSE 和部分 HATCH 支持。5 张样例的 42 个 MTEXT 与 ODA 导出的 DXF 按句柄核对字段一致；ABB 的 12 个填充边界也完成顶点、闭合和标志核对。R2018 独立解析路径已随 0.2.2 发布，仍属实验性。0.3.0 起补充了 R13/R14 的 TEXT/MTEXT/LEADER、R2018 MTEXT 背景、无几何块标注和缓存外部参照；SHAPE、REGION、3DSOLID、MULTILEADER、IMAGE 等仍会拒绝导出。
