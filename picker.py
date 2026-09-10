"""Scanning and random-selection logic, independent of tkinter."""
from __future__ import annotations

import os
import random
from pathlib import Path


def normalized_path(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def normalize_extension(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    return "." + value.lstrip(".")


class FileScanner:
    def scan(self, root: str, extensions: set[str], excluded_folders: set[str],
             excluded_files: set[str], filename_filters: list[str], scope_enabled: dict[str, bool]) -> list[str]:
        if not root or not os.path.isdir(root) or not extensions:
            return []
        root_key = normalized_path(root)
        excluded_folders = {normalized_path(p) for p in excluded_folders}
        excluded_files = {normalized_path(p) for p in excluded_files}
        filters = [x.strip().casefold() for x in filename_filters if x.strip()]
        results: list[str] = []
        try:
            for current, dirs, files in os.walk(root, topdown=True, onerror=lambda _e: None):
                current_key = normalized_path(current)
                dirs[:] = [d for d in dirs if normalized_path(os.path.join(current, d)) not in excluded_folders]
                if current_key == root_key:
                    dirs[:] = [d for d in dirs if scope_enabled.get(d, True)]
                for name in files:
                    path = os.path.join(current, name)
                    if (Path(name).suffix.lower() in extensions and normalized_path(path) not in excluded_files
                            and not any(word in name.casefold() for word in filters)):
                        results.append(path)
        except OSError:
            pass
        return results


class RandomPicker:
    def __init__(self) -> None:
        self.pool: list[str] = []
        self.shuffle_queue: list[str] = []

    def set_pool(self, paths: list[str]) -> None:
        self.pool = list(paths)
        self.shuffle_queue = []

    def candidates(self, recent_history: list[str], recent_n: int) -> list[str]:
        """All allowed files, preserving equal probability for each file."""
        if not self.pool:
            return []
        n = max(0, int(recent_n))
        excluded = {normalized_path(p) for p in recent_history[:n]}
        choices = [p for p in self.pool if normalized_path(p) not in excluded and os.path.isfile(p)]
        if choices:
            return choices
        # N may cover every file: relax history rather than getting stuck.
        return [p for p in self.pool if os.path.isfile(p)]

    def choose(self, mode: str, history: list[str], recent_n: int) -> str | None:
        if mode == "shuffle":
            available = [p for p in self.pool if os.path.isfile(p)]
            available_keys = {normalized_path(p) for p in available}
            self.shuffle_queue = [p for p in self.shuffle_queue if normalized_path(p) in available_keys]
            if not self.shuffle_queue:
                self.shuffle_queue = available[:]
                random.shuffle(self.shuffle_queue)
            return self.shuffle_queue.pop() if self.shuffle_queue else None
        choices = self.candidates(history, recent_n) if mode == "recent" else [p for p in self.pool if os.path.isfile(p)]
        return random.choice(choices) if choices else None
