"""General Python utils (not specific to this project)"""

from __future__ import annotations

import itertools
from pathlib import Path, PurePath
from typing import TypeVar, TypeGuard, Iterable, Callable, Iterator

T = TypeVar('T')
KT = TypeVar('KT')
PT = TypeVar('PT', bound=PurePath)


# Note: this must be TypeGuard NOT TypeIs because
#  true => iterable
#  BUT false does NOT => non-iterable
#   (because this returns False for str which is technically an iterable)
def _is_actual_iterable(o: object) -> TypeGuard[Iterable]:
    if isinstance(o, (str, bytes)):
        # Special case - technically 'iterables' but not in a useful way for us here
        return False
    try:
        iter(o)  # type: ignore
    except (TypeError, NotImplementedError):
        return False
    return True


# Note: `|` is NOT commutative (as it checks LHS first to see if it matches that)
# So here, `T | Iterable` would mean that the type param of `ls`
#  always gets bound to `T` (even if it is iterable) as it always matches `T`
def flatten(ls: Iterable[Iterable[T] | T]) -> list[T]:
    return [item for sub in ls for item in (sub if _is_actual_iterable(sub) else [sub])]


def group_by(it: Iterable[T], key: Callable[[T], KT]) -> Iterator[tuple[KT, Iterator[T]]]:
    """Same as itertools.groupby but with types that Pycharm recognizes"""
    return itertools.groupby(it, key=key)


def assert_not_exotic(p: Path):
    """Assert that ``p`` is a regular file or directory."""
    assert p.is_file() or p.is_dir(), "Must not be an exotic fs object (e.g. symlink)"


def get_path_root_and_drv(p: PT) -> PT:
    return Path(p).parents[-1]


def get_path_without_anchor(p: PT) -> PT:
    return p.relative_to(get_path_root_and_drv(p))
