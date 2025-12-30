from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .common import Clusivity, DeepBool
from .condition import AbstractCondition, ConditionalPath
from .fs_util import is_subpath, innermost_stem
from .rule import AbstractIncludeExclude, AbstractExclude


class SpecificPathRule(AbstractIncludeExclude):
    def __init__(self, clusivity: Clusivity, *paths: Path,
                 condition: AbstractCondition | None = None):
        super().__init__(clusivity)
        self.cond_paths = [ConditionalPath(p, condition) for p in paths]

    def _list_paths(self) -> Iterable[ConditionalPath]:
        return self.cond_paths

    def should_exclude(self, path: Path) -> DeepBool | bool:
        return any(is_subpath(path, cp.path) and cp.matches_subpath(path)
                   for cp in self.cond_paths)


class NameExclude(AbstractExclude):
    def __init__(self, *names: str, strip_suffixes=False, keep_dir_self=False):
        self.names = names
        self.strip_suffixes = strip_suffixes
        self.keep_dir_self = keep_dir_self

    def fallback_keep_self(self, path: Path):
        return self.keep_dir_self

    def should_exclude(self, path: Path) -> DeepBool | bool:
        name = path.name if not self.strip_suffixes else innermost_stem(path)
        return name in self.names


class FileExtExclude(AbstractExclude):
    def __init__(self, *extensions: str, allow_empty_prefix=True):
        self.extensions = ['.' + e.removeprefix('.') for e in extensions]
        self.allow_empty_prefix = allow_empty_prefix

    def should_exclude(self, path: Path) -> DeepBool | bool:
        return path.is_file() and any(
            self.matches_ext(path.name, e) for e in self.extensions)

    def matches_ext(self, name: str, ext: str):
        return (name != ext or self.allow_empty_prefix) and name.endswith(ext)
