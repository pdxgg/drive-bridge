# Drive Bridge 原理说明

Drive Bridge 不是把视频、照片、文档本身转换成另一种格式。APFS、exFAT、NTFS 是硬盘分区的文件系统格式，普通文件在这些文件系统之间迁移时，正确方式是复制同一份文件字节，并检查目标卷是否能写入、空间是否足够、复制后内容是否一致。

## 核心模块

- `drive_bridge.py`：跨平台复制核心，负责识别卷、计算大小、复制文件/文件夹、重名处理和 SHA-256 校验。
- `drive_bridge_gui.py`：本地网页界面。它启动一个 `127.0.0.1` HTTP 服务，浏览器只作为界面，文件操作仍在本机 Python 进程中执行。
- `drive-bridge-mac.command` / `drive-bridge-win.bat`：启动界面。
- `drive-bridge-stop-mac.command` / `drive-bridge-stop-win.bat`：通过本地 `/api/shutdown` 关闭界面服务。

## 复制流程

1. 用户选择源文件或源文件夹。
2. 用户选择目标文件夹。
3. 程序计算源数据大小。
4. 程序检测目标位置的剩余空间和可写性。
5. 复制到目标文件夹。
6. 如果同名文件已存在，默认自动改名，例如 `video (1).mp4`。
7. 复制完成后使用 SHA-256 校验源文件和目标文件是否一致。
8. 成功后界面显示实际复制路径，并提供“打开所在文件夹”按钮。

## 文件系统支持

- APFS：macOS 原生支持读写。
- exFAT：macOS 和 Windows 通常都支持读写，适合作为跨平台中间分区。
- NTFS：Windows 原生支持读写；macOS 通常只能读取，写入需要额外 NTFS 写入驱动。

## 平台差异

### macOS

- 使用 `/Volumes` 识别外接卷。
- 用 `df`、`mount`、`diskutil` 等系统工具辅助识别文件系统。
- 文件选择窗口由 `osascript` 调用系统选择器。
- “打开所在文件夹”通过 `open -R` 定位复制结果。

### Windows

- 使用 Windows API 识别驱动器和文件系统。
- 文件选择窗口由 PowerShell 调用 Windows Forms。
- “打开所在文件夹”通过 Explorer 打开或选中复制结果。

## 安全边界

Drive Bridge 不会格式化磁盘、不改分区表、不做原地文件系统转换，也不会删除源文件。它只在用户选择的目标位置创建复制结果。
