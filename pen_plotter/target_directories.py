from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

from .settings import DOWNLOADS_DIR, TARGET_DOWNLOADS


DRIVE_REMOVABLE = 2


@dataclass(frozen=True)
class TargetDirectoryChoice:
    label: str
    path: Path
    settings_value: str


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
        )
        for root in _removable_drive_roots()
    )
    return choices


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
        if (
            kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE
            and root_path.exists()
        ):
            roots.append(root_path)
    return roots


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
