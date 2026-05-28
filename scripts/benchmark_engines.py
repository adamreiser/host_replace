#!/usr/bin/env python3
"""Benchmark host-replace engines for compile and replace performance."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import random
import statistics
import string
import time

import host_replace


@dataclass(frozen=True)
class Scenario:
    name: str
    host_count: int
    text_size_bytes: int
    injected_matches: int
    iterations: int


@dataclass(frozen=True)
class EngineStats:
    compile_ms: float
    replace_mean_ms: float
    replace_p95_ms: float
    throughput_mib_s: float
    bytes_replace_mean_ms: float
    bytes_throughput_mib_s: float
    e2e_single_run_ms: float
    e2e_avg_ms_run5: float


def build_host_map(host_count: int) -> dict[str, str]:
    """Generate deterministic host map with realistic host shapes."""
    host_map: dict[str, str] = {}
    for idx in range(host_count):
        original = f"web-{idx}.svc{idx % 17}.example.com"
        replacement = f"www-{idx}.edge-{idx % 29}.example.net"
        host_map[original] = replacement
    return host_map


def _random_noise_block(rng: random.Random, length: int) -> str:
    alphabet = string.ascii_letters + string.digits + " /:?&=_-.;,\n"
    return "".join(rng.choice(alphabet) for _ in range(length))


def build_corpus(
    host_map: dict[str, str], target_size_bytes: int, injected_matches: int, seed: int
) -> str:
    """Create mixed corpus with both random text and encoded hostname occurrences."""
    rng = random.Random(seed)
    encoders = list(host_replace.host_replace.encoding_functions.values())
    originals = list(host_map.keys())

    chunks: list[str] = []
    total_chars = 0
    for _ in range(injected_matches):
        encoder = rng.choice(encoders)
        original = rng.choice(originals)
        prefix = rng.choice(
            (
                "",
                "https://",
                "href=\"",
                "next=",
                " domain=",
                " path=/",
                "\n",
            )
        )
        suffix = rng.choice(("", "", "", "/path", "?q=1", "\"", " "))
        chunk_a = encoder(prefix + original + suffix)
        chunk_b = _random_noise_block(rng, rng.randint(20, 80))
        chunks.append(chunk_a)
        chunks.append(chunk_b)
        total_chars += len(chunk_a) + len(chunk_b)
        if total_chars >= target_size_bytes:
            break

    if total_chars < target_size_bytes:
        padding = _random_noise_block(rng, target_size_bytes - total_chars)
        chunks.append(padding)

    text = "".join(chunks)
    return text[:target_size_bytes]


def benchmark_end_to_end(
    *,
    engine: str,
    host_map: dict[str, str],
    corpus: str,
    runs: int,
) -> float:
    """Measure average ms/run including engine construction cost."""
    start = time.perf_counter()
    replacer = host_replace.HostnameReplacer(host_map, engine=engine)  # type: ignore[arg-type]
    for _ in range(runs):
        replacer.apply_replacements(corpus)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return elapsed_ms / runs


def benchmark_engine(
    *,
    engine: str,
    host_map: dict[str, str],
    corpus: str,
    iterations: int,
) -> EngineStats:
    """Benchmark compile + repeated replacement for one engine."""
    t0 = time.perf_counter()
    replacer = host_replace.HostnameReplacer(host_map, engine=engine)  # type: ignore[arg-type]
    compile_ms = (time.perf_counter() - t0) * 1000.0

    # Warmup to reduce first-run variance.
    replacer.apply_replacements(corpus)

    durations_ms: list[float] = []
    corpus_bytes = len(corpus.encode("utf-8"))
    for _ in range(iterations):
        start = time.perf_counter()
        replacer.apply_replacements(corpus)
        durations_ms.append((time.perf_counter() - start) * 1000.0)

    mean_ms = statistics.mean(durations_ms)
    p95_ms = statistics.quantiles(durations_ms, n=20)[18] if len(durations_ms) > 1 else mean_ms
    throughput_mib_s = (corpus_bytes / (1024 * 1024)) / (mean_ms / 1000.0)

    corpus_binary = corpus.encode("utf-8")
    bytes_durations_ms: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        replacer.apply_replacements(corpus_binary)
        bytes_durations_ms.append((time.perf_counter() - start) * 1000.0)

    bytes_mean_ms = statistics.mean(bytes_durations_ms)
    bytes_throughput_mib_s = (len(corpus_binary) / (1024 * 1024)) / (bytes_mean_ms / 1000.0)

    return EngineStats(
        compile_ms=compile_ms,
        replace_mean_ms=mean_ms,
        replace_p95_ms=p95_ms,
        throughput_mib_s=throughput_mib_s,
        bytes_replace_mean_ms=bytes_mean_ms,
        bytes_throughput_mib_s=bytes_throughput_mib_s,
        e2e_single_run_ms=benchmark_end_to_end(
            engine=engine, host_map=host_map, corpus=corpus, runs=1
        ),
        e2e_avg_ms_run5=benchmark_end_to_end(
            engine=engine, host_map=host_map, corpus=corpus, runs=5
        ),
    )


def print_results(name: str, corpus_size: int, results: dict[str, EngineStats]) -> None:
    print(f"\nScenario: {name} ({corpus_size / 1024:.1f} KiB)")
    print(
        f"{'Engine':<11} {'Compile ms':>11} {'Replace mean ms':>16} "
        f"{'Replace p95 ms':>15} {'Throughput MiB/s':>17} "
        f"{'E2E 1-run ms':>13} {'E2E avg@5 ms':>13}"
    )
    print("-" * 106)
    for engine in ("regex", "automaton"):
        stats = results[engine]
        print(
            f"{engine:<11} "
            f"{stats.compile_ms:>11.2f} "
            f"{stats.replace_mean_ms:>16.2f} "
            f"{stats.replace_p95_ms:>15.2f} "
            f"{stats.throughput_mib_s:>17.2f} "
            f"{stats.e2e_single_run_ms:>13.2f} "
            f"{stats.e2e_avg_ms_run5:>13.2f}"
        )

    print("\nBytes steady-state:")
    print(f"{'Engine':<11} {'Replace mean ms':>16} {'Throughput MiB/s':>17}")
    print("-" * 48)
    for engine in ("regex", "automaton"):
        stats = results[engine]
        print(
            f"{engine:<11} "
            f"{stats.bytes_replace_mean_ms:>16.2f} "
            f"{stats.bytes_throughput_mib_s:>17.2f}"
        )

    one_shot_winner = min(results.items(), key=lambda item: item[1].e2e_single_run_ms)[0]
    reuse_winner = min(results.items(), key=lambda item: item[1].e2e_avg_ms_run5)[0]
    print(
        f"\nRecommendation: one-shot={one_shot_winner}, repeated(5x)={reuse_winner}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run fewer/smaller scenarios for a fast smoke benchmark.",
    )
    args = parser.parse_args()

    if args.quick:
        scenarios = [
            Scenario("quick-small", host_count=100, text_size_bytes=96 * 1024, injected_matches=300, iterations=4),
            Scenario("quick-medium", host_count=800, text_size_bytes=384 * 1024, injected_matches=1600, iterations=3),
        ]
    else:
        scenarios = [
            Scenario("small", host_count=200, text_size_bytes=128 * 1024, injected_matches=500, iterations=6),
            Scenario("medium", host_count=1500, text_size_bytes=768 * 1024, injected_matches=3500, iterations=5),
            Scenario("large", host_count=4000, text_size_bytes=2 * 1024 * 1024, injected_matches=9000, iterations=4),
        ]

    print("Benchmarking host-replace engines (lower time and higher throughput are better).")
    for idx, scenario in enumerate(scenarios, start=1):
        host_map = build_host_map(scenario.host_count)
        corpus = build_corpus(
            host_map=host_map,
            target_size_bytes=scenario.text_size_bytes,
            injected_matches=scenario.injected_matches,
            seed=1337 + idx,
        )

        # Correctness guard: benchmark only if both engines agree.
        baseline = host_replace.HostnameReplacer(host_map, engine="regex")
        candidate = host_replace.HostnameReplacer(host_map, engine="automaton")
        baseline_output = baseline.apply_replacements(corpus)
        candidate_output = candidate.apply_replacements(corpus)
        if baseline_output != candidate_output:
            raise RuntimeError(
                f"Parity failure for scenario '{scenario.name}': outputs differ between engines."
            )

        results = {
            "regex": benchmark_engine(
                engine="regex",
                host_map=host_map,
                corpus=corpus,
                iterations=scenario.iterations,
            ),
            "automaton": benchmark_engine(
                engine="automaton",
                host_map=host_map,
                corpus=corpus,
                iterations=scenario.iterations,
            ),
        }
        print_results(scenario.name, scenario.text_size_bytes, results)


if __name__ == "__main__":
    main()
