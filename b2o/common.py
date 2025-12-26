from __future__ import annotations

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
    CONTENTS = 1
    ALL = 2

    def exclude_contents(self):
        return self >= ExcludeMode.CONTENTS

    def exclude_self(self):
        return self >= ExcludeMode.ALL
