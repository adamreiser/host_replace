#!/usr/bin/env python3
"""Parity harness for replacement engine backends."""

from typing import Dict, List

import pytest
import host_replace


def _build_host_map() -> Dict[str, str]:
    return {
        "web.example.com": "www.example.com",
        "en.us.example.com": "en.us.regions.example.com",
        "us.example.com": "us-east-1.example.net",
        "127.0.0.1": "home.example.com",
        "2001:db8::": "ipv6.example.com",
        "files": "cloud.example.com",
    }


def _build_text_corpus(host_map: Dict[str, str]) -> List[str]:
    corpus: List[str] = []
    encoders = host_replace.host_replace.encoding_functions

    prefixes = ("", "https://", "href=\"", "a..", "\n")
    suffixes = ("", "/path", "?next=1", "\"", "\r")

    for original in host_map:
        for encode in encoders.values():
            encoded_original = encode(original)
            for prefix in prefixes:
                for suffix in suffixes:
                    corpus.append(encode(prefix + original + suffix))
                    corpus.append(prefix + encoded_original + suffix)

    corpus.extend(
        [
            "No hosts in this sentence.",
            "webxexamplexcom should not be replaced",
            "undefined.web.example.com should stay unchanged",
            "https://web.example.com?next=https%3A%2F%2Fen.us.example.com",
            "files intsrv inthost1",
        ]
    )

    return corpus


def _assert_engine_parity(engine: str) -> None:
    host_map = _build_host_map()
    baseline = host_replace.HostnameReplacer(host_map)
    candidate = host_replace.HostnameReplacer(host_map, engine=engine)

    assert baseline.replacements_table == candidate.replacements_table

    for input_text in _build_text_corpus(host_map):
        assert candidate.apply_replacements(input_text) == baseline.apply_replacements(input_text)
        encoded = input_text.encode("utf-8")
        assert candidate.apply_replacements(encoded) == baseline.apply_replacements(encoded)


def test_regex_engine_parity() -> None:
    """Parity harness for regex engine."""
    _assert_engine_parity("regex")


def test_automaton_engine_parity() -> None:
    """Parity target for the future automaton backend."""
    _assert_engine_parity("automaton")


def test_auto_engine_parity() -> None:
    """Auto-selected engine must preserve output parity."""
    _assert_engine_parity("auto")


def test_auto_engine_selection_small_defaults_to_regex() -> None:
    """Small one-shot workloads should choose regex under auto."""
    host_map = {f"web-{i}.example.com": f"www-{i}.example.net" for i in range(700)}
    replacer = host_replace.HostnameReplacer(host_map, engine="auto", expected_runs=1)

    assert replacer.selected_engine is None
    output = replacer.apply_replacements("web-1.example.com")
    assert output == "www-1.example.net"
    assert replacer.selected_engine == "regex"


def test_auto_engine_selection_large_reuse_prefers_automaton() -> None:
    """Larger reusable workloads should choose automaton under auto."""
    host_map = {f"web-{i}.example.com": f"www-{i}.example.net" for i in range(700)}
    replacer = host_replace.HostnameReplacer(host_map, engine="auto", expected_runs=3)

    marker = " web-1.example.com "
    large_text = ("x" * (300 * 1024)) + marker + ("y" * 1024)
    output = replacer.apply_replacements(large_text)

    assert "www-1.example.net" in output
    assert replacer.selected_engine == "automaton"


def test_auto_engine_locks_after_first_call() -> None:
    """One-shot auto workloads should remain on regex."""
    host_map = {f"web-{i}.example.com": f"www-{i}.example.net" for i in range(700)}
    replacer = host_replace.HostnameReplacer(host_map, engine="auto", expected_runs=1)

    # First call is small, so regex should be selected.
    first = replacer.apply_replacements("web-1.example.com")
    assert first == "www-1.example.net"
    assert replacer.selected_engine == "regex"

    # expected_runs=1 always keeps auto conservative.
    large_text = ("x" * (1024 * 1024)) + " web-2.example.com " + ("y" * 1024)
    second = replacer.apply_replacements(large_text)
    assert "www-2.example.net" in second
    assert replacer.selected_engine == "regex"


def test_auto_engine_adapts_from_regex_to_automaton() -> None:
    """Auto mode should upgrade regex to automaton for later large workloads."""
    host_map = {f"web-{i}.example.com": f"www-{i}.example.net" for i in range(700)}
    replacer = host_replace.HostnameReplacer(host_map, engine="auto", expected_runs=3)

    # First call stays below auto thresholds so regex is selected.
    first = replacer.apply_replacements("web-1.example.com")
    assert first == "www-1.example.net"
    assert replacer.selected_engine == "regex"

    # A later larger call should trigger one-way upgrade to automaton.
    large_text = ("x" * (1024 * 1024)) + " web-2.example.com " + ("y" * 1024)
    second = replacer.apply_replacements(large_text)
    assert "www-2.example.net" in second
    assert replacer.selected_engine == "automaton"


@pytest.mark.parametrize(
    "host_count,input_size,expected_runs,expected_engine",
    [
        # One-shot is always conservative.
        (800, 384 * 1024, 1, "regex"),
        # Large benchmark crossover (>=2 runs) should pick automaton.
        (800, 384 * 1024, 2, "automaton"),
        # Just below large thresholds should remain regex.
        (799, 384 * 1024, 2, "regex"),
        (800, 383 * 1024, 2, "regex"),
        # Medium tier needs >=3 runs.
        (600, 256 * 1024, 3, "automaton"),
        (600, 256 * 1024, 2, "regex"),
        # Small tier requires higher reuse (>=5 runs).
        (300, 128 * 1024, 5, "automaton"),
        (300, 128 * 1024, 4, "regex"),
    ],
)
def test_auto_engine_threshold_matrix(
    host_count: int,
    input_size: int,
    expected_runs: int,
    expected_engine: str,
) -> None:
    """Lock auto-engine threshold behavior around benchmark-informed boundaries."""
    host_map = {f"web-{i}.example.com": f"www-{i}.example.net" for i in range(host_count)}
    replacer = host_replace.HostnameReplacer(
        host_map, engine="auto", expected_runs=expected_runs
    )
    marker = " web-1.example.com "
    probe = marker
    if len(probe.encode("utf-8")) < input_size:
        probe = ("x" * (input_size - len(probe.encode("utf-8")))) + probe
    output = replacer.apply_replacements(probe)
    assert "www-1.example.net" in output
    assert replacer.selected_engine == expected_engine


@pytest.mark.parametrize("engine", ["regex", "automaton", "auto"])
def test_empty_host_map_is_noop_across_engines(engine: str) -> None:
    """Empty host maps should be accepted and produce no-op output."""
    replacer = host_replace.HostnameReplacer({}, engine=engine)

    text = "No replacements should happen here."
    assert replacer.apply_replacements(text) == text

    text_bytes = b"No replacements should happen here."
    assert replacer.apply_replacements(text_bytes) == text_bytes
