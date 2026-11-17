# dwg2image

项目目标是将 DWG 图纸转换为图片。当前目录包含初步逆向成果和 Python 验证原型，已验证 DWG→DXF 阶段；图片渲染尚未接入本项目。**尚未独立重写 DWG 几何解码器**；`convert` 仍执行用户提供的 ODA 二进制。`inspect` 和 `check-dxf` 不执行 ODA。没有修改原始 AppImage、demo 或原项目输出。

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
- 尚未验证 PNG 渲染、全量46图转换、几何/字体保真、原生 Linux 性能或纯 Python 解码。

另两份真实转换 `1 刀开关.dwg`（AC1015）、`Electrical Wiring Dig.dwg`（AC1032）也已成功，DXF 审计错误均为 0。记录见 `evidence/additional-conversions.json`。

项目已从 `ODA_Converter-rea` 更名为 `dwg2image`。`evidence/` 保留采集时的原始路径，旧目录名属于历史证据。
