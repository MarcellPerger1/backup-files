from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .common import FsType, DeepBool
from .py_util import is_subpath
from .rule import AbstractExclude  # XXX: circular import problems here?


# This technically doesn't need to be with DeepBool but I think efficiency might
# go down the drain if each child has to check if the parent dir was excluded
class AbstractCondition(ABC):
    @abstractmethod
    def _evaluate(self, p: Path) -> DeepBool | bool:
        ...

    def evaluate(self, p: Path) -> DeepBool:
        if isinstance(result := self._evaluate(p), DeepBool):
            return result
        return self.bool_to_deep(result)

    def and_(self, other: AbstractCondition):
        return AndCond(self, other)

    @classmethod
    def bool_to_deep(cls, b: bool) -> DeepBool:
        """Used to convert bool results from ``_evaluate`` to ``DeepBool``s"""
        return DeepBool.ALL if b else DeepBool.NONE


class OrCond(AbstractCondition):
    def __init__(self, *children: AbstractCondition):
        self.children = children

    def _evaluate(self, p: Path) -> DeepBool:
        # PERF: `methodcaller` might be faster due to C vectorcall stuff
        return DeepBool.any(c.evaluate(p) for c in self.children)


class AndCond(AbstractCondition):
    def __init__(self, *children: AbstractCondition):
        self.children = children

    def _evaluate(self, p: Path) -> DeepBool:
        return DeepBool.all(c.evaluate(p) for c in self.children)


class NotCond(AbstractCondition):
    def __init__(self, child: AbstractCondition):
        self.child = child

    def _evaluate(self, p: Path) -> DeepBool:
        return ~self.child.evaluate(p)


class IsExcluded(AbstractCondition):
    def __init__(self, *excludes: AbstractExclude):
        self.excludes = excludes

    def _evaluate(self, p: Path) -> DeepBool:
        # NOTE: Doesn't check whether it's excluded due to the parent paths
        # PERF: map + methodcaller might be more efficient
        # PERF: We should pass fs_type as possibly-optional or at least cache
        #       FsType.from_path
        return DeepBool.any((DeepBool.from_is_excluded(ex.exclude_mode_for(p))
                             for ex in self.excludes), FsType.from_path(p))


class ConditionalPath:
    def __init__(self, subpath_cond: AbstractCondition, *paths: Path):
        self.paths = paths
        self.cond = subpath_cond
        """^ A condition that subpaths must meet to be included"""

    def matches_subpath(self, subpath: Path) -> DeepBool:
        assert any(is_subpath(subpath, p) for p in self.paths)
        return self.cond.evaluate(subpath)
