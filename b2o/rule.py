from __future__ import annotations

import abc
from abc import ABC
from collections.abc import Iterable
from pathlib import Path

from .common import Clusivity, ExcludeMode, FsType
from .condition import ConditionalPath


class AbstractInclusionRule(ABC):
    """Include or an exclude. Note that each instance must be either
    include or exclude, not both (though a class could allow both
    types of instances)"""

    @abc.abstractmethod
    def get_clusivity(self) -> Clusivity:
        """Returns the clusivity (inclusive or exclusive) for this instance"""

    def try_as_include(self) -> AbstractInclude | None:
        if self.get_clusivity() == Clusivity.INCLUDE:
            assert isinstance(self, AbstractInclude)
            return self

    def assert_include(self) -> AbstractInclude:
        if (this := self.try_as_include()) is not None:
            return this
        raise TypeError("assert_include requires an AbstractInclude")


class AbstractInclude(AbstractInclusionRule, ABC):
    @abc.abstractmethod
    def _list_paths(self) -> Iterable[Path | ConditionalPath]:
        """Lists the paths matching this rule"""

    def list_paths(self) -> Iterable[ConditionalPath]:
        """Return paths matching this rule with their conditions"""
        return (p if isinstance(p, ConditionalPath)
                else ConditionalPath.unconditional(p)
                for p in self._list_paths())

    def get_clusivity(self) -> Clusivity:
        return Clusivity.INCLUDE


class AbstractExclude(AbstractInclusionRule, ABC):
    @staticmethod
    def any(excludes: Iterable[AbstractExclude], path: Path, fs_type: FsType) -> ExcludeMode:
        return ExcludeMode.max((e.exclude_mode_for(path) for e in excludes), fs_type)

    @abc.abstractmethod
    def should_exclude(self, path: Path) -> ExcludeMode | bool:
        """Returns the ``ExcludeMode`` (or a ``bool``) for ``path``. If it
        returns a ``bool``, ``True`` keeps self based on ``fallback_keep_self``"""

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def fallback_keep_self(self, path: Path):
        """Called only if should_exclude returns ``True`` to
        determine whether to exclude the dir itself too"""
        return True

    def exclude_mode_for(self, path: Path) -> ExcludeMode:
        if isinstance(mode := self.should_exclude(path), ExcludeMode):
            return mode
        if not mode:
            return ExcludeMode.NO
        return ExcludeMode.CONTENTS if self.fallback_keep_self(path) else ExcludeMode.ALL

    def get_clusivity(self) -> Clusivity:
        return Clusivity.EXCLUDE


class AbstractIncludeExclude(AbstractInclude, AbstractExclude, ABC):
    def __init__(self, clusivity: Clusivity):
        self.clusivity = clusivity

    def get_clusivity(self) -> Clusivity:
        return self.clusivity
