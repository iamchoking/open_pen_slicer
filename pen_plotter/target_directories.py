from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .settings import DOWNLOADS_DIR, TARGET_DOWNLOADS


DRIVE_REMOVABLE = 2


@dataclass(frozen=True)
class TargetDirectoryChoice:
    label: str
    path: Path
    settings_value: str
    is_removable: bool = False


def list_target_directories() -> list[TargetDirectoryChoice]:
    choices = [
        TargetDirectoryChoice(
            label="Downloads",
            path=DOWNLOADS_DIR,
            settings_value=TARGET_DOWNLOADS,
        )
    ]
    choices.extend(
        TargetDirectoryChoice(
            label=_drive_display_label(root),
            path=root,
            settings_value=str(root),
            is_removable=True,
        )
        for root in _removable_drive_roots()
    )
    return choices


def eject_target_directory(choice: TargetDirectoryChoice) -> None:
    if not choice.is_removable:
        raise RuntimeError("Only removable USB/SD target directories can be ejected.")
    eject_drive_root(choice.path)


def clear_gcode_files_from_target(choice: TargetDirectoryChoice) -> list[Path]:
    if not choice.is_removable:
        raise RuntimeError("Only removable USB/SD target directories can be cleared.")
    return clear_gcode_files_from_drive(choice.path)


def clear_gcode_files_from_drive(path: Path) -> list[Path]:
    root = _drive_root(path)
    if root is None or not _is_removable_drive_root(root):
        raise RuntimeError(f"Not a removable drive: {path}")
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Drive root is not available: {root}")

    matches: list[Path] = []
    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() != ".gcode":
            continue
        _ensure_path_is_within_root(candidate, root)
        matches.append(candidate)

    for candidate in matches:
        candidate.unlink()
    return matches


def eject_drive_root(path: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("Drive eject is only supported on Windows.")

    root = _drive_root(path)
    if root is None or not _is_removable_drive_root(root):
        raise RuntimeError(f"Not a removable drive: {path}")

    root_text = str(root).rstrip("\\/")
    command = (
        "& { "
        "param([Parameter(Mandatory=$true)][string]$root); "
        "$ErrorActionPreference = 'Stop'; "
        "$shell = New-Object -ComObject Shell.Application; "
        "$drive = $shell.Namespace(17).ParseName($root); "
        "if ($null -eq $drive) { throw \"Drive not found: $root\" }; "
        "$drive.InvokeVerb('Eject'); "
        "Start-Sleep -Milliseconds 800 "
        "}"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
            root_text,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Unknown eject failure").strip()
        raise RuntimeError(message)


def _removable_drive_roots() -> list[Path]:
    if os.name != "nt":
        return []

    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    roots: list[Path] = []
    for index in range(26):
        if not bitmask & (1 << index):
            continue
        root = f"{chr(65 + index)}:\\"
        root_path = Path(root)
        if _is_removable_drive_root(root_path) and root_path.exists():
            roots.append(root_path)
    return roots


def _drive_root(path: Path) -> Path | None:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    anchor = resolved.anchor
    if not anchor:
        return None
    return Path(anchor)


def _is_removable_drive_root(root: Path) -> bool:
    if os.name != "nt":
        return False
    root_text = str(root)
    if not root_text.endswith("\\"):
        root_text += "\\"
    return (
        ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root_text))
        == DRIVE_REMOVABLE
    )


def _ensure_path_is_within_root(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Refusing to delete outside removable drive: {path}") from exc


def _drive_display_label(root: Path) -> str:
    root_text = str(root)
    volume_name = _volume_name(root_text)
    name = volume_name or "Removable Drive"
    return f"{name} ({root_text})"


def _volume_name(root: str) -> str:
    if os.name != "nt":
        return ""

    kernel32 = ctypes.windll.kernel32
    name_buffer = ctypes.create_unicode_buffer(261)
    serial_number = ctypes.c_ulong()
    max_component_length = ctypes.c_ulong()
    file_system_flags = ctypes.c_ulong()
    file_system_name = ctypes.create_unicode_buffer(261)
    ok = kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root),
        name_buffer,
        len(name_buffer),
        ctypes.byref(serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(file_system_flags),
        file_system_name,
        len(file_system_name),
    )
    if not ok:
        return ""
    return name_buffer.value.strip()
