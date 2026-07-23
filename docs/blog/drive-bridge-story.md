# 我为什么开发 Drive Bridge：让 Windows 和 Mac 之间的硬盘资源迁移更简单

在日常使用移动硬盘时，我经常遇到一个很现实的问题：同一块硬盘可能要同时服务于 Mac 和 Windows，但不同系统对硬盘格式的支持并不一致。

Mac 常见的是 APFS，Windows 常见的是 NTFS，而 exFAT 又常被用作两个系统之间的中间格式。比如我有一份视频、图片素材或者项目文件放在 exFAT 分区里，在 Mac 上使用时，希望把它复制到 APFS 分区；在 Windows 上使用时，又可能希望把它复制到 NTFS 分区。

一开始我以为这是“文件格式转换”的问题，后来才意识到：视频、图片、文档本身并不需要转换。真正要解决的是不同文件系统之间的安全复制、权限判断、空间检查和复制后校验。

这就是我开发 Drive Bridge 的初衷。

## 一、先说底层原理：APFS、exFAT、NTFS 到底是什么

APFS、exFAT、NTFS 不是视频格式，也不是图片格式，它们是硬盘分区的“文件系统格式”。

可以简单理解为：

- 文件本身：比如 `video.mp4`、`photo.jpg`、`project.zip`
- 文件系统：硬盘如何保存、索引、读取和管理这些文件

所以，从 exFAT 复制一个视频到 APFS，并不是把 `mp4` 转成某种 Mac 格式，而是把同一份文件字节写入另一个文件系统管理的目录里。

真正重要的是：

- 源文件是否存在
- 目标分区是否可写
- 目标空间是否足够
- 目标位置是否已经有同名文件
- 复制完成后源文件和目标文件是否一致

Drive Bridge 做的事情就是围绕这几件事展开。

## 二、为什么不能直接“转换硬盘格式”

理论上，一个分区可以被格式化成 APFS、exFAT 或 NTFS，但这通常意味着清空数据、重建文件系统。对普通用户来说，这个动作风险很高。

Drive Bridge 刻意不做这些危险操作：

- 不格式化硬盘
- 不改分区表
- 不删除源文件
- 不做原地文件系统转换

它只做一件更安全、更可控的事情：把用户选择的文件或文件夹复制到另一个已挂载的目标位置，并校验结果。

这也是这个工具的核心设计原则：不碰磁盘结构，只处理文件迁移。

## 三、Drive Bridge 的工作流程

Drive Bridge 的流程很简单：

1. 用户选择源文件或源文件夹
2. 用户选择目标文件夹
3. 程序识别源位置和目标位置所在的卷
4. 程序检查目标位置是否可写
5. 程序检查目标空间是否足够
6. 如果目标已有同名文件，自动改名
7. 执行复制
8. 复制后计算 SHA-256 校验
9. 成功后显示目标路径，并提供“打开所在文件夹”入口

这里最关键的是最后一步 SHA-256 校验。

SHA-256 可以理解为文件内容的指纹。源文件和目标文件算出的指纹一致，就说明复制后的内容和原文件一致。对大视频、素材包、照片归档这种文件迁移场景来说，这个校验很有价值。

## 四、用到的技术

Drive Bridge 使用的是 Python 标准库，尽量不依赖第三方包。这样做的好处是：用户下载解压后，只要电脑有 Python 3，就能运行。

主要技术包括：

- `http.server`：启动本地网页服务
- `pathlib` / `os` / `shutil`：处理路径、文件夹、复制和磁盘空间
- `hashlib`：计算 SHA-256 校验值
- `subprocess`：调用系统工具
- `plistlib`：在 macOS 上解析部分磁盘信息
- Windows API：识别 Windows 卷和文件系统
- PowerShell + Windows Forms：在 Windows 上弹出原生文件选择窗口
- AppleScript：在 macOS 上弹出原生文件选择窗口
- Finder / Explorer：复制成功后打开目标所在位置

前端没有使用 React、Vue 或 Electron，而是直接用一份 HTML、CSS、JavaScript 页面。页面运行在浏览器里，但服务只监听 `127.0.0.1`，也就是本机地址。

这意味着：

- 文件不会上传到外网
- 浏览器只是操作界面
- 实际复制发生在本机 Python 进程里
- macOS 和 Windows 可以共用同一套核心逻辑

## 五、整体架构

项目里主要有两个核心文件：

```text
drive_bridge.py
drive_bridge_gui.py
```

`drive_bridge.py` 是复制核心，负责：

- 枚举和识别卷
- 判断 APFS、exFAT、NTFS
- 计算文件大小
- 处理重名策略
- 复制文件或文件夹
- 校验文件内容

`drive_bridge_gui.py` 是图形界面层，负责：

- 启动本地网页界面
- 提供文件选择接口
- 调用复制核心
- 显示日志
- 保存后台运行状态
- 提供关闭服务接口
- 复制成功后打开所在文件夹

启动脚本按平台拆开：

```text
drive-bridge-mac.command
drive-bridge-stop-mac.command
drive-bridge-win.bat
drive-bridge-stop-win.bat
```

macOS 用户双击 `.command` 启动，Windows 用户双击 `.bat` 启动。关闭脚本会调用本地 `/api/shutdown` 接口，让服务优雅退出。

## 六、为什么选择“本地网页界面”

一开始也可以做传统桌面 GUI，比如 Tkinter、PyQt 或 Electron。但我最后选择了本地网页界面，原因很直接：

- Python 标准库就能启动本地 HTTP 服务
- 浏览器是 macOS 和 Windows 都有的通用界面
- 不需要打包复杂的 GUI 运行时
- 不需要引入庞大的前端框架
- 逻辑简单，可维护性更好

这个方案的体验接近一个桌面工具：用户双击脚本，浏览器自动打开页面，选择文件、选择目标、点击复制即可。

## 七、macOS 和 Windows 的差异处理

### macOS

macOS 上外接硬盘通常挂载在：

```text
/Volumes
```

Drive Bridge 会通过系统命令识别挂载点和文件系统类型，并用 AppleScript 弹出系统文件选择窗口。

复制成功后，点击“打开所在文件夹”会调用 Finder，并尽量定位到复制出来的文件。

### Windows

Windows 上的磁盘通常是：

```text
C:\
D:\
E:\
```

Drive Bridge 会通过 Windows API 获取卷信息，用 PowerShell 调用 Windows Forms 弹出文件或文件夹选择窗口。

复制成功后，点击“打开所在文件夹”会调用 Explorer。

## 八、我希望这个工具解决的真实问题

这个工具并不是为了替代专业的磁盘管理软件，也不是为了做危险的格式转换。

它解决的是一个更日常、更真实的问题：

当我有一份文件在 exFAT、NTFS、APFS 之间流转时，我希望不用反复确认系统权限、不用担心覆盖同名文件、不用手动校验复制是否完整。

我只想：

1. 选文件
2. 选目标
3. 开始复制
4. 复制完后打开位置检查

Drive Bridge 就是围绕这个最小流程做出来的。

## 九、使用方式

macOS 下载包解压后，双击：

```text
drive-bridge-mac.command
```

Windows 下载包解压后，双击：

```text
drive-bridge-win.bat
```

启动后：

1. 点击“选文件”或“选文件夹”
2. 点击“选择位置”
3. 点击“开始复制”
4. 在日志里查看复制和校验结果
5. 点击“打开所在文件夹”检查结果

如果要关闭服务：

macOS 双击：

```text
drive-bridge-stop-mac.command
```

Windows 双击：

```text
drive-bridge-stop-win.bat
```

## 十、一些限制

目前 Drive Bridge 仍然是一个轻量工具，因此也有边界：

- 它不会格式化硬盘
- 它不会把 NTFS 原地转换为 APFS
- 它不会让 macOS 原生写入 NTFS
- 它依赖系统已经正确挂载目标分区
- 它需要电脑上有 Python 3

如果 macOS 要写入 NTFS 分区，仍然需要额外的 NTFS 写入驱动。Drive Bridge 会尽量检测目标位置是否可写，但它不会绕过系统权限。

## 结语

Drive Bridge 的开发过程让我重新理解了一个问题：很多时候用户说的“格式转换”，底层其实是“文件系统之间的数据迁移”。

把这个问题拆开后，真正需要做的不是危险地改硬盘格式，而是把复制流程做得更清楚、更安全、更可验证。

这也是 Drive Bridge 的核心价值：让 Windows 和 Mac 之间，不同格式硬盘下的资源复制传输变得更简单。

项目地址：

```text
https://github.com/pdxgg/drive-bridge
```

