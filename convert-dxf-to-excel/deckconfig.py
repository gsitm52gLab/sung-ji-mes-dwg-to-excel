#!/usr/bin/env python3
"""입력/출력 경로 설정 로더.

config.yaml(기본: 이 모듈과 같은 디렉토리)을 읽어 경로를 절대경로로 노출한다.
경로는 설정 파일 위치 기준으로 해석하므로 실행 cwd에 흔들리지 않는다.
환경변수 DECK_CONFIG로 다른 설정 파일을 지정할 수 있다.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_MODULE_DIR = Path(__file__).resolve().parent


class _Config:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with open(self.path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        base = self.path.parent

        def resolve(section, key):
            try:
                value = data[section][key]
            except (KeyError, TypeError):
                raise KeyError(f"{self.path}에 필수 키가 없습니다: {section}.{key}")
            return str((base / value).resolve() if not os.path.isabs(value)
                       else Path(value))

        self.shop_dxf = resolve("input", "shop_dxf")
        self.detail_dxf = resolve("input", "detail_dxf")
        self.excel_glob = resolve("input", "excel_glob")
        self.areas_dir = resolve("output", "areas_dir")
        self.by_zone_dir = resolve("output", "by_zone_dir")


def find_config_path():
    """DECK_CONFIG > 모듈 디렉토리의 config.yaml 순으로 설정 파일을 찾는다."""
    env = os.environ.get("DECK_CONFIG")
    if env:
        p = Path(env)
        if not p.exists():
            raise FileNotFoundError(f"DECK_CONFIG가 가리키는 설정 파일이 없습니다: {p}")
        return p
    p = _MODULE_DIR / "config.yaml"
    if not p.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {p}")
    return p


def load(path):
    return _Config(path)


cfg = load(find_config_path())
