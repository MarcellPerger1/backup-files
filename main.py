from __future__ import annotations

import os
import os.path
import shutil
import warnings
from abc import ABC, abstractmethod
from enum import StrEnum, IntEnum
from pathlib import Path
from typing import Sequence

from py_util import flatten


class FsType(StrEnum):
    FILE = 'file'
    DIR = 'dir'
    OTHER = 'other'  # TODO: symlinks?

    @classmethod
    def from_path(cls, path: Path):
        if path.is_file():
            return cls.FILE
        if path.is_dir():
            return cls.DIR
        return cls.OTHER

    def matches_path(self, path: Path):
        return self == FsType.from_path(path)


class ExcludeDirMode(IntEnum):
    # Note: inherits __bool__ from int
    NO = 0
    CONTENTS = 1
    ALL = 2

    def exclude_contents(self):
        return self >= ExcludeDirMode.CONTENTS

    def exclude_self(self):
        return self >= ExcludeDirMode.ALL


class _IAnyExclude(ABC):
    @abstractmethod
    def should_exclude(self, path: Path, /, fs_type: FsType) -> bool:
        return False


class IFileExclude(_IAnyExclude, ABC):
    """Exclude a file"""


class IDirExclude(_IAnyExclude, ABC):
    """Exclude dir itself (and contents)"""

    def __init__(self, keep_self: bool = False):
        self.keep_self = keep_self

    def should_keep_self(self):
        """Used to determine whether to keep the directory itself without
        any of the contents. Only called if should_exclude() is True."""
        return self.keep_self

    def exclude_mode_for(self, path: Path, fs_type: FsType):
        assert fs_type == FsType.DIR
        if not self.should_exclude(path, fs_type):
            return ExcludeDirMode.NO


class FileExtExclude(IFileExclude):
    def __init__(self, *ext: str):
        self.extensions = {e.removeprefix('.') for e in ext}

    def should_exclude(self, file: Path, /, fs_type: FsType) -> bool:
        _name, _, ext = file.name.rpartition('.')  # faster than the builtin .suffix!
        return ext in self.extensions


class NameExclude(IFileExclude, IDirExclude):
    def __init__(self, *names: str, fs_type: FsType | None = None,
                 keep_self: bool = False):
        super().__init__(keep_self)
        self.names = set(names)
        self.fs_type = fs_type

    def should_exclude(self, path: Path, /, fs_type: FsType) -> bool:
        if self.fs_type is not None and not self.fs_type.matches_path(path):
            return False
        return path.name in self.names


class _IAnyInclude(ABC):
    # Quite a minimal API so implementors have to decide
    # how to go about finding the paths of interest
    @abstractmethod
    def get_paths(self) -> Sequence[Path]:
        return []


class IFileInclude(_IAnyInclude, ABC):
    """Include a file"""


class IDirInclude(_IAnyInclude, ABC):
    """Include a dir"""


class Stats:
    def __init__(self):
        self.n_files = 0
        self.n_dirs = 0
        # These only include the files (du of dirs would give excluded as well)
        self.bytes_to_copy_ls = 0
        self.bytes_to_copy_du = 0
        self._size_cache: dict[Path, tuple[int, int]] = {}

    def lookup_sizes(self, file: Path):
        try:
            result = self._size_cache[file]
        except KeyError:
            warnings.warn("File not found in cache - this will give "
                          "wrong results if file is changed")
            result = self._size_cache[file] = self._calc_size(file)
        return result

    def _add_to_totals(self, sizes: tuple[int, int]):
        self.bytes_to_copy_ls += sizes[0]
        self.bytes_to_copy_du += sizes[1]

    def _sub_from_totals(self, sizes: tuple[int, int]):
        self.bytes_to_copy_ls -= sizes[0]
        self.bytes_to_copy_du -= sizes[1]

    @classmethod
    def _calc_size(cls, file: Path):
        return file.stat().st_size, shutil.disk_usage(file).used

    def add_file(self, file: Path):
        self.n_files += 1
        self._add_to_totals(self.lookup_sizes(file))

    def remove_file(self, file: Path):
        self.n_files -= 1
        self._sub_from_totals(self.lookup_sizes(file))

    def add_dir(self, _path: Path):
        self.n_dirs += 1


class ListFiles:
    def __init__(self):
        self.stats = Stats()
        self.dirs: set[Path] = set()
        """^ WARNING: this won't add the contents/files in each of these,
        just the dirs themselves"""
        self.files: set[Path] = set()
        # Consecutive blocks of includes/excludes
        # Note: later overrides earlier
        # Note: must start with an include block (an exclude would be useless at start)
        # Note: source will be in format i0, e0, i1, e1, ..., in[, en]
        self.include_blocks: list[list[...]] = []
        self.exclude_blocks: list[list[...]] = []

    def add_file(self, file: Path):
        if file in self.files:
            return
        self.stats.add_file(file)
        self.files.add(file)

    def add_dir_only(self, path: Path):
        """WARNING: doesn't add children, only the dir itself"""
        if path not in self.dirs:
            return
        self.stats.add_dir(path)
        self.dirs.add(path)

    def remove_file(self, file: Path):
        # Note: don't use internally - should not have been added
        #  in the first place (excludes are applied during each 'include walk')
        if file not in self.files:
            return
        self.stats.remove_file(file)
        self.files.remove(file)

    # noinspection PyMethodMayBeStatic
    def should_exclude_file(self, excludes: list[_IAnyExclude], file: Path):
        for e in excludes:
            if isinstance(e, IFileExclude) and e.should_exclude(file, FsType.FILE):
                return True
        return False

    # noinspection PyMethodMayBeStatic
    def get_exclude_mode(self, excludes: list[_IAnyExclude], path: Path):
        result = ExcludeDirMode.NO
        for e in excludes:
            if not isinstance(e, IDirExclude):
                continue
            # Largest value (= largest amount excluded) wins
            result = max(result, e.exclude_mode_for(path, FsType.DIR))
            if result == ExcludeDirMode.ALL:
                # Excluding everything already, no need to go further
                return result
        return result

    def _walk_roots(self, roots: set[Path], excludes: list[_IAnyExclude]):
        visited_dirs: set[Path] = set()
        for root in roots:
            assert root.is_dir(), "Cannot have a non-dir root in _walk"
            for dir_str, dirs, files in os.walk(root.expanduser().resolve()):
                dirpath = Path(dir_str).resolve()
                if dirpath in visited_dirs:
                    # Already visited this tree, don't visit children
                    dirs.clear()
                    continue
                visited_dirs.add(dirpath)

                excl_mode = self.get_exclude_mode(excludes, dirpath)
                if not excl_mode.exclude_self():
                    self.add_dir_only(dirpath)
                if excl_mode.exclude_contents():
                    dirs.clear()  # Don't recurse into dirs
                    continue  # Don't add content (skip the code below)

                for file in files:
                    filepath = dirpath / file
                    assert filepath.is_file(), \
                        "Found exotic structure (e.g. junction/symlink)"
                    if not self.should_exclude_file(excludes, filepath):
                        self.add_file(filepath)
                # Don't do anything with the dirs here, will handle them
                #  when os.walk() recursively goes into them (topdown)

    def _walk(self, includes: Sequence[_IAnyInclude], excludes: Sequence[_IAnyExclude]):
        """Lists all files and dirs, adding ``includes - excludes`` to self"""
        roots = set()
        for o in includes:
            for p in o.get_paths():
                if p.is_file():
                    self.add_file(p)
                else:
                    assert p.is_dir(), "Exotic structures (e.g. symlinks) aren't supported"
                    roots.add(p)
        return self._walk_roots(roots, list(excludes))

    def list_files(self):
        for i, includes in enumerate(self.include_blocks):  # For each include,
            excludes = flatten(self.exclude_blocks[i:])  # Use the excludes below it
            self._walk(includes, excludes)  # And add `includes - excludes_below_it`


class Backup:
    def __init__(self):
        ...
