from __future__ import annotations

import math
import os
import sys
from pathlib import PurePath, Path
from typing import TypeVar

PT = TypeVar('PT', bound=PurePath)


def assert_not_exotic(p: Path):
    """Assert that ``p`` is a regular file or directory."""
    assert p.is_file() or p.is_dir(), "Must not be an exotic fs object (e.g. symlink)"


def is_subpath(sub: Path, sup: Path, resolve=True):
    if resolve:
        # NOTE: This doesn't take into account symlinks
        sub = Path(os.path.abspath(sub))
        sup = Path(os.path.abspath(sup))
    return sub == sup or sup in sub.parents


def innermost_stem(p: Path):
    name = p.name
    without_leading_dots = name.lstrip('.')
    leading_dots = '.' * (len(name) - len(without_leading_dots))
    stem_no_leading_dots, *_ = without_leading_dots.split('.', maxsplit=1)
    return leading_dots + stem_no_leading_dots


def get_path_anchor(p: PT) -> PT:
    return Path(p).parents[-1]


def get_path_without_anchor(p: PT) -> PT:
    return p.relative_to(get_path_anchor(p))


def get_size_on_disk(p: Path, st: os.stat_result | None = None):
    st = st or p.stat()
    if HAS_ST_STAT:
        try:
            return st.st_blocks * 512
        except AttributeError:
            pass
    size = st.st_size
    if sys.platform == 'win32':  # Good-enough check for NTFS
        # NTFS: File data is stored in rest of the 1KiB block if it fits
        # File name and other stuff also takes up space there.
        # Empirically, it fits in the file table entry if
        # size < 731 - path length
        if size < 720 - len(str(p)):  # Go with 720 as there may be extra metadata
            return 0
    return math.ceil(size / 4096) * 4096


HAS_ST_STAT = hasattr(os.stat_result, 'st_blocks')
