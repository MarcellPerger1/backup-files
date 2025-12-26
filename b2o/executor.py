from __future__ import annotations

import re
import shutil
from pathlib import Path

from .list_files import ListFiles


class BackupExecutor:
    def __init__(self, file_lister: ListFiles, dest_root: Path):
        self.lister = file_lister
        self.dest = dest_root
        self.home = self.detect_home()
        self._dirs_remaining: set[Path] = set()
        self._dirs_added: set[Path] = set()

    def run(self):
        # TODO: an iterator would be more efficient perhaps,
        #  especially if destination is slower (so bottleneck is
        #  dest so must start using it as soon as possible)
        self.lister.list_files()
        # Strategy: Add all the files, then add the empty dirs that haven't
        # been added along with them (as they contained no files)
        self._dirs_remaining = set(self.lister.dirs)
        for f in self.lister.files:
            self.add_file(f)  # TODO Parallel?
        while self._dirs_remaining:
            self.add_dir(self._dirs_remaining.pop())

    def add_file(self, srcfile: Path):
        destfile = self.get_dest_path(srcfile)
        self._create_dir(destfile.parent)
        shutil.copy2(srcfile, destfile)

    def add_dir(self, srcdir: Path):
        destdir = self.get_dest_path(srcdir)
        self._create_dir(destdir)

    def _dir_exists(self, d: Path):
        return d in self._dirs_added or d.exists()

    def _create_dir(self, d: Path, remove_from_remaining: bool = True):
        if not self._dir_exists(d):
            self._create_dir(d.parent)
            d.mkdir()  # TODO: copystat on dirs?
        self._dirs_added.add(d)
        if remove_from_remaining:
            self._dirs_remaining.discard(d)

    def get_dest_path(self, path: Path):
        assert path.is_absolute()
        if (dest := self._try_dest_rel_home(path)) is not None:
            return dest
        anchor_path = path.parents[-1]
        return self.dest / self._get_drive_id(path) / path.relative_to(anchor_path)

    WINDOWS_DRIVE_RE = re.compile(r'(\w):[\\/]')

    def _get_drive_id(self, path: Path):
        if path.anchor in ('/', '', '\\'):
            return '__root__'
        if m := self.WINDOWS_DRIVE_RE.fullmatch(path.anchor):
            return m.group(1)   # e.g. C:/ -> C
        return self.escape_string(path.anchor)

    def _try_dest_rel_home(self, path: Path):
        if self.home is None:
            return None
        try:
            rel_home = path.relative_to(self.home)
        except RuntimeError:
            return None
        return self.dest / '__home__' / rel_home

    @classmethod
    def detect_home(cls):
        try:
            return Path('~').expanduser()
        except RuntimeError:
            return None

    PATH_UNSAFE_RE = re.compile(r'[^\w-.]')

    @classmethod
    def escape_string(cls, s: str):
        def replacer(m: re.Match[str]):
            num = ord(m.group(0))
            if 0 <= num <= 255:
                return f'+x{num:>02X}'
            return f'+U{num:>08X}'

        return cls.PATH_UNSAFE_RE.sub(replacer, s)
