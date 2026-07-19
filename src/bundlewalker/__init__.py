# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bundlewalker")
except (PackageNotFoundError, OSError):
    __version__ = ""
