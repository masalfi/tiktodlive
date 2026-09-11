"""Pengelola binary scrcpy: deteksi, unduh, verifikasi.

scrcpy tidak ikut disimpan di project (total ~46 MB untuk semua platform).
Binary yang cocok diunduh sekali saat dibutuhkan ke folder vendor/, lalu
dipakai terus. Kalau scrcpy sudah terpasang di sistem, itu yang dipakai.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.config import ROOT

log = logging.getLogger(__name__)

VENDOR_DIR = ROOT / "vendor"
RELEASE_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"

# Nama aset per platform. Kunci = (sistem, arsitektur dinormalisasi).
_ASSET_PATTERNS = {
    ("darwin", "arm64"): "scrcpy-macos-aarch64",
    ("darwin", "x86_64"): "scrcpy-macos-x86_64",
    ("windows", "amd64"): "scrcpy-win64",
    ("windows", "x86"): "scrcpy-win32",
    ("linux", "x86_64"): "scrcpy-linux-x86_64",
}


def _norm_arch() -> str:
    """Samakan penamaan arsitektur antar platform."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "amd64" if sys.platform == "win32" else "x86_64"
    if machine in ("i386", "i686", "x86"):
        return "x86"
    return machine


def current_platform_key() -> tuple[str, str]:
    system = "windows" if sys.platform == "win32" else sys.platform
    return (system, _norm_arch())


def platform_label() -> str:
    system, arch = current_platform_key()
    names = {"darwin": "macOS", "windows": "Windows", "linux": "Linux"}
    return f"{names.get(system, system)} ({arch})"


@dataclass
class ScrcpyInfo:
    """Di mana scrcpy ditemukan dan versinya."""

    path: str
    source: str            # "vendor" | "sistem" | "manual"
    version: str = ""

    @property
    def available(self) -> bool:
        return bool(self.path)


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def _vendor_binary() -> Path | None:
    """Cari scrcpy di folder vendor (hasil unduhan)."""
    if not VENDOR_DIR.exists():
        return None
    target = _exe("scrcpy")
    # Binary bisa di vendor/scrcpy-.../scrcpy atau langsung vendor/scrcpy
    direct = VENDOR_DIR / target
    if direct.exists():
        return direct
    for child in sorted(VENDOR_DIR.iterdir()):
        if not child.is_dir():
            continue
        candidate = child / target
        if candidate.exists():
            return candidate
    return None


def find_scrcpy(configured: str = "") -> ScrcpyInfo:
    """Urutan: path manual -> folder vendor -> PATH sistem."""
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return ScrcpyInfo(str(path), "manual", _probe_version(str(path)))

    vendor = _vendor_binary()
    if vendor is not None:
        return ScrcpyInfo(str(vendor), "vendor", _probe_version(str(vendor)))

    system = shutil.which("scrcpy")
    if system:
        return ScrcpyInfo(system, "sistem", _probe_version(system))

    return ScrcpyInfo("", "")


def _probe_version(path: str) -> str:
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    first = (proc.stdout or proc.stderr or "").strip().splitlines()
    return first[0] if first else ""


# ------------------------------------------------------------------ unduh

def fetch_release() -> dict:
    """Ambil metadata rilis terbaru dari GitHub."""
    import httpx

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(RELEASE_API, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        return response.json()


def pick_asset(release: dict) -> dict | None:
    """Pilih aset yang cocok untuk platform ini."""
    pattern = _ASSET_PATTERNS.get(current_platform_key())
    if pattern is None:
        return None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(pattern) and (name.endswith(".zip") or name.endswith(".tar.gz")):
            return asset
    return None


def _expected_hashes(release: dict) -> dict[str, str]:
    """Baca SHA256SUMS.txt dari rilis untuk verifikasi."""
    import httpx

    url = ""
    for asset in release.get("assets", []):
        if asset.get("name") == "SHA256SUMS.txt":
            url = asset.get("browser_download_url", "")
            break
    if not url:
        return {}
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            text = client.get(url).text
    except Exception:                               # noqa: BLE001
        return {}

    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[-1].lstrip("*")] = parts[0]
    return out


def download_scrcpy(progress=None) -> ScrcpyInfo:
    """Unduh + ekstrak scrcpy untuk platform ini.

    progress: callable(pesan, persen 0-100) - persen -1 berarti tak diketahui.
    Lempar RuntimeError kalau gagal.
    """
    import httpx

    def report(message: str, percent: int = -1) -> None:
        if progress:
            progress(message, percent)

    report("Mengambil info rilis scrcpy...", -1)
    release = fetch_release()
    asset = pick_asset(release)
    if asset is None:
        raise RuntimeError(
            f"Tidak ada binary scrcpy resmi untuk {platform_label()}. "
            "Install manual, lalu isi path-nya di Pengaturan."
        )

    name = asset["name"]
    url = asset["browser_download_url"]
    total = int(asset.get("size", 0))

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    archive = VENDOR_DIR / name

    report(f"Mengunduh {name} ({total / 1048576:.1f} MB)...", 0)
    digest = hashlib.sha256()
    got = 0
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(archive, "wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                        digest.update(chunk)
                        got += len(chunk)
                        if total:
                            report(f"Mengunduh... {got / 1048576:.1f}/{total / 1048576:.1f} MB",
                                   int(got * 100 / total))
    except Exception as exc:                        # noqa: BLE001
        archive.unlink(missing_ok=True)
        raise RuntimeError(f"Gagal mengunduh: {exc}") from exc

    # Verifikasi kalau checksum tersedia; kalau tidak, lanjut dengan peringatan.
    expected = _expected_hashes(release).get(name)
    if expected:
        actual = digest.hexdigest()
        if actual.lower() != expected.lower():
            archive.unlink(missing_ok=True)
            raise RuntimeError("Checksum tidak cocok - unduhan rusak atau tidak asli.")
        report("Checksum cocok.", 100)
    else:
        log.warning("SHA256SUMS.txt tidak tersedia, verifikasi dilewati")

    report("Mengekstrak...", 100)
    try:
        _extract(archive, VENDOR_DIR)
    finally:
        archive.unlink(missing_ok=True)

    info = find_scrcpy()
    if not info.available:
        raise RuntimeError("Ekstraksi selesai tapi binary scrcpy tidak ditemukan.")

    _make_executable(Path(info.path))
    report(f"Selesai: {info.version or 'scrcpy siap'}", 100)
    return info


def _extract(archive: Path, dest: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            _safe_extract_zip(zf, dest)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            _safe_extract_tar(tf, dest)


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Cegah path traversal (entri '../') dari arsip."""
    root = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if not str(target).startswith(str(root)):
            raise RuntimeError(f"Entri arsip mencurigakan: {member}")
    zf.extractall(dest)


def _safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(root)):
            raise RuntimeError(f"Entri arsip mencurigakan: {member.name}")
    tf.extractall(dest)


def _make_executable(path: Path) -> None:
    """Arsip tar kadang kehilangan bit executable; pastikan bisa dijalankan."""
    if sys.platform == "win32":
        return
    try:
        path.chmod(path.stat().st_mode | 0o755)
        # scrcpy butuh adb & server di sebelahnya juga executable
        for sibling in path.parent.iterdir():
            if sibling.is_file() and sibling.suffix in ("", ".so"):
                sibling.chmod(sibling.stat().st_mode | 0o755)
    except OSError as exc:
        log.warning("Gagal set izin executable: %s", exc)


def remove_vendor() -> bool:
    """Hapus scrcpy hasil unduhan (untuk unduh ulang)."""
    if not VENDOR_DIR.exists():
        return False
    removed = False
    for child in VENDOR_DIR.iterdir():
        if child.name.startswith("scrcpy"):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            removed = True
    return removed
