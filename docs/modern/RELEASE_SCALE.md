# SCALE 发布与打包

本项目现在把 `scale_release` 定义为最终用户可运行的交付包，而不是源码镜像。

## 产物

- 输出目录：`scale_release/`
- 压缩文件：`scale_release.zip`

## 交付包内容

- `backend/` 运行所需代码
- `frontend/dist/` 已构建的静态前端
- `tools/` 运行所需工具
- `docs/modern/` 精简文档
- `start_delivery.bat` 双击启动入口
- `cli/`、`cad-cli.bat`、`install_cli.bat` 和 `CLI.md`：与后端版本一致的命令行入口
- `requirements.txt`

## 不再包含

- `frontend/src`
- `frontend/node_modules`
- `agent-harness`
- 测试、缓存、数据库、`.env`
- `runtime_config.local.json`（含 API Key 的运行时配置，构建脚本会拒绝打包）
- 个人配置、provider API key、虚拟环境和日志
- 历史交付材料和开发期辅助文件

## 打包方式

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

脚本会使用 `npm ci` 构建前端，再生成新的 `scale_release/` 和
`scale_release.zip`。构建完成后会对目录和压缩包执行统一的发布审计；
压缩包中的嵌套 ZIP 也会检查路径穿越、虚拟环境、日志和配置文件。

## 启动方式

最终用户在交付目录中双击：

```bat
start_delivery.bat
```

启动器会：

- 在 `cmd` 中显示交付根目录、后端入口路径、前端静态目录路径和访问地址
- 以单进程模式启动后端
- 由后端直接托管前端静态页
- 自动打开浏览器到 `http://127.0.0.1:8000/`

---

## 便携 EXE 交付包（scale_release_exe/）

在 `scale_release/`（需 Python 的运行时包）基础上，`scale_release_exe/` 是**自带 Python 运行时**的单机便携版本，目标机器无需预装 Python。

### 产物

- 输出目录：`scale_release_exe/`
- 入口：`launcher.exe`（PyInstaller onedir 打包）
- 内部：`_internal/` 包含 Python 运行时与收集的依赖库；`runtime_payload.zip` 内嵌后端源码 + 前端构建产物 + 工具

### 打包方式

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1
```

脚本会先构建前端，再调用 PyInstaller 将 `release_exe/launcher.py` 打成 `launcher.exe`，并把 `backend/`、`frontend/dist/`、`tools/` 打包为 `runtime_payload.zip` 内嵌。

所需文件：

构建前会检查必需运行依赖（包括旧 `.xls` 支持所需的 `xlrd`）。缺失时构建明确失败，并提示在当前构建环境安装 `backend/requirements.txt`，避免 PyInstaller 仅记录隐藏导入错误后继续产出不完整包。

- `release_exe/launcher.py` — PyInstaller 入口，负责解压负载、启动后端、打开浏览器。
- `release_exe/pyinstaller_manifest.py` — 输出 PyInstaller 的 hidden-import / collect-* 清单。

### 启动方式

双击 `launcher.exe`：

- 将内嵌负载按内容 SHA-256 解压到
  `%LOCALAPPDATA%/CAD Translation/code-cache/<sha256>/`
- 将 SQLite 数据库、上传、输出、临时文件和模型配置持久化到
  `%LOCALAPPDATA%/CAD Translation/data/`，代码缓存与用户数据分开保存
- 解压在进程锁下通过独立 staging 目录和完整标记原子完成；解压完成即释放锁。
  每个实例的生成环境文件在正常退出时清理，不删除其他实例的数据。
- 以单进程模式启动后端，并自动打开浏览器到 `http://127.0.0.1:<PORT>/`（端口被占用时自动换端口）
- 服务健康检查通过后才打开浏览器；设置 `CAD_HEADLESS=true` 可用于无头启动
- 关闭命令行窗口即退出，代码缓存和用户数据不会被启动器删除

### 在 CNB 上自动构建

- 打 `v*` Tag 时，CNB 流水线使用 Wine Windows Python 交叉构建 EXE，并要求 Tag
  与 `backend/app/version.py` 的 SemVer 完全一致后才创建 Release 附件。
- 也可在「流水线 → Web 触发」手动点击「生成 Windows EXE」（`manual-exe`）构建。
- 未接入 Windows 节点时，本机仍可用上方 PowerShell 命令生成。

所有运行时、EXE/Nuitka 和云端源码包都通过 `scripts/release_manifest.py` 的同一套文件过滤
和敏感字段规则；`tools/manifest.json` 只列出实际复制到包内的工具及其 SHA-256，
不会声明不存在的二进制或下载校验和。上传脚本在令牌缺失、上传失败或确认失败时
返回错误，流水线不会把附件失败当作成功。

### 构建后验收

本地 EXE/Nuitka 构建与 CNB 的 Windows EXE 构建会调用：

```powershell
python scripts/smoke_release.py --exe <构建目录>/launcher.exe
```

验收使用独立临时数据目录，启动实际 EXE 两次，验证模型设置通过 API 保存并在重启后
生效、SQL 项目与任务持久化、真实合成 DXF 提取及 Excel 依赖可用。全程只提取合成文字，
不调用外部模型，也不打开浏览器。失败会阻塞发布；开发用 `-SkipPyInstaller` /
`-SkipNuitka` 只产生占位文件，不作为可发布 EXE，也不运行这个启动验收。

仅检查源码负载时可用 `python scripts/smoke_release.py --payload <runtime_payload.zip>`；
它不能替代冻结 EXE 验收。原生 Windows 验收证明本地运行时可启动，Wine 验收只证明
对应 Wine 环境；两者均不证明目标机器已安装的 AutoCAD/浩辰 COM 可以完成 DWG 转换。

最终 ZIP 包还会递归检查内层 ZIP，拒绝路径穿越、开发目录、个人配置和敏感字段。
审计预算为单个成员最多 512 MiB、累计解压成员最多 2 GiB、最多三层嵌套 ZIP；超过预算
会明确失败。证书信任库 `certifi/cacert.pem` 是允许发布的公共 CA 数据。
