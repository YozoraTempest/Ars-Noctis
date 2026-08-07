"""Crash-safe document storage and ownership locks for Noctis Exec."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterator

from exec_errors import NoctisError


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        raise NoctisError(f"file does not exist: {path}") from error


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def pid_alive(pid: Any) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return True
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reclaim_dead_lock(lock_path: Path) -> bool:
    try:
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(owner, dict) or pid_alive(owner.get("pid")):
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    return True


@contextlib.contextmanager
def document_lock(path: Path) -> Iterator[None]:
    lock_path = path.parent / f".{path.name}.noctis.lock"
    token = uuid.uuid4().hex
    owner = {"pid": os.getpid(), "token": token}
    for attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as error:
            if attempt or not reclaim_dead_lock(lock_path):
                raise NoctisError(f"document is locked: {path}") from error
    else:
        raise NoctisError(f"document is locked: {path}")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(owner, stream)
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8"))
            if current.get("token") == token:
                lock_path.unlink()
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            pass
