from __future__ import annotations

import os
import os.path
from pathlib import Path
from typing import Sequence

from .py_util import flatten, group_by
from .stats import Stats
from .common import ExcludeMode as ExcludeDirMode, Clusivity
from .rule import AbstractInclusionRule, AbstractInclude, AbstractExclude


class ListFiles:
    """NOTE: decls has later overrides earlier in all cases.
    It must also start with an include block (exclude would be useless
    at the start as it only excludes from the stuff before it)"""
    def __init__(self, *decls: AbstractInclusionRule):
        self.decls: list[AbstractInclusionRule] = list(decls)
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
        assert len(self.decls) > 0, "Expected some declarations"
        assert self.decls[0].get_clusivity() == Clusivity.INCLUDE, (
            "Include must come first (if exclude is first, "
            "it would only apply to stuff before it (i.e. nothing))")
        ie_blocks = [], []
        k: Clusivity
        for k, group in group_by(self.decls, key=lambda r: r.get_clusivity()):
            ie_blocks[k].append(list(group))
        return ie_blocks

    def _walk(self, includes: Sequence[AbstractInclude],
              excludes: Sequence[AbstractExclude]):
        """Lists all files and dirs, adding ``includes - excludes`` to self"""
        excludes = list(excludes)
        roots = set()
        for o in includes:
            for p in o.list_paths():
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
            if e.should_exclude(file):
                return True
        return False

    # noinspection PyMethodMayBeStatic
    def get_dir_exclude_mode(self, excludes: list[AbstractExclude], path: Path):
        result = ExcludeDirMode.NO
        for e in excludes:
            # Largest value (= largest amount excluded) wins
            result = max(result, e.exclude_mode_for(path))
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
