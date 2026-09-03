"""轻量 SimHash（64bit）+ 海明距离，用于同文换 URL 的内容去重。

- 特征：char 3-gram（中文友好，无需分词依赖），权重 = 频次
- 稳定哈希：md5 前 8 字节（内置 hash() 受 PYTHONHASHSEED 影响，不能用）
- 判重：海明距离 <= 3 视为相似
"""

import hashlib
import re
from collections import Counter

SIMILAR_THRESHOLD = 3


def _features(text: str, n: int = 3) -> Counter:
    text = re.sub(r"\s+", "", text)
    return Counter(text[i : i + n] for i in range(max(len(text) - n + 1, 0)))


def _stable_hash(feature: str) -> int:
    return int.from_bytes(hashlib.md5(feature.encode("utf-8")).digest()[:8], "big")


def simhash(text: str) -> int:
    weights = [0] * 64
    for feature, count in _features(text).items():
        h = _stable_hash(feature)
        for i in range(64):
            weights[i] += count if (h >> i) & 1 else -count
    bits = 0
    for i in range(64):
        if weights[i] > 0:
            bits |= 1 << i
    return bits


def to_hex(value: int) -> str:
    return format(value, "016x")


def from_hex(hex_str: str) -> int:
    return int(hex_str, 16)


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_similar(a: int, b: int, threshold: int = SIMILAR_THRESHOLD) -> bool:
    return hamming_distance(a, b) <= threshold
