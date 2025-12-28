from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum, IntEnum
from pathlib import Path

from .py_util import assert_not_exotic


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
        raise assert_not_exotic(path)

    def matches_path(self, path: Path):
        return self == FsType.from_path(path)


class Clusivity(IntEnum):
    EXCLUDE = 0
    INCLUDE = 1


class ExcludeMode(IntEnum):
    # Note: inherits __bool__ from int
    NO = 0
    CONTENTS = 1  # or SHALLOW
    ALL = 2

    def exclude_contents(self):
        return self >= ExcludeMode.CONTENTS

    def exclude_self(self):
        return self >= ExcludeMode.ALL

    def is_completely_excluded(self, fs_type: FsType):
        return (self == ExcludeMode.ALL or
                (fs_type == FsType.FILE and self == ExcludeMode.CONTENTS))

    @classmethod
    def max(cls, modes: Iterable[ExcludeMode], fs_type: FsType):
        result = ExcludeMode.NO
        for m in modes:
            result = max(result, m)
            if result.is_completely_excluded(fs_type):
                return ExcludeMode.ALL
        return result

    @classmethod
    def min(cls, modes: Iterable[ExcludeMode]):
        result = ExcludeMode.ALL
        for m in modes:
            result = min(result, m)
            if result == ExcludeMode.NO:
                return ExcludeMode.NO
        return result


class DeepBool(IntEnum):
    NONE = 0
    SHALLOW = 1
    ALL = 2

    def __invert__(self) -> DeepBool:
        return type(self)(2 - self)

    def __or__(self, other):
        return max(self, other)

    def __and__(self, other):
        return min(self, other)

    def normalize(self, fs_type: FsType):
        if fs_type == FsType.FILE and self == DeepBool.SHALLOW:
            return DeepBool.ALL
        return self

    def equals(self, other: DeepBool, fs_type: FsType):
        return self.normalize(fs_type) == other.normalize(fs_type)

    def is_max(self, fs_type: FsType):
        return self >= self.lowest_maximum(fs_type)

    @classmethod
    def any(cls, bools: Iterable[DeepBool], fs_type: FsType = FsType.DIR):
        # max(bools) but short-circuiting (next() may often be super-expensive)
        result = cls.NONE
        for b in bools:
            result |= b
            if result.is_max(fs_type):
                return cls.ALL
        return result

    @classmethod
    def all(cls, bools: Iterable[DeepBool]):
        # min(bools) but short-circuiting (next() may often be super-expensive)
        result = cls.ALL
        for b in bools:
            result &= b
            if result == cls.NONE:
                return result
        return result

    @classmethod
    def from_is_excluded(cls, excl_mode: ExcludeMode):
        return cls(excl_mode)

    @classmethod
    def from_not_excluded(cls, excl_mode: ExcludeMode):
        return ~cls.from_is_excluded(excl_mode)

    @classmethod
    def lowest_maximum(cls, fs_type: FsType):
        """Returns the smallest value v such that
        ``v.normalize(fs_type) == DeepBool.ALL``"""
        return cls.ALL if fs_type == FsType.DIR else cls.SHALLOW
