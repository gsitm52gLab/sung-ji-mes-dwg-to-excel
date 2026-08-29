#!/usr/bin/env python3
"""deckconfig 로더 테스트. pytest 불필요: `python3 test_deckconfig.py`."""

import os
import tempfile
from pathlib import Path


def test_resolves_paths_relative_to_config_file():
    """경로는 cwd가 아니라 config.yaml 위치 기준으로 절대경로가 된다."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text(
            "input:\n"
            "  shop_dxf: sub/shop.dxf\n"
            "  detail_dxf: sub/detail.dxf\n"
            "  excel_glob: xl/*.xlsm\n"
            "output:\n"
            "  areas_dir: out/areas\n"
            "  by_zone_dir: out/zone\n",
            encoding="utf-8",
        )
        import deckconfig
        cfg = deckconfig.load(cfg_path)
        base = os.path.realpath(d)
        assert cfg.shop_dxf == os.path.realpath(str(Path(base) / "sub/shop.dxf")), cfg.shop_dxf
        assert cfg.detail_dxf == os.path.realpath(str(Path(base) / "sub/detail.dxf")), cfg.detail_dxf
        assert cfg.excel_glob == os.path.realpath(str(Path(base) / "xl/*.xlsm")), cfg.excel_glob
        assert cfg.areas_dir == os.path.realpath(str(Path(base) / "out/areas")), cfg.areas_dir
        assert cfg.by_zone_dir == os.path.realpath(str(Path(base) / "out/zone")), cfg.by_zone_dir


def test_env_override():
    """DECK_CONFIG가 기본 config.yaml 대신 로드된다."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "custom.yaml"
        cfg_path.write_text(
            "input:\n  shop_dxf: a.dxf\n  detail_dxf: b.dxf\n  excel_glob: c/*.xlsm\n"
            "output:\n  areas_dir: x\n  by_zone_dir: y\n",
            encoding="utf-8",
        )
        os.environ["DECK_CONFIG"] = str(cfg_path)
        try:
            import deckconfig
            cfg = deckconfig.load(deckconfig.find_config_path())
            assert cfg.shop_dxf == os.path.realpath(str(Path(d) / "a.dxf")), cfg.shop_dxf
        finally:
            del os.environ["DECK_CONFIG"]


def test_missing_key_raises():
    """필수 키 누락 시 KeyError."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text("input:\n  shop_dxf: a.dxf\n", encoding="utf-8")
        import deckconfig
        try:
            deckconfig.load(cfg_path)
        except KeyError:
            return
        raise AssertionError("KeyError가 발생해야 한다")


def main():
    test_resolves_paths_relative_to_config_file()
    test_env_override()
    test_missing_key_raises()
    print("OK: 3개 테스트 통과")


if __name__ == "__main__":
    main()
