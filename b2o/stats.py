from __future__ import annotations

from pathlib import Path

from .py_util import get_size_on_disk


class Stats:
    def __init__(self):
        self.n_files = 0
        self.n_dirs = 0
        # These only include the files (du of dirs would give excluded as well)
        self.bytes_to_copy_ls = 0
        self.bytes_to_copy_du = 0
        self._size_cache: dict[Path, tuple[int, int]] = {}

    def lookup_sizes(self, file: Path):
        try:
            result = self._size_cache[file]
        except KeyError:
            # warnings.warn("File not found in cache - this will give "
            #               "wrong results if file is changed")
            result = self._size_cache[file] = self._calc_size(file)
        return result

    def _add_to_totals(self, sizes: tuple[int, int]):
        self.bytes_to_copy_ls += sizes[0]
        self.bytes_to_copy_du += sizes[1]

    def _sub_from_totals(self, sizes: tuple[int, int]):
        self.bytes_to_copy_ls -= sizes[0]
        self.bytes_to_copy_du -= sizes[1]

    @classmethod
    def _calc_size(cls, file: Path):
        st = file.stat()
        return st.st_size, get_size_on_disk(file, st)

    def add_file(self, file: Path):
        self.n_files += 1
        self._add_to_totals(self.lookup_sizes(file))

    def remove_file(self, file: Path):
        self.n_files -= 1
        self._sub_from_totals(self.lookup_sizes(file))

    def add_dir(self, _path: Path):
        self.n_dirs += 1
