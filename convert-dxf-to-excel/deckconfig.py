#!/usr/bin/env python3
"""입력/출력 경로 설정 로더 (전체 파이프라인 공용).

리포지토리 루트의 config.yaml을 읽어 경로를 절대경로로 노출한다.
경로는 설정 파일 위치 기준으로 해석하므로 실행 cwd에 흔들리지 않는다.
환경변수 DECK_CONFIG로 다른 설정 파일을 지정할 수 있다.

파이썬(emit_*.py)에서는 `from deckconfig import cfg`로 사용한다.
shell(convert-dwg-to-dxf.sh)에서는 `--export`로 KEY='값' 형태를 얻어
`eval "$(python3 deckconfig.py --export)"`로 소비한다.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import yaml

_MODULE_DIR = Path(__file__).resolve().parent


class _Config:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with open(self.path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        base = self.path.parent

        def resolve(*keys):
            node = data
            for k in keys:
                try:
                    node = node[k]
                except (KeyError, TypeError):
                    dotted = ".".join(keys)
                    raise KeyError(f"{self.path}에 필수 키가 없습니다: {dotted}")
            value = node
            return str((base / value).resolve() if not os.path.isabs(value)
                       else Path(value))

        # 1단계: dwg -> dxf
        self.dwg_dir = resolve("convert", "dwg_dir")
        self.dxf_dir = resolve("convert", "dxf_dir")
        # 2단계: dxf -> excel
        self.shop_dxf = resolve("emit", "input", "shop_dxf")
        self.detail_dxf = resolve("emit", "input", "detail_dxf")
        self.excel_glob = resolve("emit", "input", "excel_glob")
        self.areas_dir = resolve("emit", "output", "areas_dir")
        self.by_zone_dir = resolve("emit", "output", "by_zone_dir")

    def as_env(self):
        """shell에서 소비할 KEY -> 절대경로 매핑."""
        return {
            "DWG_DIR": self.dwg_dir,
            "DXF_DIR": self.dxf_dir,
            "SHOP_DXF": self.shop_dxf,
            "DETAIL_DXF": self.detail_dxf,
            "EXCEL_GLOB": self.excel_glob,
            "AREAS_DIR": self.areas_dir,
            "BY_ZONE_DIR": self.by_zone_dir,
        }


def _find_repo_root(start):
    """start에서 위로 올라가며 .git이 있는 디렉토리를 리포지토리 루트로 본다."""
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return None


def find_config_path():
    """DECK_CONFIG > 리포지토리 루트의 config.yaml 순으로 설정 파일을 찾는다."""
    env = os.environ.get("DECK_CONFIG")
    if env:
        p = Path(env)
        if not p.exists():
            raise FileNotFoundError(f"DECK_CONFIG가 가리키는 설정 파일이 없습니다: {p}")
        return p
    root = _find_repo_root(_MODULE_DIR)
    if root is None:
        raise FileNotFoundError(
            f"리포지토리 루트(.git)를 찾을 수 없습니다: {_MODULE_DIR} 기준")
    p = root / "config.yaml"
    if not p.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {p}")
    return p


def load(path):
    return _Config(path)


cfg = load(find_config_path())


def _main(argv):
    if len(argv) == 2 and argv[1] == "--export":
        for key, value in cfg.as_env().items():
            print(f"{key}={shlex.quote(value)}")
        return 0
    sys.stderr.write("usage: deckconfig.py --export\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
