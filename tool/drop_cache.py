#!/usr/bin/env python3
"""Drop page cache for a directory tree using posix_fadvise. No root needed."""

import os
import sys


def drop_dir_cache(path):
    count = 0
    total_bytes = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                fd = os.open(fp, os.O_RDONLY)
                sz = os.fstat(fd).st_size
                os.posix_fadvise(fd, 0, sz, os.POSIX_FADV_DONTNEED)
                os.close(fd)
                count += 1
                total_bytes += sz
            except Exception:
                pass
    return count, total_bytes


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: drop_cache.py <dir> [<dir> ...]")
        sys.exit(1)
    for path in sys.argv[1:]:
        count, total = drop_dir_cache(path)
        print(f"Evicted {count} files ({total / 1024 / 1024:.0f} MB) from {path}")
