#!/usr/bin/env python3
"""
Drive Bridge: copy files safely between APFS, exFAT, NTFS, and other mounted
volumes.

This tool does not convert a video/document format. It transfers file bytes
between mounted filesystems, checks destination writability and free space, and
can verify copied files with SHA-256.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional


SUPPORTED_FILESYSTEMS = {"apfs", "exfat", "ntfs"}
CHUNK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class VolumeInfo:
    mount_point: Path
    fs_type: str
    name: str
    writable: bool
    total_bytes: int
    free_bytes: int


def run_command(args: list[str]) -> Optional[bytes]:
    try:
        completed = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
        )
        return completed.stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.2f} {unit}"
        number /= 1024
    return f"{value} B"


def normalize_fs(fs_type: str) -> str:
    lowered = (fs_type or "unknown").strip().lower()
    aliases = {
        "apfs": "apfs",
        "apple_apfs": "apfs",
        "exfat": "exfat",
        "msdos": "exfat",
        "ntfs": "ntfs",
        "ntfs-3g": "ntfs",
    }
    return aliases.get(lowered, lowered)


def existing_parent(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.exists():
        return candidate
    for parent in [candidate.parent, *candidate.parents]:
        if parent.exists():
            return parent
    return Path("/")


def disk_usage_for(path: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


def mac_mount_point(path: Path) -> Path:
    stdout = run_command(["/bin/df", "-Pk", str(path)])
    if not stdout:
        return path
    lines = stdout.decode(errors="replace").strip().splitlines()
    if len(lines) < 2:
        return path
    fields = lines[-1].split(None, 5)
    if len(fields) < 6:
        return path
    return Path(fields[5])


def mac_mount_fs_type(mount_point: Path) -> str:
    stdout = run_command(["/sbin/mount"])
    if not stdout:
        return "unknown"
    marker = f" on {mount_point} ("
    for line in stdout.decode(errors="replace").splitlines():
        if marker in line:
            options = line.split(marker, 1)[1].split(")", 1)[0]
            return options.split(",", 1)[0].strip()
    return "unknown"


def mac_volume_info(path: Path) -> VolumeInfo:
    target = existing_parent(path)
    mount_point = mac_mount_point(target)
    fs_type = mac_mount_fs_type(mount_point)
    name = mount_point.name or str(mount_point)
    writable_probe_path = target if target.is_dir() else target.parent
    writable = os.access(writable_probe_path, os.W_OK)

    plist_stdout = run_command(["/usr/sbin/diskutil", "info", "-plist", str(mount_point)])
    if plist_stdout:
        try:
            info = plistlib.loads(plist_stdout)
            fs_type = (
                info.get("FilesystemName")
                or info.get("FilesystemType")
                or info.get("TypeBundle")
                or fs_type
            )
            name = info.get("VolumeName") or name
            writable = bool(info.get("Writable", writable))
        except (plistlib.InvalidFileException, ValueError):
            pass

    total, free = disk_usage_for(mount_point)
    return VolumeInfo(
        mount_point=mount_point,
        fs_type=normalize_fs(str(fs_type)),
        name=str(name),
        writable=writable,
        total_bytes=total,
        free_bytes=free,
    )


def windows_volume_info(path: Path) -> VolumeInfo:
    kernel32 = ctypes.windll.kernel32
    source = str(existing_parent(path).resolve())

    root_buffer = ctypes.create_unicode_buffer(260)
    kernel32.GetVolumePathNameW(source, root_buffer, len(root_buffer))
    mount_point = Path(root_buffer.value or Path(source).anchor)

    volume_name = ctypes.create_unicode_buffer(260)
    fs_name = ctypes.create_unicode_buffer(260)
    serial = ctypes.c_ulong()
    max_component_len = ctypes.c_ulong()
    flags = ctypes.c_ulong()
    kernel32.GetVolumeInformationW(
        str(mount_point),
        volume_name,
        len(volume_name),
        ctypes.byref(serial),
        ctypes.byref(max_component_len),
        ctypes.byref(flags),
        fs_name,
        len(fs_name),
    )

    total, free = disk_usage_for(mount_point)
    writable = os.access(mount_point, os.W_OK)
    return VolumeInfo(
        mount_point=mount_point,
        fs_type=normalize_fs(fs_name.value),
        name=volume_name.value or str(mount_point),
        writable=writable,
        total_bytes=total,
        free_bytes=free,
    )


def generic_volume_info(path: Path) -> VolumeInfo:
    target = existing_parent(path)
    total, free = disk_usage_for(target)
    return VolumeInfo(
        mount_point=target,
        fs_type="unknown",
        name=target.name or str(target),
        writable=os.access(target, os.W_OK),
        total_bytes=total,
        free_bytes=free,
    )


def get_volume_info(path: Path) -> VolumeInfo:
    system = platform.system()
    if system == "Darwin":
        return mac_volume_info(path)
    if system == "Windows":
        return windows_volume_info(path)
    return generic_volume_info(path)


def mac_volume_candidates() -> list[Path]:
    candidates = [Path("/")]
    volumes = Path("/Volumes")
    if volumes.exists():
        candidates.extend(sorted(p for p in volumes.iterdir() if p.is_dir()))
    return candidates


def windows_volume_candidates() -> list[Path]:
    candidates: list[Path] = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter_index in range(26):
        if bitmask & (1 << letter_index):
            candidates.append(Path(f"{chr(65 + letter_index)}:\\"))
    return candidates


def list_volumes() -> list[VolumeInfo]:
    system = platform.system()
    if system == "Darwin":
        candidates = mac_volume_candidates()
    elif system == "Windows":
        candidates = windows_volume_candidates()
    else:
        candidates = [Path("/")]

    volumes: list[VolumeInfo] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            info = get_volume_info(candidate)
        except (OSError, ValueError):
            continue
        key = str(info.mount_point)
        if key not in seen:
            seen.add(key)
            volumes.append(info)
    return volumes


def can_create_file(directory: Path) -> bool:
    target_dir = existing_parent(directory)
    try:
        with tempfile.NamedTemporaryFile(prefix=".drive-bridge-", dir=target_dir, delete=True):
            return True
    except OSError:
        return False


def iter_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    for root, _, files in os.walk(path):
        root_path = Path(root)
        for filename in files:
            yield root_path / filename


def total_size(path: Path) -> int:
    return sum(file.stat().st_size for file in iter_files(path))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def destination_for(source: Path, destination: Path, into: bool) -> Path:
    if into or destination.exists() and destination.is_dir():
        return destination / source.name
    return destination


def renamed_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 10000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find available renamed path for {path}")


def resolve_conflict(path: Path, policy: str) -> Optional[Path]:
    if not path.exists():
        return path
    if policy == "fail":
        raise FileExistsError(f"Destination already exists: {path}")
    if policy == "skip":
        return None
    if policy == "rename":
        return renamed_path(path)
    if policy == "overwrite":
        return path
    raise ValueError(f"Unknown conflict policy: {policy}")


def verify_pair(source: Path, destination: Path, mode: str) -> tuple[bool, str]:
    if mode == "none":
        return True, "verification skipped"
    if not destination.exists():
        return False, "destination missing"
    if source.is_file():
        if source.stat().st_size != destination.stat().st_size:
            return False, "size mismatch"
        if mode == "size":
            return True, "sizes match"
        source_hash = sha256_file(source)
        destination_hash = sha256_file(destination)
        return (
            source_hash == destination_hash,
            "sha256 match" if source_hash == destination_hash else "sha256 mismatch",
        )

    source_files = sorted(file.relative_to(source) for file in iter_files(source))
    for relative in source_files:
        source_file = source / relative
        destination_file = destination / relative
        if not destination_file.exists():
            return False, f"missing file: {relative}"
        if source_file.stat().st_size != destination_file.stat().st_size:
            return False, f"size mismatch: {relative}"
        if mode == "sha256" and sha256_file(source_file) != sha256_file(destination_file):
            return False, f"sha256 mismatch: {relative}"
    return True, "all files verified"


def copy_file(source: Path, destination: Path, conflict: str, dry_run: bool) -> Optional[Path]:
    resolved = resolve_conflict(destination, conflict)
    if resolved is None:
        return None
    if dry_run:
        return resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, resolved)
    return resolved


def copy_directory(source: Path, destination: Path, conflict: str, dry_run: bool) -> Optional[Path]:
    resolved_root = resolve_conflict(destination, conflict)
    if resolved_root is None:
        return None
    if dry_run:
        return resolved_root

    resolved_root.mkdir(parents=True, exist_ok=True)
    for directory, _, files in os.walk(source):
        directory_path = Path(directory)
        relative_dir = directory_path.relative_to(source)
        target_dir = resolved_root / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copystat(directory_path, target_dir, follow_symlinks=False)
        for filename in files:
            source_file = directory_path / filename
            target_file = target_dir / filename
            file_target = resolve_conflict(target_file, "overwrite" if conflict == "overwrite" else "fail")
            if file_target is None:
                continue
            shutil.copy2(source_file, file_target)
    return resolved_root


def print_volume(info: VolumeInfo) -> None:
    support = "supported" if info.fs_type in SUPPORTED_FILESYSTEMS else "other"
    writable = "writable" if info.writable else "read-only"
    print(
        f"{info.mount_point} | {info.fs_type} | {info.name} | "
        f"{writable} | free {human_bytes(info.free_bytes)} / {human_bytes(info.total_bytes)} | {support}"
    )


def command_list(_: argparse.Namespace) -> int:
    for info in list_volumes():
        print_volume(info)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    destination = Path(args.destination).expanduser()
    if not source.exists():
        print(f"Source does not exist: {source}", file=sys.stderr)
        return 2

    source_volume = get_volume_info(source)
    destination_volume = get_volume_info(destination)
    size = total_size(source)
    final_destination = destination_for(source, destination, args.into)

    print("Source volume:")
    print_volume(source_volume)
    print("Destination volume:")
    print_volume(destination_volume)
    print(f"Transfer: {source} -> {final_destination}")
    print(f"Source size: {human_bytes(size)}")

    if destination_volume.free_bytes < size:
        print("Problem: destination does not have enough free space.", file=sys.stderr)
        return 3
    if not can_create_file(final_destination.parent):
        print("Problem: destination volume is not writable from this system.", file=sys.stderr)
        return 4
    if destination_volume.fs_type == "ntfs" and platform.system() == "Darwin":
        print("Note: macOS normally mounts NTFS read-only unless an NTFS driver is installed.")
    return 0


def command_copy(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    destination = Path(args.destination).expanduser()
    if not source.exists():
        print(f"Source does not exist: {source}", file=sys.stderr)
        return 2

    final_destination = destination_for(source, destination, args.into)
    destination_volume = get_volume_info(final_destination.parent)
    size = total_size(source)

    if destination_volume.free_bytes < size:
        print(
            f"Destination free space is too small: need {human_bytes(size)}, "
            f"available {human_bytes(destination_volume.free_bytes)}",
            file=sys.stderr,
        )
        return 3
    if not can_create_file(final_destination.parent):
        print(
            f"Destination is not writable: {destination_volume.mount_point} ({destination_volume.fs_type})",
            file=sys.stderr,
        )
        if destination_volume.fs_type == "ntfs" and platform.system() == "Darwin":
            print("macOS usually needs a third-party NTFS driver to write NTFS.", file=sys.stderr)
        return 4

    try:
        if source.is_dir():
            copied_to = copy_directory(source, final_destination, args.conflict, args.dry_run)
        else:
            copied_to = copy_file(source, final_destination, args.conflict, args.dry_run)
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return 5

    if copied_to is None:
        print(f"Skipped existing destination: {final_destination}")
        return 0
    if args.dry_run:
        print(f"Dry run: would copy {source} -> {copied_to}")
        return 0

    ok, message = verify_pair(source, copied_to, args.verify)
    if not ok:
        print(f"Copied, but verification failed: {message}", file=sys.stderr)
        return 6
    print(f"Copied {source} -> {copied_to}")
    print(f"Verification: {message}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    destination = Path(args.destination).expanduser()
    if not source.exists():
        print(f"Source does not exist: {source}", file=sys.stderr)
        return 2
    ok, message = verify_pair(source, destination, args.mode)
    print(message)
    return 0 if ok else 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drive_bridge",
        description="Copy files safely between APFS, exFAT, NTFS, and other mounted volumes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List mounted volumes.")
    list_parser.set_defaults(func=command_list)

    plan_parser = subparsers.add_parser("plan", help="Check a transfer before copying.")
    plan_parser.add_argument("source")
    plan_parser.add_argument("destination")
    plan_parser.add_argument("--into", action="store_true", help="Treat destination as a directory.")
    plan_parser.set_defaults(func=command_plan)

    copy_parser = subparsers.add_parser("copy", help="Copy a file or folder and verify it.")
    copy_parser.add_argument("source")
    copy_parser.add_argument("destination")
    copy_parser.add_argument("--into", action="store_true", help="Treat destination as a directory.")
    copy_parser.add_argument(
        "--conflict",
        choices=["fail", "skip", "rename", "overwrite"],
        default="fail",
        help="What to do when the destination already exists.",
    )
    copy_parser.add_argument(
        "--verify",
        choices=["none", "size", "sha256"],
        default="sha256",
        help="Verification mode after copy.",
    )
    copy_parser.add_argument("--dry-run", action="store_true", help="Show the copy target without writing.")
    copy_parser.set_defaults(func=command_copy)

    verify_parser = subparsers.add_parser("verify", help="Verify an existing source/destination pair.")
    verify_parser.add_argument("source")
    verify_parser.add_argument("destination")
    verify_parser.add_argument(
        "--mode",
        choices=["size", "sha256"],
        default="sha256",
        help="Verification mode.",
    )
    verify_parser.set_defaults(func=command_verify)

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
