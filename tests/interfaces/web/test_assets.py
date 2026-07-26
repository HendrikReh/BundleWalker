# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from importlib.resources import files


def test_web_distribution_contains_vite_entrypoint_and_manifest() -> None:
    static = files("bundlewalker.interfaces.web").joinpath("static")
    assert static.joinpath("index.html").is_file()
    assert static.joinpath(".vite", "manifest.json").is_file()
    html = static.joinpath("index.html").read_text(encoding="utf-8")
    assert '<script type="module"' in html
    assert "http://" not in html
    assert "https://" not in html
    assert all(not asset.name.endswith(".map") for asset in static.joinpath("assets").iterdir())
