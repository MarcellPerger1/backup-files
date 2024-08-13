from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Flag
from pathlib import Path, PurePath

from py_util import assert_not_exotic


class FsTypeFlag(Flag):
    FILE = 1
    DIR = 2
    BOTH = FILE | DIR

    @classmethod
    def from_path(cls, p: Path):
        if p.is_file():
            return cls.FILE
        if p.is_dir():
            return cls.DIR
        assert_not_exotic(p)


FILE = FsTypeFlag.FILE
DIR = FsTypeFlag.DIR


class AbstractPattern(ABC):
    """Represents any file/dir-matching pattern.

    API for users:
     - ``match`` returns a ``bool`` indicating whether ``self`` matches a path
     - TODO: ``list_files`` returns a list/iterable of all the files matching ``self``
     - ``__init__`` of subclasses to instantiate these patterns

    API for implementors:
     - (**Required**) ``matches_self`` - returns True if a path matches
       ``self``, not taking into account the children
     - (Optional) ``matches_null`` - whether it matches an final null segment.
       Default: return ``False``
     - (Optional) ``get_subpath`` returns path to match children against
     - (Optional) ``is_final_component``
     - (Optional) ``current_component`` returns current segment of path
       being matched against in ``self`` (for use by implementors)
     - (**Required**) TODO something to do with listing files
    """

    def __init__(self, fs_type: FsTypeFlag = None,
                 children: Sequence[AbstractPattern] = ()):
        # TODO: if perf of this bad, use a bit of caching of upper levels results
        #  as when checking many deep paths, the first few parts will be
        #  the same but will need to be checked a TON
        self.children = children
        self.fs_type = self._get_fs_type(fs_type)

    def _get_fs_type(self, fs_type: FsTypeFlag = None):
        if fs_type is not None:
            if fs_type == FsTypeFlag.FILE:
                assert len(self.children) == 0, "Cannot have children in a file-only pattern"
            return fs_type
        if len(self.children) > 0:
            return FsTypeFlag.DIR  # must be dir if it has children
        return FsTypeFlag.BOTH

    def match(self, p: Path):
        return self.matches_subpath(p, p)

    def matches_subpath(self, path: PurePath, full_path: Path):
        # Wow, this is so readable!
        return (self._is_valid_for_current_type(path, full_path)
                and self.matches_self(path, full_path)
                and self._subpatterns_match(path, full_path))

    @abstractmethod
    def matches_self(self, path: PurePath, full_path: Path):
        ...

    def _is_valid_for_current_type(self, path: PurePath, full_path: Path):
        actual_type_flag = (FsTypeFlag.DIR if not self.is_final_component(path)
                            else FsTypeFlag.from_path(full_path))
        return self.fs_type & actual_type_flag

    def _subpatterns_match(self, path: PurePath, full_patch: Path):
        return (
            self._subpatterns_match_final(path, full_patch) if self.is_final_component(path)
            else self._subpatterns_match_path(path, full_patch))

    def _subpatterns_match_path(self, path, full_path):
        if not self.children:
            return True
        subpath = self.get_subpath(path)
        for ch in self.children:
            if ch.matches_subpath(subpath, full_path):
                return True
        return False

    def _subpatterns_match_final(self, _path: PurePath, full_path: Path):
        actual_type_flag = FsTypeFlag.from_path(full_path)
        if not self.fs_type & actual_type_flag:
            return False
        if not self.children:
            return True
        for ch in self.children:
            if ch.matches_null():
                return True
        return False

    # Not static so that is can be overridden by 'shortcut' matchers
    #  (i.e. matchers matching multiple levels)
    # noinspection PyMethodMayBeStatic
    def get_subpath(self, path: PurePath):
        # Relative to first inner dir = remove first dir, then return
        return path.relative_to(Path(*path.parts[:1]))

    @classmethod
    def is_final_component(cls, path: PurePath):
        return len(path.parts) == 1

    # noinspection PyMethodMayBeStatic
    def matches_null(self):
        return False

    # noinspection PyMethodMayBeStatic
    def current_component(self, path: PurePath):
        return path.parts[0].replace('\\', '/')


class SingleNamePattern(AbstractPattern):
    def __init__(self, name: str,
                 fs_type: FsTypeFlag = None,
                 children: Sequence[AbstractPattern] = ()):
        self.name = name
        if fs_type is None and name.endswith('/'):
            fs_type = FsTypeFlag.DIR
        super().__init__(fs_type, children)

    def matches_self(self, path: PurePath, full_path: Path):
        return self.current_component(path) == self.name
