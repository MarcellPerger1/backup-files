from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

# XXX: This is meant to solve the circular import problem. Does it work? Must test this.
from . import conditions
from .common import DeepBool
from .fs_util import is_subpath


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
        return conditions.AndCond(self, other)

    def apply_to(self, path: Path):  # Just for nicer syntax
        return ConditionalPath(path, self)

    @classmethod
    def bool_to_deep(cls, b: bool) -> DeepBool:
        """Used to convert bool results from ``_evaluate`` to ``DeepBool``s"""
        return DeepBool.ALL if b else DeepBool.NONE


class ConditionalPath:
    def __init__(self, path: Path, subpath_cond: AbstractCondition | None = None):
        self.path = path
        # PERF: Cache default TrueCond instance, perhaps make TrueCond
        # into a singleton class - unconditional will be quite common
        self.cond = subpath_cond or conditions.TrueCond()
        """^ A condition that subpaths must meet to be included"""

    def matches_subpath(self, subpath: Path) -> DeepBool:
        assert is_subpath(subpath, self.path)
        return self.cond.evaluate(subpath)
