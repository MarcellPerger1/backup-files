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
        self.dest.mkdir(exist_ok=True)
        self._dirs_remaining = set(self.lister.dirs)
        for f in self.lister.files:
            self.add_file(f)  # TODO Parallel?
        while self._dirs_remaining:
            self.add_dir(self._dirs_remaining.pop())

    def add_file(self, srcfile: Path):
        destfile = self.get_dest_path(srcfile)
        self.add_dir(srcfile.parent)  # Will always map to destfile.parent
        shutil.copy2(srcfile, destfile)

    def add_dir(self, srcdir: Path, remove_from_remaining: bool = True):
        destdir = self.get_dest_path(srcdir)
        self._copy_dir(destdir, srcdir, remove_from_remaining)

    def _copy_dir(self, destdir: Path, srcdir: Path = None,
                  remove_from_remaining: bool = True):
        if not self._dir_exists(destdir):
            self._copy_dir(destdir.parent, srcdir.parent, remove_from_remaining)
            destdir.mkdir()
            # If we don't need to copy it, just make the dir, don't copy stat
            # (the source might not be somewhere sane, the dir is just there
            # for infrastructure purposes, not because it needs to vbe copied)
            if srcdir and (srcdir in self._dirs_remaining or srcdir in self._dirs_added):
                shutil.copystat(srcdir, destdir)
        self._dirs_added.add(destdir)
        if remove_from_remaining:
            self._dirs_remaining.discard(destdir)

    def _dir_exists(self, d: Path):
        return d in self._dirs_added or d.exists()

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
        return cls.PATH_UNSAFE_RE.sub(cls.char_escape_repl, s)

    @classmethod
    def char_escape_repl(cls, m: re.Match[str]):
        num = ord(m.group(0))
        if 0 <= num <= 255:
            return f'+x{num:>02X}'
        return f'+U{num:>08X}'
