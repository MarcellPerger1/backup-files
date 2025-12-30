from __future__ import annotations

import os
import os.path
from pathlib import Path
from typing import Sequence

from .condition import AbstractCondition, ConditionalPath, OrCond, NotExcluded
from .py_util import flatten, group_by, assert_not_exotic
from .stats import Stats
from .common import Clusivity, FsType, DeepBool
from .rule import AbstractInclusionRule, AbstractInclude, AbstractExclude

_IEBlocksTup = tuple[list[list[AbstractInclude]], list[list[AbstractExclude]]]


class ListFiles:
    """NOTE: decls has later overrides earlier in all cases.
    It must also start with an include block (exclude would be useless
    at the start as it only excludes from the stuff before it)"""
    def __init__(self, *decls: AbstractInclusionRule):
        self.decls: list[AbstractInclusionRule] = list(decls)
        self.stats = Stats()
        # PERF: Is the RAM tradeoff really worth it? A generator might
        # be better and then later code just checks the destination
        # to see if it exists or something.
        self.dirs: set[Path] = set()
        """^ WARNING: this won't add the contents/files in each of these,
        just the dirs themselves"""
        self.files: set[Path] = set()
        # REFACTOR: files and dirs should really be in a single object?
        self._added: set[Path] = set()

    def list_files(self):
        include_blocks, exclude_blocks = self._group_declarations()
        for i, includes in enumerate(include_blocks):  # For each include,
            excludes = flatten(exclude_blocks[i:])  # Use the excludes below it
            self._walk(includes, excludes)  # And add `includes - excludes_below_it`

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
        ie_blocks: _IEBlocksTup = [], []
        k: Clusivity
        for k, group in group_by(self.decls, key=lambda r: r.get_clusivity()):
            ie_blocks[k].append(list(group))
        return ie_blocks

    def _walk(self, includes: Sequence[AbstractInclude],
              excludes: Sequence[AbstractExclude]):
        """Lists all files and dirs, adding ``includes - excludes`` to self"""
        excludes = list(excludes)
        cond_roots: dict[Path, list[AbstractCondition]] = {}
        for o in includes:
            for cp in o.list_paths():
                assert_not_exotic(cp.path)
                cond_roots.setdefault(cp.path, []).append(cp.cond)
        return self._walk_paths([
            OrCond(*conds).and_(NotExcluded(*excludes)).apply_to(p)
            for p, conds in cond_roots.items()])

    def _walk_paths(self, paths: list[ConditionalPath]):
        for cp in paths:
            self._walk_conditional_path(cp, cp.path)

    def _walk_conditional_path(self, root: ConditionalPath, path: Path):
        if path in self._added:
            return
        if FsType.from_path(path) == FsType.FILE:
            return self._add_conditional_file(root, path)
        # PERF: scandir would be faster
        self._add_conditional_dir(root, path)

    def _add_conditional_dir(self, cp_root: ConditionalPath, d: Path):
        # TODO: how to handle EACCES errors? (permission denied)
        incl_mode = cp_root.matches_subpath(d)
        if incl_mode < DeepBool.SHALLOW:
            return
        self.add_dir_only(d)
        if incl_mode < DeepBool.ALL:
            return
        for ch in d.iterdir():
            self._walk_conditional_path(cp_root, ch)

    def _add_conditional_file(self, cp_root: ConditionalPath, f: Path):
        if cp_root.matches_subpath(f):
            self.add_file(f)

    def _walk_roots(self, roots: set[Path], excludes: list[AbstractExclude]):
        # TODO: handle files here
        visited_dirs: set[Path] = set()
        for root in roots:
            assert root.is_dir(), "Cannot have a non-dir root in _walk"
            for dir_str, dirs, files in os.walk(root.expanduser().resolve()):
                if (dirpath := Path(dir_str).resolve()) in visited_dirs:
                    dirs.clear()  # Already visited this tree, don't visit children
                    continue
                visited_dirs.add(dirpath)
                self._visit_dir(dirpath, dirs, files, excludes)

    def _visit_dir(self, dirpath: Path, dirnames: list[str], filenames: list[str],
                   excludes: list[AbstractExclude]):
        excl_mode = AbstractExclude.any(excludes, dirpath, FsType.DIR)
        if excl_mode.exclude_contents():
            dirnames.clear()  # Don't recurse into dirs
            filenames.clear()  # Don't add files
        if excl_mode.exclude_self():
            return  # Don't add self (skip the code below)
        self.add_dir_only(dirpath)
        for file in filenames:
            self._add_file_with_excludes(excludes, dirpath / file)
        # Don't do anything with the dirs here, will handle them
        #  when os.walk() recursively goes into them (topdown)

    def _add_file_with_excludes(self, excludes: list[AbstractExclude], file: Path):
        assert file.is_file(), "Expected a file, not dir/exotic"
        if not AbstractExclude.any(excludes, file, FsType.FILE):
            self.add_file(file)

    def add_file(self, file: Path):
        if file in self.files:
            return
        self.stats.add_file(file)
        self.files.add(file)
        self._added.add(file)

    def add_dir_only(self, path: Path):
        """WARNING: doesn't add children, only the dir itself"""
        if path not in self.dirs:
            return
        self.stats.add_dir(path)
        self.dirs.add(path)
        self._added.add(path)

    def remove_file(self, file: Path):
        # Note: don't use internally - should not have been added
        #  in the first place (excludes are applied during each 'include walk')
        if file not in self.files:
            return
        self.stats.remove_file(file)
        self.files.remove(file)

# TODO: for intra-file progress bar (Windows API):
#  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfile2,
#  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfileexa
#  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nc-winbase-lpprogress_routine
