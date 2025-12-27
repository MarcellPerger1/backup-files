from pathlib import Path
from typing import Iterable

from .common import Clusivity, ExcludeMode
from .py_util import is_subpath, innermost_stem
from .rule import AbstractIncludeExclude, AbstractExclude


class SpecificPathRule(AbstractIncludeExclude):
    def __init__(self, clusivity: Clusivity, *paths: Path):
        super().__init__(clusivity)
        self.paths = paths

    def list_paths(self) -> Iterable[Path]:
        return self.paths

    def should_exclude(self, path: Path) -> ExcludeMode | bool:
        return any(is_subpath(path, p) for p in self.paths)


class NameExclude(AbstractExclude):
    def __init__(self, *names: str, strip_suffixes=False, keep_dir_self=False):
        self.names = names
        self.strip_suffixes = strip_suffixes
        self.keep_dir_self = keep_dir_self

    def fallback_keep_self(self, path: Path):
        return self.keep_dir_self

    def should_exclude(self, path: Path) -> ExcludeMode | bool:
        name = path.name if not self.strip_suffixes else innermost_stem(path)
        return name in self.names


class FileExtExclude(AbstractExclude):
    def __init__(self, *extensions: str, allow_empty_prefix=True):
        self.extensions = ['.' + e.removeprefix('.') for e in extensions]
        self.allow_empty_prefix = allow_empty_prefix

    def should_exclude(self, path: Path) -> ExcludeMode | bool:
        return path.is_file() and any(
            self.matches_ext(path.name, e) for e in self.extensions)

    def matches_ext(self, name: str, ext: str):
        return (name != ext or self.allow_empty_prefix) and name.endswith(ext)
