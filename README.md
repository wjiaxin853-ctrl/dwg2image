# dwg2image

**将 CAD 图纸转换为图片，接入你的 Python 项目。**

[![PyPI](https://img.shields.io/pypi/v/dwg2image)](https://pypi.org/project/dwg2image/)
[![Python](https://img.shields.io/pypi/pyversions/dwg2image)](https://pypi.org/project/dwg2image/)

**dwg2image** 提供 DWG→PNG、DWG→DXF 和 DXF→PNG 三个 Python 接口，适合图纸预览、文档处理和批量转换脚本。DWG 通过用户配置的 ODA File Converter 转为 DXF，再由 ezdxf 与 Matplotlib 渲染为 PNG。

[安装](#安装) · [快速上手](#快速上手) · [API](#api) · [运行环境](#运行环境) · [常见问题](#常见问题) · [PyPI](https://pypi.org/project/dwg2image/) · [问题反馈](https://github.com/wjiaxin853-ctrl/dwg2image/issues)

## 能做什么

- **直接调用**：安装后 `from dwg2image import dwg_to_png`，传入文件路径即可集成。
- **三种转换**：从 DWG 导出 PNG 或 DXF，也可以单独渲染已有 DXF。
- **调整图片**：设置 DPI 和背景色，默认输出白底 PNG。
- **保护已有文件**：目标文件已存在时抛出异常；DWG→PNG 的中间 DXF 自动清理。
- **选择运行方式**：配置原生 Linux x86-64 ODA，或通过 Docker 运行转换器。

> **依赖说明**：DXF→PNG 安装 Python 包后即可使用。DWG 输入还需要自行准备 ODA File Converter；本包不包含、不自动下载 ODA，也不是独立的 DWG 解码器。

## 安装

需要 **Python 3.10+**：

```bash
pip install --upgrade dwg2image
```

安装会一并获取 ezdxf、Matplotlib、Pillow 及其 Python 依赖。使用 DWG 输入前，请先完成下方的[运行环境配置](#运行环境)。

## 快速上手

### DWG → PNG

以下示例使用已准备好的 ODA 解包目录和 Docker 运行镜像：

```python
from dwg2image import dwg_to_png

image = dwg_to_png(
    "drawing.dwg",
    "drawing.png",
    appdir="/absolute/path/to/squashfs-root",
    docker_image="dwg2image-runtime:local",
    dpi=150,
    background="#FFFFFF",
)
print(image)  # Path("drawing.png")
```

在已经安装所需共享库和 Xvfb 的原生 Linux x86-64 上，省略 `docker_image` 参数即可。

### DXF → PNG

已有 DXF 时，不需要 ODA 或 Docker：

```python
from dwg2image import dxf_to_png

image = dxf_to_png("drawing.dxf", "drawing.png", dpi=150)
```

### DWG → DXF

将图纸转换为中间交换格式，供其他 CAD 工具或数据处理流程使用：

```python
from dwg2image import dwg_to_dxf

dxf = dwg_to_dxf(
    "drawing.dwg",
    "drawing.dxf",
    appdir="/absolute/path/to/squashfs-root",
    docker_image="dwg2image-runtime:local",
)
```

## 支持的转换

| 输入 | 输出 | Python 接口 | 额外运行要求 |
| --- | --- | --- | --- |
| DWG | PNG | `dwg_to_png()` | ODA；非原生 Linux x86-64 使用 Docker |
| DWG | DXF | `dwg_to_dxf()` | ODA；非原生 Linux x86-64 使用 Docker |
| DXF | PNG | `dxf_to_png()` | 无外部 CAD 程序要求 |

当前 DWG 入口识别 **AC1015、AC1032** 文件头，其他版本会被拒绝。DXF 导出版本为 ACAD2018。PNG 渲染模型空间，不包含完整的图纸空间布局导出。

## API

三个转换函数都接受字符串或 `pathlib.Path`，成功时返回输出文件的 `Path`。父目录会自动创建，已有目标文件不会被覆盖。

| 参数 | 适用接口 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `source` | 全部转换接口 | 必填 | 输入文件路径 |
| `destination` | 全部转换接口 | 必填 | 输出路径；图片必须使用 `.png` 后缀 |
| `appdir` | DWG 转换接口 | 必填 | 解包后的 Linux x86-64 ODA 目录 |
| `docker_image` | DWG 转换接口 | `None` | Docker 镜像名；省略时调用本机 Linux 转换器 |
| `timeout` | DWG 转换接口 | `300` | ODA 转换等待上限，单位为秒，不包括 PNG 渲染 |
| `dpi` | PNG 输出接口 | `150` | 渲染分辨率，必须为正整数；不是固定像素宽高 |
| `background` | PNG 输出接口 | `"#FFFFFF"` | 图片背景色 |

`source`、`destination` 以外的参数通过关键字传入。

常见异常：

- `FileExistsError`：目标文件已存在。
- `FileNotFoundError`：输入文件或 ODA 程序不存在。
- `ValueError`：不支持的 DWG 文件头、错误的图片后缀或 DPI。
- `RuntimeError`：ODA 返回失败、没有生成预期 DXF，或本机不满足运行平台要求。
- `subprocess.TimeoutExpired`：ODA 调用超时。

无效 DXF 还可能抛出 ezdxf 的解析异常。库不会把转换失败伪装为成功输出。

此外可通过 `inspect_dwg(path)` 检查 DWG 文件头、摘要和部分节目录，通过 `inspect_dxf(path)` 获取 DXF 实体统计与审计结果。这些检查不等于几何保真验证。

## 运行环境

### 1. 准备 ODA

从 [ODA 官网](https://www.opendesign.com/guestfiles/oda_file_converter)自行获取 Linux x86-64 File Converter AppImage，并在 Linux 中解包。以下文件名为示例，请替换为实际下载的文件名：

```bash
chmod +x ODAFileConverter.AppImage
./ODAFileConverter.AppImage --appimage-extract
```

解包目录应包含：

```text
squashfs-root/
└── usr/
    ├── bin/ODAFileConverter
    ├── lib/
    └── plugins/
```

保留随包共享库和 Qt 插件，将整个 `squashfs-root` 的绝对路径传给 `appdir`。macOS 不能直接运行 Linux AppImage，需要在 Linux 环境中完成解包后使用其目录。

### 2. 选择运行方式

**Docker（macOS 或使用容器的 Linux 主机）**

从仓库构建运行镜像：

```bash
git clone https://github.com/wjiaxin853-ctrl/dwg2image.git
cd dwg2image
docker build --platform linux/amd64 -t dwg2image-runtime:local .
```

构建完成后，将 `docker_image="dwg2image-runtime:local"` 传给 DWG 转换接口。

Dockerfile 安装图形、字体与虚拟显示依赖，不包含 ODA。转换时容器禁用网络，ODA 目录以只读方式挂载。Docker 需要能访问 ODA 目录与系统临时目录；macOS ARM 还需启用 Linux x86-64 模拟支持。

**原生 Linux x86-64**

Ubuntu 22.04 可按本仓库 Dockerfile 准备依赖：

```bash
sudo apt-get update
sudo apt-get install -y libgl1 libfontconfig1 libx11-6 libfreetype6 xvfb xauth
```

随后只传 `appdir`，省略 `docker_image`。转换器通过 Xvfb 获得虚拟显示，无需桌面会话。

### 已验证范围

已在 macOS ARM 的 Docker x86-64 模拟环境中，使用指定 ODA AppImage 完成 DWG→DXF 和 DWG→PNG 验证，并验证从 PyPI 安装后导入。原生 Linux 路径尚未进行实机验证；未验证 Windows DWG 转换及任意 ODA 版本兼容性。

## 命令行

安装后可使用 `dwg2image`，也可运行 `python -m dwg2image`：

```bash
dwg2image --help
dwg2image inspect drawing.dwg
dwg2image check-dxf drawing.dxf
dwg2image convert drawing.dwg drawing.dxf \
  --appdir /absolute/path/to/squashfs-root \
  --docker-image dwg2image-runtime:local
```

当前 CLI 的 `convert` 输出 DXF；PNG 转换使用上方 Python API。

## 常见问题

**安装后能直接转换 DWG 吗？**

还需要准备 ODA 运行环境。若输入已经是 DXF，直接调用 `dxf_to_png()` 即可。

**为什么中文、字体或某些图块显示不同？**

渲染结果受字体、外部参照及实体支持情况影响。当前不保证代理对象、动态块和所有 CAD 内容的显示保真；可读取的 DXF 或有效 PNG 也不代表几何完全一致。

**能同时转换多个文件吗？**

可以在脚本中顺序调用。Matplotlib 不保证多线程绘图安全，服务端并发转换请使用独立进程，并按机器资源控制并发量。

**支持 JPG、PDF、SVG 或图纸空间吗？**

当前公开转换接口输出 PNG 或 DXF，图片只渲染模型空间。其他格式和完整布局导出尚未提供。

## 开发与反馈

```bash
git clone https://github.com/wjiaxin853-ctrl/dwg2image.git
cd dwg2image
python3 -m venv .venv
.venv/bin/pip install -e . build twine
.venv/bin/python -m unittest -v
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

测试覆盖 DXF→PNG 渲染、已有文件保护和部分 DWG 文件头解析边界。真实 DWG 转换验证需要另外配置 ODA 与运行环境。

欢迎提交 [Issue](https://github.com/wjiaxin853-ctrl/dwg2image/issues) 或 [Pull Request](https://github.com/wjiaxin853-ctrl/dwg2image/pulls)。报告问题时请附 Python 与操作系统版本、dwg2image 与 ODA 版本、最小调用代码、完整错误信息，以及可以公开的最小样例。

## 许可证

当前仓库尚未声明开源许可证。ODA File Converter 是独立的第三方软件，其使用条款由 ODA 提供；pip 安装包不分发 ODA 程序。
