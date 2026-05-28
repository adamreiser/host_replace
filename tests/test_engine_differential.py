#!/usr/bin/env python3
"""Deterministic differential tests for regex vs automaton engines."""

from __future__ import annotations

import random
import string

import pytest
import host_replace


def _label(rng: random.Random, min_len: int = 1, max_len: int = 12) -> str:
    """Generate DNS-compatible label with no leading/trailing hyphen."""
    length = rng.randint(min_len, max_len)
    alphabet = string.ascii_lowercase + string.digits + "-"
    chars = [rng.choice(alphabet) for _ in range(length)]
    if chars[0] == "-":
        chars[0] = rng.choice(string.ascii_lowercase + string.digits)
    if chars[-1] == "-":
        chars[-1] = rng.choice(string.ascii_lowercase + string.digits)
    return "".join(chars)


def _hostname(rng: random.Random) -> str:
    """Generate a valid-ish hostname used for map construction."""
    labels = [_label(rng, 1, 10) for _ in range(rng.randint(2, 4))]
    return ".".join(labels)


def _build_host_map(seed: int, count: int) -> dict[str, str]:
    rng = random.Random(seed)
    host_map: dict[str, str] = {}
    while len(host_map) < count:
        src = _hostname(rng)
        dst = _hostname(rng)
        if src != dst:
            host_map[src] = dst
    return host_map


def _noise(rng: random.Random, length: int) -> str:
    alphabet = string.ascii_letters + string.digits + " /:?&=_-.;,\n\"'()[]{}"
    return "".join(rng.choice(alphabet) for _ in range(length))


def _build_corpus(seed: int, host_map: dict[str, str], approx_size: int) -> str:
    rng = random.Random(seed)
    encoders = list(host_replace.host_replace.encoding_functions.values())
    hosts = list(host_map.keys())
    prefixes = ("", "https://", "href=\"", "next=", "=", "a..", "\n", " ")
    suffixes = ("", "/p", "?q=1", "\"", " ", "\n", ":443")

    chunks: list[str] = []
    while len("".join(chunks)) < approx_size:
        if rng.random() < 0.65:
            host = rng.choice(hosts)
            enc = rng.choice(encoders)
            chunks.append(enc(rng.choice(prefixes) + host + rng.choice(suffixes)))
        else:
            chunks.append(_noise(rng, rng.randint(10, 80)))
    text = "".join(chunks)
    return text[:approx_size]


@pytest.mark.parametrize("seed", [7, 13, 41, 97, 1337])
def test_engine_differential_randomized(seed: int) -> None:
    """Randomized parity: both engines must produce identical outputs."""
    host_map = _build_host_map(seed=seed, count=45)
    corpus = _build_corpus(seed=seed + 1000, host_map=host_map, approx_size=120_000)

    regex_replacer = host_replace.HostnameReplacer(host_map, engine="regex")
    automaton_replacer = host_replace.HostnameReplacer(host_map, engine="automaton")

    # str path parity
    regex_out = regex_replacer.apply_replacements(corpus)
    automaton_out = automaton_replacer.apply_replacements(corpus)
    assert regex_out == automaton_out

    # bytes path parity
    corpus_bytes = corpus.encode("utf-8")
    regex_out_bytes = regex_replacer.apply_replacements(corpus_bytes)
    automaton_out_bytes = automaton_replacer.apply_replacements(corpus_bytes)
    assert regex_out_bytes == automaton_out_bytes


@pytest.mark.parametrize("seed", [3, 17, 29])
def test_engine_differential_with_invalid_utf8_delimiters(seed: int) -> None:
    """Parity under invalid UTF-8 byte delimiters around encoded hosts."""
    host_map = _build_host_map(seed=seed, count=20)
    encoders = list(host_replace.host_replace.encoding_functions.values())
    rng = random.Random(seed + 5000)

    regex_replacer = host_replace.HostnameReplacer(host_map, engine="regex")
    automaton_replacer = host_replace.HostnameReplacer(host_map, engine="automaton")

    bad_delims = [
        b"\xc1\x80",
        b"\x80",
        b"\xf5\x80\x80\x80",
        b"\xe0\x80\x80",
        b"\xc2",
    ]

    payloads: list[bytes] = []
    hosts = list(host_map.keys())
    for _ in range(150):
        host = rng.choice(hosts)
        enc = rng.choice(encoders)
        delimiter = rng.choice(bad_delims)
        payloads.append(delimiter + enc(host).encode("utf-8") + delimiter)
    corpus = b"::".join(payloads)

    regex_out = regex_replacer.apply_replacements(corpus)
    automaton_out = automaton_replacer.apply_replacements(corpus)
    assert regex_out == automaton_out
