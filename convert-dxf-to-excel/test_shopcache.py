#!/usr/bin/env python3
"""load_shop_cached 의 캐시 동작 검증 (스탠드얼론).

실제 138MB dxf 대신 임시 파일 + extract_shop_by_floor 교체로 파싱 횟수를 센다.
캐시는 파싱을 반복하지 않는 것이 요점이므로 "몇 번 파싱했나"가 핵심 관찰값이다.
"""
import os
import tempfile

import poc_deckorder as M


def _fake_dxf(dirpath, content=b"x"):
    p = os.path.join(dirpath, "shop.dxf")
    with open(p, "wb") as f:
        f.write(content)
    return p


def _counting_parser(calls, ret):
    def fake(path):
        calls.append(path)
        return ret
    return fake


def test_cache_miss_parses_and_creates_cache():
    """캐시가 없으면 한 번 파싱하고 캐시 파일을 만든다."""
    with tempfile.TemporaryDirectory() as d:
        dxf = _fake_dxf(d)
        calls = []
        orig = M.extract_shop_by_floor
        M.extract_shop_by_floor = _counting_parser(calls, {"B1F": "DATA"})
        try:
            r = M.load_shop_cached(dxf)
        finally:
            M.extract_shop_by_floor = orig
        assert r == {"B1F": "DATA"}, r
        assert len(calls) == 1, f"파싱 {len(calls)}회 (기대 1)"
        assert os.path.exists(dxf + ".cache.pkl"), "캐시 파일 미생성"


def test_cache_hit_skips_parse():
    """같은 dxf 를 두 번 로드하면 두 번째는 파싱하지 않는다."""
    with tempfile.TemporaryDirectory() as d:
        dxf = _fake_dxf(d)
        calls = []
        orig = M.extract_shop_by_floor
        M.extract_shop_by_floor = _counting_parser(calls, {"B1F": "DATA"})
        try:
            M.load_shop_cached(dxf)         # miss → parse
            r = M.load_shop_cached(dxf)     # hit  → no parse
        finally:
            M.extract_shop_by_floor = orig
        assert len(calls) == 1, f"파싱 {len(calls)}회 (기대 1)"
        assert r == {"B1F": "DATA"}, r


def test_changed_dxf_reparses():
    """dxf 크기가 바뀌면(stale) 다시 파싱한다."""
    with tempfile.TemporaryDirectory() as d:
        dxf = _fake_dxf(d, b"x")
        calls = []
        orig = M.extract_shop_by_floor
        M.extract_shop_by_floor = lambda p: (calls.append(p) or {"n": len(calls)})
        try:
            M.load_shop_cached(dxf)                       # parse #1
            with open(dxf, "wb") as f:
                f.write(b"xxxx")                          # 크기 변경 → stale
            r = M.load_shop_cached(dxf)                   # parse #2
        finally:
            M.extract_shop_by_floor = orig
        assert len(calls) == 2, f"파싱 {len(calls)}회 (기대 2)"
        assert r == {"n": 2}, r


def test_corrupt_cache_falls_back():
    """손상된 캐시 파일이면 파싱으로 복구한다."""
    with tempfile.TemporaryDirectory() as d:
        dxf = _fake_dxf(d)
        with open(dxf + ".cache.pkl", "wb") as f:
            f.write(b"not a valid pickle")
        calls = []
        orig = M.extract_shop_by_floor
        M.extract_shop_by_floor = _counting_parser(calls, {"ok": True})
        try:
            r = M.load_shop_cached(dxf)
        finally:
            M.extract_shop_by_floor = orig
        assert len(calls) == 1, f"파싱 {len(calls)}회 (기대 1)"
        assert r == {"ok": True}, r


def test_cache_write_failure_still_returns_data():
    """캐시 저장이 실패해도(권한·디스크 등) 파싱 결과는 그대로 돌려준다."""
    with tempfile.TemporaryDirectory() as d:
        dxf = _fake_dxf(d)
        calls = []
        orig_parse = M.extract_shop_by_floor
        orig_dump = M.pickle.dump
        M.extract_shop_by_floor = _counting_parser(calls, {"ok": 1})

        def boom(*a, **k):
            raise PermissionError("쓰기 불가")

        M.pickle.dump = boom
        try:
            r = M.load_shop_cached(dxf)
        finally:
            M.extract_shop_by_floor = orig_parse
            M.pickle.dump = orig_dump
        assert r == {"ok": 1}, r            # 쓰기 실패해도 데이터 반환 (크래시 X)
        assert len(calls) == 1, f"파싱 {len(calls)}회 (기대 1)"
        assert not os.path.exists(dxf + ".cache.pkl"), "실패했는데 캐시가 남음"


if __name__ == "__main__":
    tests = [
        test_cache_miss_parses_and_creates_cache,
        test_cache_hit_skips_parse,
        test_changed_dxf_reparses,
        test_corrupt_cache_falls_back,
        test_cache_write_failure_still_returns_data,
    ]
    for t in tests:
        t()
    print(f"OK: {len(tests)}개 테스트 통과")
