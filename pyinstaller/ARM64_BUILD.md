# ARM64 构建指南

本文档介绍如何使用 GitHub Actions 构建 ARM64 版本的 dirsearch 可执行文件。

## 方法一：使用 GitHub Actions（推荐）

### 前提条件
- GitHub 仓库
- 对仓库有推送权限

### 步骤

1. **确保文件已提交到仓库**
   
   ARM64 构建相关的文件包括：
   - `.github/workflows/build-arm64.yml` - GitHub Actions workflow 配置
   - `pyinstaller/Dockerfile.arm64` - Docker 交叉编译配置
   - `pyinstaller/build-arm64.sh` - 本地构建脚本

2. **推送代码到 GitHub**

   ```bash
   git add .github/workflows/build-arm64.yml
   git add pyinstaller/Dockerfile.arm64
   git add pyinstaller/build-arm64.sh
   git commit -m "Add ARM64 build configuration"
   git push
   ```

3. **触发构建**

   构建会在以下情况自动触发：
   - 推送代码到 `main` 或 `master` 分支
   - 修改以下目录中的文件时：
     - `pyinstaller/**`
     - `lib/**`
     - `dirsearch.py`
     - `requirements.txt`

   或者手动触发：
   - 进入 GitHub 仓库页面
   - 点击 "Actions" 标签
   - 选择 "Build ARM64 Executable" workflow
   - 点击 "Run workflow" 按钮

4. **下载构建产物**

   构建完成后：
   - 进入 "Actions" 标签
   - 点击完成的 workflow 运行
   - 在 "Artifacts" 部分下载 `dirsearch-arm64-binary`
   - 解压后得到 `dirsearch-{VERSION}-linux-arm64` 可执行文件

### 构建产物命名

构建的可执行文件命名格式：
```
dirsearch-{VERSION}-linux-arm64
```

其中 `{VERSION}` 是从 `lib/core/settings.py` 中读取的版本号。

## 方法二：使用 ARM64 设备本地构建

如果您有 ARM64 设备（如树莓派、Mac M1/M2/M3），可以直接在设备上构建：

### 步骤

1. **克隆仓库**

   ```bash
   git clone <repository-url>
   cd dirsearch
   ```

2. **安装依赖**

   ```bash
   pip3 install --break-system-packages pyinstaller==6.3.0
   pip3 install --break-system-packages -r requirements.txt
   ```

3. **构建可执行文件**

   ```bash
   python3 pyinstaller/dirsearch.spec
   ```

   或使用构建脚本：
   ```bash
   cd pyinstaller
   python3 -m PyInstaller \
     --onefile \
     --name dirsearch \
     --paths=. \
     --collect-submodules=lib \
     --add-data "../db:db" \
     --add-data "../config.ini:." \
     --add-data "../lib/report:lib/report" \
     --strip \
     --clean \
     ../dirsearch.py
   ```

4. **获取可执行文件**

   构建完成后，可执行文件位于：
   ```
   dist/dirsearch
   ```

## 方法三：使用 Docker 交叉编译

在 x86_64 系统上使用 Docker 交叉编译 ARM64 版本。

### 前提条件

- Docker 已安装并运行
- 配置 binfmt_misc 支持多平台构建

### 步骤

1. **配置 Docker 多平台支持（只需执行一次）**

   ```bash
   docker run --privileged --rm tonistiigi/binfmt --install all
   ```

2. **构建 ARM64 可执行文件**

   ```bash
   ./pyinstaller/build-arm64.sh
   ```

3. **获取可执行文件**

   构建完成后，可执行文件位于：
   ```
   pyinstaller/dist/dirsearch-arm64
   ```

## 验证 ARM64 可执行文件

构建完成后，可以使用以下命令验证文件是否为 ARM64 架构：

```bash
file dirsearch-arm64
```

期望输出：
```
dirsearch-arm64: ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), ...
```

## 运行 ARM64 可执行文件

在 ARM64 设备上运行：

```bash
./dirsearch-arm64 --help
```

## 故障排除

### GitHub Actions 构建失败

1. 检查 `python-version` 是否支持 ARM64
2. 确保依赖项版本兼容
3. 查看 Actions 日志了解详细错误信息

### Docker 构建失败

1. 确认 Docker 已安装并运行
2. 验证 binfmt_misc 已正确配置
3. 检查网络连接是否正常

### 本地构建失败

1. 确认设备架构为 ARM64（`uname -m` 应显示 `aarch64`）
2. 安装所有必要的构建依赖
3. 确保有足够的磁盘空间

## 其他平台

- **Linux AMD64**: 使用 `pyinstaller/build.sh` 构建
- **macOS Intel/MacOS Silicon**: 在对应 Mac 上运行 `pyinstaller/build.sh`
- **Windows**: 在 Windows 系统上运行 PyInstaller

更多信息请参考 `pyinstaller/README.md`。
