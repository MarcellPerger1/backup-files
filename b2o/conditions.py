from __future__ import annotations

from pathlib import Path

from .common import DeepBool, FsType
from .condition import AbstractCondition
from .rule import AbstractExclude


class OrCond(AbstractCondition):
    def __init__(self, *children: AbstractCondition):
        # PERF: in __new__() check for one-arg case and return arg
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


class GroupCondition(AbstractCondition):
    """Mainly useful for utility condition classes that want to compose
    existing classes"""

    def __init__(self, inner: AbstractCondition):
        self.inner = inner

    def _evaluate(self, p: Path) -> DeepBool:
        return self.inner.evaluate(p)


class IsExcluded(AbstractCondition):
    def __init__(self, *excludes: AbstractExclude):
        self.excludes = excludes

    def _evaluate(self, p: Path) -> DeepBool:
        # NOTE: Doesn't check whether it's excluded due to the parent paths
        # PERF: map + methodcaller might be more efficient
        # PERF: We should pass fs_type as possibly-optional or at least cache
        #       FsType.from_path
        return DeepBool.any((ex.exclude_mode_for(p) for ex in self.excludes),
                            FsType.from_path(p))


class NotExcluded(GroupCondition):
    def __init__(self, *excludes: AbstractExclude):
        super().__init__(NotCond(IsExcluded(*excludes)))


class TrueCond(AbstractCondition):
    def _evaluate(self, p: Path) -> DeepBool | bool:
        return DeepBool.ALL
