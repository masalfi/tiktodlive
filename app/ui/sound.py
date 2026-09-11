"""Pemutar suara berbasis Qt.

QSoundEffect butuh QApplication hidup, jadi pembuatannya ditunda sampai
GUI jalan (disuntikkan ke HostExecutor dari MainWindow).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def make_sound_player() -> Callable[[Path, float], tuple[bool, str]]:
    """Kembalikan fungsi play(path, volume) -> (ok, pesan)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QSoundEffect

    # Simpan referensi supaya efek tidak di-GC saat masih berbunyi.
    cache: dict[str, QSoundEffect] = {}

    def play(path: Path, volume: float) -> tuple[bool, str]:
        key = str(path)
        effect = cache.get(key)
        if effect is None:
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(key))
            cache[key] = effect
        effect.setVolume(max(0.0, min(1.0, volume)))
        effect.play()
        return True, "ok"

    return play
