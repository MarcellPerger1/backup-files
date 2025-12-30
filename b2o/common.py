from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum, IntEnum
from pathlib import Path


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
        raise OSError("FsType (and b2o in general) cannot handle exotic"
                      " objects (e.g. symlinks)")

    def matches_path(self, path: Path):
        return self == FsType.from_path(path)


class Clusivity(IntEnum):
    EXCLUDE = 0
    INCLUDE = 1


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
    def lowest_maximum(cls, fs_type: FsType):
        """Returns the smallest value v such that
        ``v.normalize(fs_type) == DeepBool.ALL``"""
        return cls.ALL if fs_type == FsType.DIR else cls.SHALLOW
