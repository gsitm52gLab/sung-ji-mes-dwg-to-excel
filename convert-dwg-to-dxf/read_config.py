#!/usr/bin/env python3
"""config.yaml 에서 점(.)으로 구분된 키 경로의 값을 출력한다.

PyYAML 없이 표준 라이브러리만으로 동작하도록, config.yaml 에서 실제로 쓰는
2단계 들여쓰기 + `key: "value"` 형태만 지원하는 최소 파서다.

사용: python3 read_config.py <config.yaml> <docker.image>
"""
import sys


def load(path):
    """들여쓰기 기반으로 중첩 dict 를 만든다 (2칸 들여쓰기 기준)."""
    root = {}
    stack = [(-1, root)]  # (indent, dict)
    with open(path, encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            # 주석/빈 줄 건너뛰기
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = _clean(value)
            # 현재 들여쓰기보다 깊거나 같은 스택 정리
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1]
            if value == "":
                child = {}
                parent[key] = child
                stack.append((indent, child))
            else:
                parent[key] = value
    return root


def _clean(value):
    """인라인 주석 제거 후 따옴표 벗기기."""
    value = value.strip()
    if value.startswith(('"', "'")):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
    # 따옴표 없는 값은 첫 '#' 이후를 주석으로 취급
    return value.split("#", 1)[0].strip()


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: read_config.py <config.yaml> <dotted.key>")
    config = load(sys.argv[1])
    node = config
    for part in sys.argv[2].split("."):
        if not isinstance(node, dict) or part not in node:
            sys.exit(f"config key not found: {sys.argv[2]}")
        node = node[part]
    if isinstance(node, dict):
        sys.exit(f"config key is not a leaf value: {sys.argv[2]}")
    print(node)


if __name__ == "__main__":
    main()
