#!/usr/bin/env python3
"""
Browser-based graphical interface for Drive Bridge.

It uses only the Python standard library. The UI runs at http://127.0.0.1 and
the copy work happens locally in this Python process.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import html
import io
import json
import os
import platform
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
from argparse import Namespace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import drive_bridge


def state_dir() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
        return Path(base) / "DriveBridge"
    return Path(os.environ.get("TMPDIR", "/tmp")) / "drive-bridge"


LOG_DIR = state_dir()
LOG_FILE = LOG_DIR / "drive-bridge.log"
STATE_FILE = LOG_DIR / "drive-bridge-state.json"


APP_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drive Bridge</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f6f7;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #667085;
      --line: #d7dce2;
      --accent: #1463d9;
      --accent-strong: #0f4ea8;
      --danger: #a32020;
      --ok: #176b35;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    main {
      width: min(860px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 28px 0;
    }
    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
      letter-spacing: 0;
    }
    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
    }
    .section-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    h2 {
      margin: 0;
      font-size: 16px;
      letter-spacing: 0;
    }
    button, input {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      padding: 9px 13px;
      cursor: pointer;
      min-height: 38px;
    }
    button:hover { border-color: #aab4c0; }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.primary:hover { background: var(--accent-strong); }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .form {
      display: grid;
      grid-template-columns: 90px 1fr auto auto;
      gap: 12px;
      align-items: center;
    }
    label {
      font-size: 13px;
      color: var(--muted);
    }
    input[type="text"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      min-height: 38px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
      align-items: center;
    }
    .result {
      display: none;
      margin-top: 14px;
      border: 1px solid #b8dbc2;
      background: #f4fbf6;
      border-radius: 8px;
      padding: 12px;
    }
    .result.visible { display: block; }
    .result-title {
      margin: 0 0 6px;
      font-weight: 700;
      color: var(--ok);
    }
    .result-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
    }
    .result-path {
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
      margin-left: 4px;
    }
    .volumes {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }
    .volume {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fafbfc;
    }
    .volume strong {
      display: block;
      margin-bottom: 6px;
      overflow-wrap: anywhere;
    }
    .volume span {
      display: block;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .path-text {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }
    pre {
      margin: 0;
      height: 230px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #111827;
      color: #f3f4f6;
      font-size: 13px;
    }
    .ok { color: var(--ok); }
    .danger { color: var(--danger); }
    @media (max-width: 820px) {
      header { display: block; }
      .form { grid-template-columns: 1fr; }
      .form button, .actions button { width: 100%; }
      main { width: calc(100vw - 20px); padding-top: 16px; }
      section { padding: 12px; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Drive Bridge</h1>
      <p class="subtitle">选源文件或文件夹，选目标位置，然后开始复制。</p>
    </div>
    <button id="refreshVolumes">刷新分区</button>
  </header>

  <section>
    <div class="section-title">
      <h2>复制</h2>
      <span id="status" class="status">就绪</span>
    </div>
    <div class="form">
      <label for="source">源路径</label>
      <input id="source" type="text" placeholder="选择或输入要复制的文件/文件夹">
      <button id="pickSourceFile">选文件</button>
      <button id="pickSourceFolder">选文件夹</button>

      <label for="destination">目标文件夹</label>
      <input id="destination" type="text" placeholder="选择或输入复制到的文件夹">
      <button id="pickDestination">选择位置</button>
      <span></span>
    </div>

    <div class="actions">
      <button id="copy" class="primary">开始复制</button>
      <button id="clearPaths">清空</button>
    </div>
    <div id="result" class="result">
      <p class="result-title">复制成功</p>
      <div class="result-row">
        <span id="copiedPath" class="result-path"></span>
        <button id="openCopiedFolder">打开所在文件夹</button>
      </div>
    </div>
  </section>

  <section>
    <div class="section-title"><h2>日志</h2><button id="clearLog">清空日志</button></div>
    <pre id="log"></pre>
  </section>

  <section>
    <div class="section-title">
      <h2>已挂载分区</h2>
      <span id="volumeStatus" class="status">读取中...</span>
    </div>
    <div id="volumes" class="volumes"></div>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let copiedPath = "";

function log(message) {
  const node = $("log");
  node.textContent += message + "\\n";
  node.scrollTop = node.scrollHeight;
}

function setStatus(message, bad=false) {
  const node = $("status");
  node.textContent = message;
  node.className = bad ? "status danger" : "status";
}

function setCopiedPath(path) {
  copiedPath = path || "";
  $("copiedPath").textContent = copiedPath;
  $("result").className = copiedPath ? "result visible" : "result";
}

async function api(path, options={}) {
  const response = await fetch(path, options);
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { data = {ok:false, error:text}; }
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function taskPayload() {
  return {
    source: $("source").value.trim(),
    destination: $("destination").value.trim(),
    into: true,
    conflict: "rename",
    verify: "sha256"
  };
}

function requirePaths() {
  const payload = taskPayload();
  if (!payload.source || !payload.destination) {
    setStatus("请选择源路径和目标路径", true);
    return null;
  }
  return payload;
}

async function refreshVolumes() {
  $("volumeStatus").textContent = "读取中...";
  try {
    const data = await api("/api/volumes");
    const body = $("volumes");
    body.innerHTML = "";
    data.volumes.forEach((item) => {
      const card = document.createElement("div");
      card.className = "volume";
      card.innerHTML = `<strong></strong><span></span><span></span><span></span>`;
      card.children[0].textContent = item.name || item.mount_point;
      card.children[1].textContent = item.mount_point;
      card.children[1].className = "path-text";
      card.children[2].textContent = `${item.fs_type.toUpperCase()} · ${item.writable ? "可写" : "只读"}`;
      card.children[2].className = item.writable ? "ok" : "danger";
      card.children[3].textContent = `剩余 ${item.free} / 总容量 ${item.total}`;
      body.appendChild(card);
    });
    $("volumeStatus").textContent = `${data.volumes.length} 个分区`;
  } catch (error) {
    $("volumeStatus").textContent = "读取失败";
    log("刷新分区失败: " + error.message);
  }
}

async function pick(kind) {
  try {
    setStatus("等待选择...");
    const data = await api("/api/pick?kind=" + encodeURIComponent(kind), { method: "POST" });
    if (!data.path) {
      setStatus("已取消选择");
      return;
    }
    if (kind === "destination") $("destination").value = data.path;
    else $("source").value = data.path;
    setStatus("已选择");
  } catch (error) {
    log("选择失败: " + error.message);
    setStatus("选择失败", true);
  }
}

async function runTask(endpoint, payload, label) {
  if (!payload) return;
  setStatus(label);
  setCopiedPath("");
  log(label);
  try {
    const data = await api(endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    log(data.output || "(无输出)");
    if (data.code === 0 && data.copied_to) {
      setCopiedPath(data.copied_to);
      log("复制成功。可以点击“打开所在文件夹”检查结果。");
    }
    setStatus(data.code === 0 ? "完成" : `失败，退出码 ${data.code}`, data.code !== 0);
  } catch (error) {
    log("任务失败: " + error.message);
    setStatus("失败", true);
  }
}

async function openCopiedFolder() {
  if (!copiedPath) return;
  try {
    await api("/api/reveal", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ path: copiedPath })
    });
    log("已打开复制结果所在文件夹。");
  } catch (error) {
    log("打开所在文件夹失败: " + error.message);
  }
}

$("refreshVolumes").addEventListener("click", refreshVolumes);
$("pickSourceFile").addEventListener("click", () => pick("source-file"));
$("pickSourceFolder").addEventListener("click", () => pick("source-folder"));
$("pickDestination").addEventListener("click", () => pick("destination"));
$("clearPaths").addEventListener("click", () => {
  $("source").value = "";
  $("destination").value = "";
  setCopiedPath("");
  setStatus("已清空");
});
$("clearLog").addEventListener("click", () => $("log").textContent = "");
$("copy").addEventListener("click", () => runTask("/api/copy", requirePaths(), "复制中，大文件可能需要较长时间..."));
$("openCopiedFolder").addEventListener("click", openCopiedFolder);

refreshVolumes();
</script>
</body>
</html>
"""


def volume_to_json(info: drive_bridge.VolumeInfo) -> dict[str, Any]:
    return {
        "mount_point": str(info.mount_point),
        "fs_type": info.fs_type,
        "name": info.name,
        "writable": info.writable,
        "total": drive_bridge.human_bytes(info.total_bytes),
        "free": drive_bridge.human_bytes(info.free_bytes),
    }


def run_cli_function(func, args: Namespace) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = int(func(args))
    output = stdout.getvalue()
    error = stderr.getvalue()
    if error:
        output = f"{output}{error}"
    return code, output.strip()


def append_backend_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def write_state(url: str, host: str, port: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "url": url,
        "host": host,
        "port": port,
        "log_file": str(LOG_FILE),
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"没有找到运行状态文件: {STATE_FILE}")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def request_shutdown() -> int:
    try:
        state = read_state()
    except Exception as exc:  # noqa: BLE001 - command line diagnostic.
        print(f"Drive Bridge 没有运行，或无法读取状态: {exc}")
        return 1

    url = f"{state.get('url', '').rstrip('/')}/api/shutdown"
    if not url.startswith("http://"):
        print("运行状态文件里的地址无效。")
        return 1

    request = urllib.request.Request(url, data=b"{}", method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except Exception as exc:  # noqa: BLE001 - command line diagnostic.
        print(f"关闭请求失败: {exc}")
        return 1
    print("Drive Bridge 已发送关闭请求。")
    return 0


def copied_path_from_output(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Copied ") and " -> " in line:
            return line.rsplit(" -> ", 1)[1].strip()
    return ""


def reveal_path(path_text: str) -> None:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"路径不存在: {path}")

    if platform.system() == "Darwin":
        if path.is_file():
            subprocess.run(["/usr/bin/open", "-R", str(path)], check=True)
        else:
            subprocess.run(["/usr/bin/open", str(path)], check=True)
        return

    if platform.system() == "Windows":
        if path.is_file():
            subprocess.run(["explorer", f"/select,{path}"], check=True)
        else:
            subprocess.run(["explorer", str(path)], check=True)
        return

    folder = path if path.is_dir() else path.parent
    webbrowser.open(folder.resolve().as_uri())


def list_directory(path_text: str) -> dict[str, Any]:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"路径不存在: {path}")
    if not path.is_dir():
        path = path.parent

    entries = []
    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "is_dir": child.is_dir(),
                "size": "" if child.is_dir() else drive_bridge.human_bytes(stat.st_size),
            }
        )
    return {"path": str(path), "entries": entries}


def choose_path(kind: str) -> str:
    system = platform.system()
    if system == "Darwin":
        prompts = {
            "source-file": 'POSIX path of (choose file with prompt "选择要复制的文件")',
            "source-folder": 'POSIX path of (choose folder with prompt "选择要复制的文件夹")',
            "destination": 'POSIX path of (choose folder with prompt "选择复制到的位置")',
        }
        script = prompts.get(kind)
        if script is None:
            raise ValueError(f"未知选择类型: {kind}")
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    if system == "Windows":
        return choose_path_windows(kind)

    raise RuntimeError("当前系统不支持弹出文件选择窗口，请手动输入路径。")


def choose_path_windows(kind: str) -> str:
    if kind == "source-file":
        script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '选择要复制的文件'
$dialog.Multiselect = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Write-Output $dialog.FileName
}
"""
    elif kind in {"source-folder", "destination"}:
        title = "选择要复制的文件夹" if kind == "source-folder" else "选择复制到的位置"
        script = rf"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{title}'
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Write-Output $dialog.SelectedPath
}}
"""
    else:
        raise ValueError(f"未知选择类型: {kind}")

    for powershell in ["powershell", "powershell.exe"]:
        try:
            completed = subprocess.run(
                [powershell, "-NoProfile", "-STA", "-Command", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except OSError:
            continue
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()
    raise RuntimeError("找不到 PowerShell，无法打开 Windows 文件选择窗口。")


def namespace_from_payload(payload: dict[str, Any], command: str, dry_run: bool = False) -> Namespace:
    source = str(payload.get("source", "")).strip()
    destination = str(payload.get("destination", "")).strip()
    if not source or not destination:
        raise ValueError("source and destination are required")

    if command == "verify":
        return Namespace(source=source, destination=destination, mode=str(payload.get("verify", "sha256")))

    if command == "plan":
        return Namespace(source=source, destination=destination, into=bool(payload.get("into", True)))

    return Namespace(
        source=source,
        destination=destination,
        into=bool(payload.get("into", True)),
        conflict=str(payload.get("conflict", "rename")),
        verify=str(payload.get("verify", "sha256")),
        dry_run=dry_run,
    )


class DriveBridgeHandler(BaseHTTPRequestHandler):
    server_version = "DriveBridge/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_html(self) -> None:
        data = APP_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_html()
                return
            if parsed.path == "/api/volumes":
                self.send_json(HTTPStatus.OK, {"volumes": [volume_to_json(v) for v in drive_bridge.list_volumes()]})
                return
            if parsed.path == "/api/list":
                query = urllib.parse.parse_qs(parsed.query)
                path = query.get("path", ["/Volumes"])[0]
                self.send_json(HTTPStatus.OK, list_directory(path))
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert local errors to UI JSON.
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            payload = self.read_payload()
            if parsed.path == "/api/shutdown":
                append_backend_log("shutdown requested")
                self.send_json(HTTPStatus.OK, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if parsed.path == "/api/pick":
                kind = query.get("kind", [""])[0]
                self.send_json(HTTPStatus.OK, {"path": choose_path(kind)})
                return
            if parsed.path == "/api/plan":
                code, output = run_cli_function(drive_bridge.command_plan, namespace_from_payload(payload, "plan"))
                self.send_json(HTTPStatus.OK, {"code": code, "output": output})
                return
            if parsed.path == "/api/copy":
                dry_run = query.get("dry_run", ["0"])[0] == "1"
                args = namespace_from_payload(payload, "copy", dry_run=dry_run)
                code, output = run_cli_function(drive_bridge.command_copy, args)
                copied_to = copied_path_from_output(output) if code == 0 and not dry_run else ""
                if code == 0:
                    append_backend_log(f"copy success source={args.source} destination={args.destination} copied_to={copied_to}")
                else:
                    append_backend_log(f"copy failed code={code} source={args.source} destination={args.destination} output={output}")
                self.send_json(HTTPStatus.OK, {"code": code, "output": output, "copied_to": copied_to})
                return
            if parsed.path == "/api/reveal":
                path = str(payload.get("path", "")).strip()
                if not path:
                    raise ValueError("path is required")
                reveal_path(path)
                append_backend_log(f"revealed copied path={path}")
                self.send_json(HTTPStatus.OK, {"ok": True})
                return
            if parsed.path == "/api/verify":
                code, output = run_cli_function(drive_bridge.command_verify, namespace_from_payload(payload, "verify"))
                self.send_json(HTTPStatus.OK, {"code": code, "output": output})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - show actionable error in UI.
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def self_test() -> int:
    volumes = [volume_to_json(v) for v in drive_bridge.list_volumes()]
    current = list_directory(str(Path.cwd()))
    payload = {
        "source": str(Path.cwd()),
        "destination": str(Path.cwd()),
        "into": True,
        "conflict": "rename",
        "verify": "sha256",
    }
    namespace_from_payload(payload, "plan")
    if not isinstance(APP_HTML, str) or "Drive Bridge" not in APP_HTML:
        print("self-test failed: html missing")
        return 1
    print(f"self-test passed: {len(volumes)} volume(s), {len(current['entries'])} current entries")
    return 0


def serve(host: str, port: int, open_browser: bool) -> int:
    server = ThreadingHTTPServer((host, port), DriveBridgeHandler)
    url = f"http://{host}:{server.server_address[1]}"
    actual_port = int(server.server_address[1])
    write_state(url, host, actual_port)
    append_backend_log(f"server started url={url} pid={os.getpid()}")
    print(f"Drive Bridge GUI: {url}")
    if open_browser:
        threading.Timer(0.4, lambda: open_gui_url(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Drive Bridge GUI")
    finally:
        server.server_close()
        append_backend_log("server stopped")
    return 0


def open_gui_url(url: str) -> None:
    if platform.system() == "Darwin":
        try:
            subprocess.run(["/usr/bin/open", url], check=True)
            return
        except (OSError, subprocess.CalledProcessError):
            pass
    webbrowser.open(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive Bridge browser graphical interface.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="Local port. Use 0 to pick an available port.")
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")
    parser.add_argument("--self-test", action="store_true", help="Run non-interactive checks.")
    parser.add_argument("--stop", action="store_true", help="Stop a running Drive Bridge GUI server.")
    args = parser.parse_args()
    if args.stop:
        return request_shutdown()
    if args.self_test:
        return self_test()
    return serve(args.host, args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
