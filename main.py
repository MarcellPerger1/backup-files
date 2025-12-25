from __future__ import annotations

import os
import os.path
import re
import shutil
from abc import ABC, abstractmethod
from enum import StrEnum, IntEnum
from pathlib import Path
from typing import Sequence

from patterns import AbstractPattern
from py_util import flatten, group_by, assert_not_exotic
from stats import Stats


class FsType(StrEnum):
    FILE = 'file'
    DIR = 'dir'
    # TODO: symlinks/exotic stuff

    @classmethod
    def from_path(cls, path: Path):
        if path.is_file():
            return cls.FILE
        if path.is_dir():
            return cls.DIR
        assert_not_exotic(path)

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


class AbstractExclude(ABC):
    @abstractmethod
    def should_exclude(self, path: Path, /, fs_type: FsType) -> bool:
        return False


class AbstractFileExclude(AbstractExclude, ABC):
    """Exclude a file"""


class AbstractDirExclude(AbstractExclude, ABC):
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
        return ExcludeDirMode.CONTENTS if self.should_keep_self() else ExcludeDirMode.ALL


class FileExtExclude(AbstractFileExclude):
    def __init__(self, *ext: str):
        self.extensions = {e.removeprefix('.') for e in ext}

    def should_exclude(self, file: Path, /, fs_type: FsType) -> bool:
        _name, _, ext = file.name.rpartition('.')  # faster than the builtin .suffix!
        return ext in self.extensions


class NameExclude(AbstractFileExclude, AbstractDirExclude):
    def __init__(self, *names: str, fs_type: FsType | None = None,
                 keep_self: bool = False):
        AbstractDirExclude.__init__(self, keep_self)
        self.names = set(names)
        self.fs_type = fs_type

    def should_exclude(self, path: Path, /, fs_type: FsType) -> bool:
        if self.fs_type is not None and not self.fs_type.matches_path(path):
            return False
        return path.name in self.names


class PatternExclude(AbstractFileExclude, AbstractDirExclude):
    def __init__(self, pat: AbstractPattern):
        # Don't keep self:
        #  - If a dir pattern has no children it will match the dir and
        #    everything below so deletes everything (e.g. a/dir/ in gitignore)
        #  - If a dir pattern has a single `*` child (= match everything),
        #    it will leave the dir and will remove everything below
        AbstractDirExclude.__init__(self, keep_self=False)
        self.pat = pat

    def should_exclude(self, path: Path, /, fs_type: FsType) -> bool:
        return self.pat.match(path)


class AbstractInclude(ABC):
    # Quite a minimal API so implementors have to decide
    # how to go about finding the paths of interest
    @abstractmethod
    def get_paths(self) -> Sequence[Path]:
        return []


class AbstractFileInclude(AbstractInclude, ABC):
    """Include a file"""


class AbstractDirInclude(AbstractInclude, ABC):
    """Include a dir"""


class PathInclude(AbstractFileInclude, AbstractDirInclude):
    def __init__(self, *paths: Path):
        self.paths = paths

    def get_paths(self) -> Sequence[Path]:
        return self.paths


class PatternInclude(AbstractFileInclude, AbstractDirInclude):
    def __init__(self, pat: AbstractPattern):
        self.pat = pat

    def get_paths(self) -> Sequence[Path]:
        return self.pat.list_files()  # And hope it's a root pattern


class ListFiles:
    """NOTE: decls has later overrides earlier in all cases.
    It must also start with an include block (exclude would be useless
    at the start as it only excludes from the stuff before it)"""
    def __init__(self, *decls: AbstractInclude | AbstractExclude):
        self.decls: list[AbstractInclude | AbstractExclude] = list(decls)
        self.stats = Stats()
        self.dirs: set[Path] = set()
        """^ WARNING: this won't add the contents/files in each of these,
        just the dirs themselves"""
        self.files: set[Path] = set()

    def list_files(self):
        include_blocks, exclude_blocks = self._group_declarations()
        for i, includes in enumerate(include_blocks):  # For each include,
            excludes = flatten(exclude_blocks[i:])  # Use the excludes below it
            self._walk(includes, excludes)  # And add `includes - excludes_below_it`

    _IEBlocksTup = tuple[list[list[AbstractInclude]], list[list[AbstractExclude]]]

    def _group_declarations(self) -> _IEBlocksTup:
        """Returns consecutive blocks of includes/excludes

        Source will be: ``i0, e0, i1, e1, ..., in[, en]``
        where each item can be 1+ decls.

        This function parses the list of decls into
        ``([i0, i1, ..., in], (e0, e1, ..., en])``"""
        def group_key(v: AbstractInclude | AbstractExclude):
            if isinstance(v, AbstractInclude): return 0
            elif isinstance(v, AbstractExclude): return 1
            assert 0, "only include and exclude declarations are allowed"

        assert len(self.decls) > 0, "Expected some declarations"
        assert isinstance(self.decls[0], AbstractInclude), (
            "Include must come first (if exclude is first, "
            "it would only apply to stuff before it (i.e. nothing))")
        ie_blocks = [], []
        for k, group in group_by(self.decls, key=group_key):
            ie_blocks[k].append(list(group))
        return ie_blocks

    def _walk(self, includes: Sequence[AbstractInclude],
              excludes: Sequence[AbstractExclude]):
        """Lists all files and dirs, adding ``includes - excludes`` to self"""
        excludes = list(excludes)
        roots = set()
        for o in includes:
            for p in o.get_paths():
                self._assert_not_exotic(p)
                if p.is_file():
                    self._add_file_with_excludes(excludes, p)
                else:
                    roots.add(p)
        return self._walk_roots(roots, excludes)

    def _walk_roots(self, roots: set[Path], excludes: list[AbstractExclude]):
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

                excl_mode = self.get_dir_exclude_mode(excludes, dirpath)
                if not excl_mode.exclude_self():
                    self.add_dir_only(dirpath)
                if excl_mode.exclude_contents():
                    dirs.clear()  # Don't recurse into dirs
                    continue  # Don't add content (skip the code below)

                for file in files:
                    self._add_file_with_excludes(excludes, dirpath / file)
                # Don't do anything with the dirs here, will handle them
                #  when os.walk() recursively goes into them (topdown)

    def _add_file_with_excludes(self, excludes: list[AbstractExclude], file: Path):
        assert file.is_file(), "Expected a file, not dir/exotic"
        if not self.should_exclude_file(excludes, file):
            self.add_file(file)

    # noinspection PyMethodMayBeStatic
    def should_exclude_file(self, excludes: list[AbstractExclude], file: Path):
        for e in excludes:
            if isinstance(e, AbstractFileExclude) and e.should_exclude(file, FsType.FILE):
                return True
        return False

    # noinspection PyMethodMayBeStatic
    def get_dir_exclude_mode(self, excludes: list[AbstractExclude], path: Path):
        result = ExcludeDirMode.NO
        for e in excludes:
            if not isinstance(e, AbstractDirExclude):
                continue
            # Largest value (= largest amount excluded) wins
            result = max(result, e.exclude_mode_for(path, FsType.DIR))
            if result == ExcludeDirMode.ALL:
                # Excluding everything already, no need to go further
                return result
        return result

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

    @staticmethod
    def _assert_not_exotic(path: Path):
        """Assert that path is a regular file or a directory"""
        assert path.is_file() or path.is_dir(), (
            "Exotic structures (e.g. symlinks) are not currently supported")

# TODO: for intra-file progress bar (Windows API):
#  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfile2,
#  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfileexa
#  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nc-winbase-lpprogress_routine


class BackupExecutor:
    def __init__(self, file_lister: ListFiles, dest_root: Path):
        self.lister = file_lister
        self.dest = dest_root
        self.home = self.detect_home()
        self._dirs_remaining: set[Path] = set()
        self._dirs_added: set[Path] = set()

    def run(self):
        # TODO: an iterator would be more efficient perhaps,
        #  especially if destination is slower (so bottleneck is
        #  dest so must start using it as soon as possible)
        self.lister.list_files()
        # Strategy: Add all the files, then add the empty dirs that haven't
        # been added along with them (as they contained no files)
        self._dirs_remaining = set(self.lister.dirs)
        for f in self.lister.files:
            self.add_file(f)  # TODO Parallel?
        while self._dirs_remaining:
            self.add_dir(self._dirs_remaining.pop())

    def add_file(self, srcfile: Path):
        destfile = self.get_dest_path(srcfile)
        self._create_dir(destfile.parent)
        shutil.copy2(srcfile, destfile)

    def add_dir(self, srcdir: Path):
        destdir = self.get_dest_path(srcdir)
        self._create_dir(destdir)

    def _dir_exists(self, d: Path):
        return d in self._dirs_added or d.exists()

    def _create_dir(self, d: Path, remove_from_remaining: bool = True):
        if not self._dir_exists(d):
            self._create_dir(d.parent)
            d.mkdir()  # TODO: copystat on dirs?
        self._dirs_added.add(d)
        if remove_from_remaining:
            self._dirs_remaining.discard(d)

    def get_dest_path(self, path: Path):
        assert path.is_absolute()
        if (dest := self._try_dest_rel_home(path)) is not None:
            return dest
        anchor_path = path.parents[-1]
        return self.dest / self._get_drive_id(path) / path.relative_to(anchor_path)

    WINDOWS_DRIVE_RE = re.compile(r'(\w):[\\/]')

    def _get_drive_id(self, path: Path):
        if path.anchor in ('/', '', '\\'):
            return '__root__'
        if m := self.WINDOWS_DRIVE_RE.fullmatch(path.anchor):
            return m.group(1)   # e.g. C:/ -> C
        return self.escape_string(path.anchor)

    def _try_dest_rel_home(self, path: Path):
        if self.home is None:
            return None
        try:
            rel_home = path.relative_to(self.home)
        except RuntimeError:
            return None
        return self.dest / '__home__' / rel_home

    @classmethod
    def detect_home(cls):
        try:
            return Path('~').expanduser()
        except RuntimeError:
            return None

    PATH_UNSAFE_RE = re.compile(r'[^\w-.]')

    @classmethod
    def escape_string(cls, s: str):
        def replacer(m: re.Match[str]):
            num = ord(m.group(0))
            if 0 <= num <= 255:
                return f'+x{num:>02X}'
            return f'+U{num:>08X}'

        return cls.PATH_UNSAFE_RE.sub(replacer, s)
