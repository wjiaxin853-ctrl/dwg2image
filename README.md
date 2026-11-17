# dwg2image

项目目标是将 DWG 图纸转换为图片。当前目录包含初步逆向成果和 Python 验证原型，已验证 DWG→DXF 阶段；已接入 DXF→PNG 库接口。**尚未独立重写 DWG 几何解码器**；`convert` 仍执行用户提供的 ODA 二进制。`inspect` 和 `check-dxf` 不执行 ODA。没有修改原始 AppImage、demo 或原项目输出。

## Python 库安装与调用

需要 Python 3.10+。目前尚未发布到 PyPI，可直接从本仓库安装：

```sh
pip install "git+https://github.com/wjiaxin853-ctrl/dwg2image.git"
```

仅渲染已有 DXF 不需要 ODA 或 Docker：

```python
from dwg2image import dxf_to_png

image = dxf_to_png("drawing.dxf", "drawing.png", dpi=150)
```

DWG 输入需要另外准备 ODA（解包方式见下文）。Linux x86-64 需 Xvfb 和相关共享库；macOS 可使用本项目 Dockerfile 构建的运行镜像：

```python
from dwg2image import dwg_to_png, dwg_to_dxf

image = dwg_to_png(
    "drawing.dwg", "drawing.png",
    appdir="/absolute/path/to/extracted/appdir",
    docker_image="dwg2image-runtime:local",  # 原生 Linux x86-64 可省略
    dpi=150,
)
```

三个转换接口接受字符串或 `Path`，返回输出 `Path`，已有目标文件会抛出 `FileExistsError`。ODA 非零退出会抛出 `RuntimeError`，超时抛出 `subprocess.TimeoutExpired`。`dwg_to_png` 的中间 DXF 自动清理。

PNG 只渲染模型空间；字体替换、外部参照和不支持的实体可能影响显示。DWG 转换仍调用闭源 ODA，本包不包含或自动下载 ODA。Matplotlib 绘图接口不保证多线程并发安全，服务端并发建议使用独立进程。

安装后可运行 `dwg2image --help` 或 `python -m dwg2image --help`；现有 CLI 保留 inspect/check-dxf/convert 子命令。

发布准备：

```sh
python -m pip install build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

最后一步需要 PyPI 账户的项目权限和发布凭证，并确认名称可用。尚未执行上传；发布成功后才可使用 `pip install dwg2image`。没有自行添加开源许可证，发布前应由项目所有者选择许可证。

运行库只安装 ezdxf、Matplotlib、Pillow 及其依赖；逆向脚本的额外依赖使用 `pip install ".[analysis]"` 安装。wheel 不含 demo、分析证据、ODA 程序或本地输出。

## 已定位的实现

目标：`ODAFileConverter_QT6_lnxX64_8.3dll_27.1.AppImage`。
SHA-256：`cb77a106354af98a1d355ba0191160aca3f90cb020946803e7c8132cba434dfc`。

- SquashFS 4.0 数据区偏移 **189632**，使用 ZLIB；7-Zip 解包得到 184 个文件。
- `usr/bin/ODAFileConverter` 是保留符号表的 Linux x86-64 ELF。AppRun 也是 ELF，不能当 shell 脚本读取。
- `main` 位于 `0x41e872`；`CConvertor::convertFile` 位于 `0x42c1fe`；`startConvertion` 位于 `0x42d9c0`。
- `startConvertion` 的 `0x42f242` 直接调用 `convertFile`。
- `convertFile` 的 `0x42cac4` 调用 `OdDbDatabase::auditDatabase`；`0x42ce33` 调用 `OdDbDatabase::writeFile`。读取阶段存在间接调用，尚未逐个恢复其运行时目标。
- `TD_DbIO.tx` 导出 `OdDbDatabase_readFile`（`0x103b34`）、`OdDbDatabase_writeFile`（`0x104fba`）、R18 解压入口（`0x17a9c8`）和 R21 解压入口（`0x18e200`）。这些是本 ELF 的静态地址，动态库运行时需加装载基址。
- 因此转换入口依赖 ODA 数据库与 I/O 模块。仅重写命令行或 Qt 界面不足以替代 DWG 解码。
- 该包仅有 Qt `xcb` 平台插件；实际运行不能使用 `QT_QPA_PLATFORM=offscreen`，原型采用 Xvfb。

上述结论来自普通 ELF/Capstone 工具，**不是 REA Evidence**。本次没有可连接的 REA MCP 或已构建 CLI，未使用 Ghidra 反编译。保留完整静态指令与哈希：

- `evidence/entry-disassembly.json`：主入口、转换函数；
- `evidence/io-disassembly.json`：R18/R21 解压函数；
- `evidence/io-codecs.txt`：相关导出符号；
- `evidence/dwg-inventory.json`：46 个输入的路径、SHA-256、版本及 AC1015 节目录。

## 使用

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python dwg_tool.py inspect '../ODA_Converter/demo/1 刀开关.dwg'
.venv/bin/python -m unittest -v
```

当前已解包的程序位于 `artifacts/appdir/`（本地生成，不纳入源码）。复现解包：

```sh
mkdir -p artifacts
python3 - <<'PY'
from pathlib import Path
import hashlib
p = Path('../ODA_Converter/ODAFileConverter_QT6_lnxX64_8.3dll_27.1.AppImage')
b = p.read_bytes()
assert hashlib.sha256(b).hexdigest() == 'cb77a106354af98a1d355ba0191160aca3f90cb020946803e7c8132cba434dfc'
Path('artifacts/payload.squashfs').write_bytes(b[189632:])
PY
7z x artifacts/payload.squashfs -oartifacts/appdir
chmod +x artifacts/appdir/usr/bin/ODAFileConverter
.venv/bin/python inspect_binary.py artifacts/appdir/usr/bin/ODAFileConverter > evidence/entry-disassembly.json
```

macOS ARM 使用 Docker 的 x86-64 模拟：

```sh
docker build --platform linux/amd64 -t dwg2image-runtime:local .
.venv/bin/python dwg_tool.py convert \
  '../ODA_Converter/demo/2D Drawings EX 3 - 1.dwg' \
  'output/example.dxf' \
  --appdir artifacts/appdir --docker-image dwg2image-runtime:local
```

本次本地镜像由同一 Ubuntu 22.04 环境安装 Dockerfile 列出的依赖后 `docker commit` 生成；没有实际执行 `docker build`。Linux x86-64 可安装对应依赖后省略 `--docker-image`。输出必须是尚不存在的路径。

`convert` 在临时目录处理单个输入，等待 ODA 成功退出，再用 ezdxf 读取实际新生成的 DXF。Docker 禁用网络，输入 ODA 库只读挂载。审计计数不等于几何一致性验证；未自动证明所有文字、字体、动态块、布局和代理对象保真。

## 未完成的独立实现

46 个样例有 25 个 AC1015 和 21 个 AC1032。纯 Python/Go 替代需要继续恢复两代页/节结构、位流解码、压缩及纠错、对象类型与句柄、块和实体语义，最后才能写出可靠 DXF。当前 Python 实现只独立解析 AC1015 节目录，AC1032 只识别文件头。没有将预览图、已有 DXF 或空 DXF 冒充转换结果。

后续可从已定位的 `TD_DbIO.tx` 解压入口做函数级恢复与差分验证，再沿对象解码扩展；目前不能宣称已经获得闭源转换器的完整源码。

## 本次验证记录

- 46 个 DWG 头部检查完成；4 项边界单测通过。
- `2D Drawings EX 3 - 1.dwg` 已在本次真实运行 ODA 后生成 DXF，ezdxf 可读取、audit errors=0，模型空间含 LINE 21、CIRCLE 10、LWPOLYLINE 1、DIMENSION 2、HATCH 1。详见 `evidence/fresh-conversion.json`。
- 首次 offscreen 失败；第二次 xvfb-run 阻塞在启动等待；最终用 `run_headless.sh` 直接启动 Xvfb 成功。脚本只等待 X socket 就绪，不依赖 xvfb-run 的信号握手。
- `evidence/existing-dxf-check.json` 是原项目已有 DXF 的检查，明确与本次新转换分开。
- 初次调查时尚未验证 PNG 渲染、全量46图转换、几何/字体保真、原生 Linux 性能或纯 Python 解码。

另两份真实转换 `1 刀开关.dwg`（AC1015）、`Electrical Wiring Dig.dwg`（AC1032）也已成功，DXF 审计错误均为 0。记录见 `evidence/additional-conversions.json`。

项目已从 `ODA_Converter-rea` 更名为 `dwg2image`。`evidence/` 保留采集时的原始路径，旧目录名属于历史证据。

## 库化验证（2026-11-17）

- 6 项 unittest 通过，含真实 DXF→PNG 渲染及已有文件保护。
- wheel、sdist 构建成功，`twine check` 均通过。
- wheel 安装到独立虚拟环境，在 `/tmp` 从 site-packages 导入，实际调用 `dwg_to_png()` 成功生成 320×452 PNG（14317 字节），并检查存在非空白像素。
- 上述端到端样例为 `2D Drawings EX 3 - 1.dwg`，使用本地 ODA 和 Docker 镜像；不是纯 Python DWG 解码或全量保真验证。
