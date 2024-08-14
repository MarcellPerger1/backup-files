from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Flag
from pathlib import Path, PurePath

from py_util import assert_not_exotic, flatten


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
     - ``list_files`` returns a list of all the files matching ``self``
     - ``__init__`` of subclasses to instantiate these patterns

    API for implementors:
     - (**Required**) ``matches_self`` - returns True if a path matches
       ``self``, not taking into account the children
     - (Optional) ``matches_null`` - whether it matches a final null segment.
       Default: return ``False``
     - (Optional) ``get_subpath`` returns path to match children against
     - (Optional) ``is_final_component``
     - (Optional) ``current_component`` returns current segment of path
       being matched against in ``self`` (for use by implementors)
     - (Optional, but **recommended**) ``list_subpaths_matching_self`` returns
       a list of subdirectories of ``parent`` matching ``self``, not taking
       into account the children
     - (**Required for root patterns**) ``list_files_from_root`` list
       all paths matching ``self``, not taking children into account
     - (Optional, maybe don't override) ``has_allowed_fs_type``
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

    # region list_files() et al.
    def list_files(self, root: Path = None) -> list[Path]:
        return self.list_subpaths_matching(root)

    def list_subpaths_matching(self, parent: Path | None) -> list[Path]:
        """List all subpaths of ``parent`` matching ``self``.

        Here, parent is the directory above this and ``parent.iterdir()``
        gives the candidates for ``self`` to match."""
        return self._find_all_subpaths_from_subpatterns(
            self._filter_allowed_fs_types(
                self.list_subpaths_matching_self_or_root(parent)
            )
        )

    def list_subpaths_matching_self_or_root(self, parent: Path | None) -> list[Path]:
        if parent is None:
            return self.list_files_from_root()
        return self.list_subpaths_matching_self(parent)

    def list_files_from_root(self) -> list[Path]:
        raise TypeError("list_files_from_root must only be called on a root pattern")

    def list_subpaths_matching_self(self, parent: Path) -> list[Path]:
        """List all subpaths of ``parent`` matching ``self``,
        not taking into account subpatterns/children.

        This default implementation is inefficient,
        listing all the files in the dir and checking if they match.
        Implementors should provide a more efficient implementation if possible.

        Here, parent is the directory above this and ``parent.iterdir()``
        gives the candidates for ``self`` to match."""
        return [p for p in parent.iterdir()
                if self.has_allowed_fs_type(p)
                and self.matches_self(p.relative_to(parent), full_path=p)]

    def _find_all_subpaths_from_subpatterns(  # This name is so long!
            self, paths_matching_self: list[Path]) -> list[Path]:
        return flatten([self._find_subpaths_of_from_subpatterns(p)
                        for p in paths_matching_self])

    def _find_subpaths_of_from_subpatterns(self, p: Path) -> list[Path]:
        if not self.children:
            return [p]
        if p.is_file():
            return [p] if self._subpatterns_match_final(p, p) else []
        return flatten(sub.list_subpaths_matching(parent=p) for sub in self.children)

    def _filter_allowed_fs_types(self, paths: list[Path]) -> list[Path]:
        return [p for p in paths if self.has_allowed_fs_type(p)]
    # endregion

    # region match() et al.
    def match(self, p: Path):
        assert p.is_absolute()
        return self.matches_subpath(p, p)

    def matches_subpath(self, path: PurePath, full_path: Path) -> bool:
        # Wow, this is so readable!
        return (self._is_valid_for_current_type(path, full_path)
                and self.matches_self(path, full_path)
                and self._subpatterns_match(path, full_path))

    @abstractmethod
    def matches_self(self, path: PurePath, full_path: Path) -> bool:
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
        return (self.has_allowed_fs_type(full_path)
                and (len(self.children) == 0
                     or self._any_child_matches_null()))

    def _any_child_matches_null(self):
        for ch in self.children:
            if ch.matches_null():
                return True
        return False
    # endregion

    # region (overridable) one-liner utils for more readable code
    def has_allowed_fs_type(self, p: Path):
        return self.fs_type & FsTypeFlag.from_path(p)

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
    # endregion


class SingleNamePattern(AbstractPattern):
    def __init__(self, name: str,
                 fs_type: FsTypeFlag = None,
                 children: Sequence[AbstractPattern] = ()):
        if fs_type is None and name.endswith('/'):
            fs_type = FsTypeFlag.DIR
            name = name.removesuffix('/')
        self.name = name
        super().__init__(fs_type, children)

    def matches_self(self, path: PurePath, full_path: Path) -> bool:
        return self.current_component(path) == self.name

    def list_subpaths_matching_self(self, parent: Path) -> list[Path]:
        sub = parent / self.name
        return [sub] if sub.exists() and self.fs_type & FsTypeFlag.from_path(sub) else []


class RootPattern(AbstractPattern):
    """A root pattern (windows drive letter or '/' on Posix).
    Maybe could also represent some UNC path stuff
    but that isn't supported (yet???)."""
    def __init__(self, path: str | Path, children: Sequence[AbstractPattern]):
        path = Path(path)
        assert path.is_dir()
        assert path.is_absolute()
        assert len(path.parts) == 0
        self.root = path
        self.root_str = self.root.as_posix()
        super().__init__(FsTypeFlag.DIR, children)

    def matches_self(self, path: PurePath, full_path: Path) -> bool:
        assert path == full_path, "RootPattern must be at the bottom of the pattern tree."
        return self.current_component(path) == self.root_str

    def list_files_from_root(self) -> list[Path]:
        return list(self.root.iterdir())
