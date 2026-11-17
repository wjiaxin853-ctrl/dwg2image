# dwg2image

将 DWG 图纸转换为 PNG 的 Python 库，也支持 DWG→DXF 和 DXF→PNG。

DWG 解码依赖用户自行准备的 **ODA File Converter**，本库不包含或自动下载 ODA。已有 DXF 转 PNG 不需要 ODA 或 Docker。Python 版本要求：3.10+。

## 安装

通过 PyPI 安装：

```sh
pip install dwg2image
```

## 使用

已有 DXF 转图片：

```python
from dwg2image import dxf_to_png

image = dxf_to_png("drawing.dxf", "drawing.png", dpi=150)
```

DWG 转图片：

```python
from dwg2image import dwg_to_png

image = dwg_to_png(
    "drawing.dwg",
    "drawing.png",
    appdir="/absolute/path/to/squashfs-root",
    docker_image="dwg2image-runtime:local",
    dpi=150,
)
```

仅转换为 DXF：

```python
from dwg2image import dwg_to_dxf

dxf = dwg_to_dxf(
    "drawing.dwg", "drawing.dxf",
    appdir="/absolute/path/to/squashfs-root",
    docker_image="dwg2image-runtime:local",
)
```

三个接口接受字符串或 `Path`，返回输出 `Path`；已有目标文件不会覆盖，抛出 `FileExistsError`。`dwg_to_png()` 自动清理中间 DXF。ODA 非零退出抛出 `RuntimeError`，超时抛出 `subprocess.TimeoutExpired`；超时参数为 `timeout=300`（秒）。

## 准备 ODA 运行环境

当前适配 Linux x86-64 ODA AppImage 的解包目录，要求包含 `usr/bin/ODAFileConverter` 及随包共享库和 Qt 插件。在 Linux 解包：

```sh
chmod +x ODAFileConverter.AppImage
./ODAFileConverter.AppImage --appimage-extract
```

将得到的 `squashfs-root` 绝对路径传入 `appdir`。源码目录中的 `artifacts/appdir` 只是本地准备的运行依赖，不随 Git 或 pip 安装包分发。

原生 Linux x86-64 需要 Xvfb、xauth 及共享库（参考 Dockerfile），可以省略 `docker_image` 参数。

macOS 或使用容器的 Linux 主机，先从仓库构建运行镜像：

```sh
git clone https://github.com/wjiaxin853-ctrl/dwg2image.git
cd dwg2image
docker build --platform linux/amd64 -t dwg2image-runtime:local .
```

Docker 必须能访问 `appdir` 和系统临时目录；macOS ARM 还需支持 Linux x86-64 模拟。容器转换期间禁用网络，ODA 目录只读挂载。Dockerfile 只安装运行依赖，不包含 ODA。

## 范围与限制

- PNG 渲染模型空间。字体替换、外部参照及不支持的实体可能影响显示，不保证所有 CAD 内容保真。
- 当前入口识别 AC1015、AC1032 文件头，其他 DWG 版本尚未支持。
- Matplotlib 绘图接口不保证多线程并发安全；服务端并发调用建议使用独立进程。
- 已提供 `inspect_dwg()` 和 `inspect_dxf()` 检查接口；CLI 保留 `inspect`、`check-dxf` 和 `convert` 子命令，运行 `dwg2image --help` 查看参数。

## 开发与打包

```sh
python3 -m venv .venv
.venv/bin/pip install -e . build twine
.venv/bin/python -m unittest -v
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

发布使用 `python -m twine upload dist/*`，需要 PyPI 项目权限和发布凭证。

已验证独立虚拟环境安装 wheel 后从源码目录之外导入，使用本地 ODA 与 Docker 完成一次真实 DWG→PNG 转换。测试包含 DXF 渲染与已有文件保护；尚未进行全量图纸或几何保真验证。
