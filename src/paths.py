"""Path / asset resolution for both dev and PyInstaller-frozen runtimes (§4.4, §6.1).

Two runtime modes are supported with one API:
  * dev:    files live under ``<repo>/external/ndlocr-lite/src`` and the deps are
            in the project venv.
  * frozen: ``flet pack`` (PyInstaller) bundles the upstream ``src/`` tree under
            ``sys._MEIPASS``; our own modules sit at the bundle root.

Non-ASCII path resistance (§6.1) is layered here:
  (A) ``ascii_workspace()`` / ``model_dir()`` / ``config_dir()`` guarantee the
      paths handed to the C/native engine never contain non-ASCII characters.
  (B) ``relocate_if_needed()`` re-launches the frozen app from a fixed ASCII base
      if the install path itself is non-ASCII.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from _version import __version__
except Exception:  # pragma: no cover - defensive
    __version__ = "0.0.0+dev"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _is_ascii(p) -> bool:
    return str(p).isascii()


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _meipass() -> Path:
    return Path(sys._MEIPASS)  # type: ignore[attr-defined]


def _repo_root() -> Path:
    # src/paths.py -> src -> repo root
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# upstream src resolution
# --------------------------------------------------------------------------

def _upstream_candidates():
    if is_frozen():
        base = _meipass()
        # flet pack/PyInstaller --add-data lands the upstream tree under one of these.
        yield base / "ndlocr_src"
        yield base / "upstream" / "src"
        yield base / "src"
        yield base
    else:
        yield _repo_root() / "external" / "ndlocr-lite" / "src"


_upstream_src_cache: Path | None = None


def upstream_src_dir() -> Path:
    """Directory holding ``ocr.py`` / ``deim.py`` (and ``model/`` ``config/``)."""
    global _upstream_src_cache
    if _upstream_src_cache is not None:
        return _upstream_src_cache
    for cand in _upstream_candidates():
        if (cand / "ocr.py").is_file():
            _upstream_src_cache = cand
            return cand
    tried = ", ".join(str(c) for c in _upstream_candidates())
    raise FileNotFoundError(
        f"上流の ocr.py が見つかりません。探索した場所: {tried}"
    )


def ensure_upstream_importable() -> None:
    """Insert ``upstream_src_dir()`` at ``sys.path[0]`` (idempotent).

    Required so the engine's relative imports (``from deim import DEIM`` etc.) resolve.
    """
    src = str(upstream_src_dir())
    if sys.path and sys.path[0] == src:
        return
    while src in sys.path:
        sys.path.remove(src)
    sys.path.insert(0, src)


# --------------------------------------------------------------------------
# ASCII base + atomic, locked materialization (cache regime, Medium6)
# --------------------------------------------------------------------------

def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return True
    except Exception:
        return False


def ascii_base() -> Path:
    """A fixed, ASCII, user-independent base directory for caches/workspaces.

    Order: ``%PUBLIC%\\ndlocr-pdf`` (ASCII, not under the user profile) first,
    then an ASCII ``%LOCALAPPDATA%``, then the temp dir. Raises if none is usable.
    """
    candidates: list[Path] = []
    pub = os.environ.get("PUBLIC")
    candidates.append(Path(pub) if pub else Path(r"C:\Users\Public"))
    lad = os.environ.get("LOCALAPPDATA")
    if lad:
        candidates.append(Path(lad))
    candidates.append(Path(tempfile.gettempdir()))

    for c in candidates:
        base = c / "ndlocr-pdf"
        if _is_ascii(base) and _writable(base):
            return base
    raise RuntimeError(
        "ASCII の書き込み可能なフォルダが見つかりませんでした。"
        "管理者に連絡するか、C:\\Users\\Public への書き込み権限を確認してください。"
    )


def _acquire_lock(lock: Path, timeout: float = 120.0) -> bool:
    """Acquire a cross-process lock via atomic ``mkdir``. Returns False on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(parents=False, exist_ok=False)
            return True
        except FileExistsError:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)
        except Exception:
            return False


def _materialize(src: Path, final_dest: Path) -> Path:
    """Copy ``src`` -> ``final_dest`` atomically, serialized across processes.

    Uses a ``.complete`` sentinel so a partial (interrupted) copy is discarded
    and rebuilt on next start. No-op if a complete copy already exists.
    """
    sentinel = final_dest / ".complete"
    if sentinel.is_file():
        return final_dest

    final_dest.parent.mkdir(parents=True, exist_ok=True)
    lock = final_dest.parent / (final_dest.name + ".lock")
    got = _acquire_lock(lock)
    try:
        if sentinel.is_file():
            return final_dest
        if not got:
            # We could not serialize against another process. Do NOT touch the
            # cache directories (that would race the lock holder and could
            # corrupt the shared copy). Wait for the holder to publish the
            # sentinel and reuse its result; give up with a clear error if it
            # never appears.
            deadline = time.monotonic() + 120.0
            while time.monotonic() < deadline:
                if sentinel.is_file():
                    return final_dest
                time.sleep(0.5)
            raise RuntimeError(
                f"キャッシュの準備がタイムアウトしました: {final_dest}"
            )
        if final_dest.exists():
            shutil.rmtree(final_dest, ignore_errors=True)
        tmp = final_dest.parent / (final_dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp)
        (tmp / ".complete").write_text("ok", encoding="ascii")
        os.replace(tmp, final_dest)  # atomic on same volume
        return final_dest
    finally:
        if got:
            try:
                lock.rmdir()
            except Exception:
                pass


def _purge_old_versions(parent: Path) -> None:
    """Remove cache dirs for other versions to avoid disk bloat (best effort)."""
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name != __version__:
                shutil.rmtree(child, ignore_errors=True)
    except Exception:
        pass


# --------------------------------------------------------------------------
# model / config dirs (must be ASCII)
# --------------------------------------------------------------------------

def _asset_cache_root() -> Path:
    root = ascii_base() / __version__ / "assets"
    return root


def model_dir() -> Path:
    """Directory with ``*.onnx`` models, guaranteed ASCII (copies if needed)."""
    native = upstream_src_dir() / "model"
    if _is_ascii(native):
        return native
    _purge_old_versions(ascii_base())
    return _materialize(native, _asset_cache_root() / "model")


def config_dir() -> Path:
    """Directory with ``ndl.yaml`` / ``NDLmoji.yaml``, guaranteed ASCII."""
    native = upstream_src_dir() / "config"
    if _is_ascii(native):
        return native
    _purge_old_versions(ascii_base())
    return _materialize(native, _asset_cache_root() / "config")


# --------------------------------------------------------------------------
# ASCII workspace for per-run engine I/O
# --------------------------------------------------------------------------

def ascii_workspace() -> Path:
    """Create and return a unique, ASCII, writable working directory.

    The engine's input PDF, output files and searchable PDF all live under this
    directory, so the native layer never sees a non-ASCII path (§4.2, §6.1-A).
    Caller is responsible for cleanup (§5.3).
    """
    base = ascii_base() / "work"
    base.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix="run_", dir=str(base)))
    return ws


# --------------------------------------------------------------------------
# (B) ASCII self-relocation launcher (§6.1)
# --------------------------------------------------------------------------

def relocate_if_needed(argv: list[str]) -> bool:
    """If frozen and installed at a non-ASCII path, copy the payload to a fixed
    ASCII base and re-launch from there. Returns True if a relaunch was started
    (caller should exit immediately). Returns False to continue normally.

    Raises RuntimeError if relocation is required but impossible (last-resort
    case (C) is handled by the caller catching this and showing a JP dialog).
    """
    if not is_frozen():
        return False

    exe = Path(sys.executable)
    install_dir = exe.parent
    if _is_ascii(install_dir):
        return False  # already ASCII, nothing to do

    dest_install = ascii_base() / __version__ / "app"
    _purge_old_versions(ascii_base())
    _materialize(install_dir, dest_install)

    new_exe = dest_install / exe.name
    if not new_exe.is_file():
        raise RuntimeError(
            f"ASCII フォルダへの再配置に失敗しました（{new_exe} が見つかりません）。"
        )

    # Detach so the current (non-ASCII) process can exit cleanly.
    creationflags = 0
    DETACHED_PROCESS = 0x00000008
    if os.name == "nt":
        creationflags = DETACHED_PROCESS
    subprocess.Popen(
        [str(new_exe), *argv[1:]],
        cwd=str(dest_install),
        creationflags=creationflags,
        close_fds=True,
    )
    return True
