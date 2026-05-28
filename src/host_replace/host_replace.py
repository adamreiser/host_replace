"""Host Replace module"""
from typing import Callable, Dict, Iterable, Literal, Optional, Protocol, TypeAlias, TypedDict, Union, cast
from collections import deque
import logging
import ipaddress
import idna
import regex

__all__ = ["HostnameReplacer"]

logger = logging.getLogger(__name__)

ReplaceCallbackStr = Callable[[str, int], str]
ReplaceCallbackBytes = Callable[[bytes, int], bytes]
AutomatonToken: TypeAlias = Union[str, int]
AutomatonPattern: TypeAlias = Union[str, bytes]


class AutomatonNode(TypedDict):
    """Aho-Corasick trie node."""

    next: dict[AutomatonToken, int]
    fail: int
    outputs: list[AutomatonPattern]


AUTO_ENGINE_LARGE_HOST_COUNT = 800
AUTO_ENGINE_LARGE_INPUT_BYTES = 384 * 1024
AUTO_ENGINE_MEDIUM_HOST_COUNT = 600
AUTO_ENGINE_MEDIUM_INPUT_BYTES = 256 * 1024
AUTO_ENGINE_SMALL_HOST_COUNT = 300
AUTO_ENGINE_SMALL_INPUT_BYTES = 128 * 1024


class _UninitializedEngine:
    """Placeholder engine for lazy auto-selection."""

    def replace_str(self, text: str, replace_callback: ReplaceCallbackStr) -> str:
        """Raise until auto mode initializes a concrete backend."""
        _ = (text, replace_callback)
        raise RuntimeError("Replacement engine was not initialized")

    def replace_bytes(self, text: bytes, replace_callback: ReplaceCallbackBytes) -> bytes:
        """Raise until auto mode initializes a concrete backend."""
        _ = (text, replace_callback)
        raise RuntimeError("Replacement engine was not initialized")


class _NoOpReplacementEngine:
    """No-op engine used when no replacement keys are present."""

    def replace_str(self, text: str, replace_callback: ReplaceCallbackStr) -> str:
        """Return input text unchanged."""
        _ = replace_callback
        return text

    def replace_bytes(self, text: bytes, replace_callback: ReplaceCallbackBytes) -> bytes:
        """Return input bytes unchanged."""
        _ = replace_callback
        return text


class ReplacementEngine(Protocol):
    """Engine abstraction for hostname replacement backends."""

    def replace_str(self, text: str, replace_callback: ReplaceCallbackStr) -> str:
        """Replace matches in a string and return transformed string."""

    def replace_bytes(self, text: bytes, replace_callback: ReplaceCallbackBytes) -> bytes:
        """Replace matches in bytes and return transformed bytes."""


class RegexReplacementEngine:
    """Current regex-based replacement backend."""

    def __init__(self, replacement_keys: Iterable[str]):
        # Prefer longer alternatives first to reduce regex backtracking when
        # keys overlap (e.g. subdomain vs bare domain forms).
        ordered_searches = sorted(replacement_keys, key=lambda search: (-len(search), search))
        search_str = "(" + "|".join([regex.escape(search) for search in ordered_searches]) + ")"
        pattern_str = f"{LEFT_SIDE}{search_str}{RIGHT_SIDE}"

        self.pattern_str = pattern_str
        self.hostname_regex = regex.compile(pattern_str, flags=regex.I | regex.M | regex.X)
        self.hostname_regex_binary = regex.compile(
            pattern_str.encode("utf-8"), flags=regex.I | regex.M | regex.X
        )

    def replace_str(self, text: str, replace_callback: ReplaceCallbackStr) -> str:
        """Apply regex substitutions to a string input."""
        return self.hostname_regex.sub(
            lambda match: replace_callback(match.group(), match.start()), text
        )

    def replace_bytes(self, text: bytes, replace_callback: ReplaceCallbackBytes) -> bytes:
        """Apply regex substitutions to a bytes input."""
        return self.hostname_regex_binary.sub(
            lambda match: replace_callback(match.group(), match.start()), text
        )


class AutomatonReplacementEngine:  # pylint: disable=too-many-instance-attributes
    """Aho-Corasick based backend with explicit boundary validation."""

    def __init__(self, replacement_keys: Iterable[str]):
        self._keys = tuple(replacement_keys)
        self._keys_bytes = tuple(key.encode("utf-8") for key in self._keys)

        # Case-insensitive matching normalized via lower() for both keys and text.
        self._automaton_str = _AhoCorasickAutomaton([key.lower() for key in self._keys])
        self._automaton_bytes = _AhoCorasickAutomaton(
            [key_bytes.lower() for key_bytes in self._keys_bytes]
        )

        flags = regex.I | regex.M | regex.X
        self._left_boundary_str = regex.compile(rf"{LEFT_SIDE}\Z", flags=flags)
        self._right_boundary_str = regex.compile(rf"{RIGHT_SIDE}", flags=flags)
        self._left_boundary_bytes = regex.compile(
            rf"{LEFT_SIDE}\Z".encode("utf-8"), flags=flags
        )
        self._right_boundary_bytes = regex.compile(
            rf"{RIGHT_SIDE}".encode("utf-8"), flags=flags
        )

    def replace_str(self, text: str, replace_callback: ReplaceCallbackStr) -> str:
        """Apply automaton substitutions to a string input."""
        normalized = text.lower()
        candidates = self._collect_candidates(
            haystack=text,
            normalized_haystack=normalized,
            automaton=self._automaton_str,
            left_boundary=self._left_boundary_str,
            right_boundary=self._right_boundary_str,
        )
        return cast(str, _apply_candidates(text, candidates, replace_callback))

    def replace_bytes(self, text: bytes, replace_callback: ReplaceCallbackBytes) -> bytes:
        """Apply automaton substitutions to a bytes input."""
        normalized = text.lower()
        candidates = self._collect_candidates(
            haystack=text,
            normalized_haystack=normalized,
            automaton=self._automaton_bytes,
            left_boundary=self._left_boundary_bytes,
            right_boundary=self._right_boundary_bytes,
        )
        return cast(bytes, _apply_candidates(text, candidates, replace_callback))

    def _collect_candidates(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        haystack: Union[str, bytes],
        normalized_haystack: Union[str, bytes],
        automaton: "_AhoCorasickAutomaton",
        left_boundary: Union[regex.Pattern[str], regex.Pattern[bytes]],
        right_boundary: Union[regex.Pattern[str], regex.Pattern[bytes]],
    ) -> list[tuple[int, int]]:
        haystack_len = len(haystack)
        best_end_by_start = [-1] * haystack_len

        for start, end in automaton.iter_matches(normalized_haystack):
            if start < 0 or start >= haystack_len:
                continue
            if end <= best_end_by_start[start]:
                continue
            # Avoid slicing: evaluate boundaries with pos/endpos directly.
            if not left_boundary.search(haystack, 0, start):  # type: ignore[arg-type]
                continue
            if not right_boundary.match(haystack, end):  # type: ignore[arg-type]
                continue
            best_end_by_start[start] = end

        candidates: list[tuple[int, int]] = []
        current_end = 0
        for start, end in enumerate(best_end_by_start):
            if end == -1 or start < current_end:
                continue
            candidates.append((start, end))
            current_end = end

        return candidates


class _AhoCorasickAutomaton:  # pylint: disable=too-few-public-methods
    """Minimal Aho-Corasick implementation for str/bytes haystacks."""

    def __init__(self, patterns: list[AutomatonPattern]):
        if not patterns:
            raise ValueError("At least one pattern is required")

        self.nodes: list[AutomatonNode] = [{"next": {}, "fail": 0, "outputs": []}]

        for pattern in patterns:
            self._add_pattern(pattern)

        self._build_failures()

    def _add_pattern(self, pattern: AutomatonPattern) -> None:
        node_idx = 0
        for token in pattern:
            token_map = self.nodes[node_idx]["next"]
            if token not in token_map:
                token_map[token] = len(self.nodes)
                self.nodes.append({"next": {}, "fail": 0, "outputs": []})
            node_idx = token_map[token]

        outputs = self.nodes[node_idx]["outputs"]
        outputs.append(pattern)

    def _build_failures(self) -> None:
        queue: deque[int] = deque()
        root_next = self.nodes[0]["next"]

        for child in root_next.values():
            self.nodes[child]["fail"] = 0
            queue.append(child)

        while queue:
            current = queue.popleft()
            current_next = self.nodes[current]["next"]

            for token, nxt in current_next.items():
                queue.append(nxt)
                fail = self.nodes[current]["fail"]

                while fail and token not in self.nodes[fail]["next"]:
                    fail = self.nodes[fail]["fail"]

                fail_next = self.nodes[fail]["next"]
                if token in fail_next:
                    self.nodes[nxt]["fail"] = fail_next[token]
                else:
                    self.nodes[nxt]["fail"] = 0

                fail_outputs = self.nodes[self.nodes[nxt]["fail"]]["outputs"]
                outputs = self.nodes[nxt]["outputs"]
                outputs.extend(fail_outputs)

    def iter_matches(self, haystack: AutomatonPattern) -> Iterable[tuple[int, int]]:
        """Yield non-normalized start/end offsets for all matched patterns."""
        state = 0
        for idx, token_raw in enumerate(haystack):
            token = cast(AutomatonToken, token_raw)
            while state and token not in self.nodes[state]["next"]:
                state = self.nodes[state]["fail"]
            next_map = self.nodes[state]["next"]
            state = next_map.get(token, 0)

            outputs = self.nodes[state]["outputs"]
            for pattern in outputs:
                start = idx - len(pattern) + 1
                yield (start, idx + 1)


def _apply_candidates(
    text: Union[str, bytes],
    candidates: list[tuple[int, int]],
    replace_callback: Union[ReplaceCallbackStr, ReplaceCallbackBytes],
) -> Union[str, bytes]:
    if not candidates:
        return text

    chosen: list[tuple[int, int]] = []
    current_end = 0
    i = 0

    while i < len(candidates):
        start = candidates[i][0]
        if start < current_end:
            i += 1
            continue

        best = candidates[i]
        j = i + 1
        while j < len(candidates) and candidates[j][0] == start:
            if (candidates[j][1] - candidates[j][0]) > (best[1] - best[0]):
                best = candidates[j]
            j += 1

        chosen.append(best)
        current_end = best[1]
        i = j

    parts: list[Union[str, bytes]] = []
    cursor = 0
    for start, end in chosen:
        parts.append(text[cursor:start])
        matched = text[start:end]
        parts.append(replace_callback(matched, start))  # type: ignore[arg-type]
        cursor = end
    parts.append(text[cursor:])

    if isinstance(text, str):
        return "".join(parts)  # type: ignore[arg-type]
    return b"".join(parts)  # type: ignore[arg-type]


class HostnameReplacer:  # pylint: disable=too-many-instance-attributes
    """
    A class for performing host and domain replacements on a str or byte array.

    Parameters:
        host_map: The host mapping dictionary.

    Example:
        host_map = {
            "web.example.com": "www.example.net",
            "example.org": "example.net"
        }

        replacer = HostnameReplacer(host_map)
        output_text = replacer.apply_replacements(input_text)
    """

    def __init__(
        self,
        host_map: Dict[str,str],
        engine: Literal["regex", "automaton", "auto"] = "regex",
        expected_runs: int = 1,
    ):
        """
        Initializes the host mapping dictionaries.

        Args:
            host_map: The host mapping dictionary.
            engine: Replacement engine backend. Supported values are "regex"
                    , "automaton", and "auto".
            expected_runs: Hint for auto engine selection; expected number of
                    replacement calls with this replacer instance.

        Raises:
            ValueError: If any entry is neither a valid domain nor IP address.
        """
        if engine not in ("regex", "automaton", "auto"):
            raise ValueError(f"Unsupported engine: {engine}")
        if not isinstance(expected_runs, int) or expected_runs < 1:
            raise ValueError("expected_runs must be a positive integer")

        self.engine = engine
        self.expected_runs = expected_runs
        self.selected_engine: Optional[Literal["regex", "automaton"]] = None
        self.replacements_table: Dict[str,str] = {}
        self.replacement_engine: ReplacementEngine = _UninitializedEngine()
        # Backward-compatible handles kept for callers/tests that access these.
        self.hostname_regex: regex.Pattern[str]
        self.hostname_regex_binary: regex.Pattern[bytes]
        self._auto_engine_locked = False
        self.compute_replacements(host_map)

    def _validate_hostname(self, hostname: str) -> None:
        """Validates that the supplied hostname is a valid domain or IP
        address. This includes qualified and unqualified hostnames,
        internationalized domain names (IDNs), and IPv4/IPv6 addresses.

        Args:
            hostname: The name or IP address to validate.

        Raises:
            ValueError if the supplied hostname is invalid.

        Returns:
            None
        """

        if not isinstance(hostname, str):
            raise ValueError(f"{hostname} is not a str")

        # Check if the name is an IDN; this also covers IPv4 addresses
        try:
            idna.decode(hostname)
            return
        except idna.core.IDNAError:
            pass
        try:
            ipaddress.IPv6Address(hostname)
            return
        except ipaddress.AddressValueError:
            raise ValueError(f"{hostname} is not a valid hostname or IP address") from None

    def _validate_host_map(self, host_map: Dict[str,str]) -> None:
        """
        Validates the entries in the provided host map.

        Args:
            host_map: The host mapping dictionary to validate.

        Raises:
            ValueError: If any entry is neither a valid domain nor IP address.
        """
        if not isinstance(host_map, dict):
            raise ValueError("host_map must be a dictionary")

        # Validate each key and value. Do not use set/union here, since
        # unhashable values should still be reported as invalid host map input.
        for hostname in list(host_map.keys()) + list(host_map.values()):
            self._validate_hostname(hostname)

    def compute_replacements(self, host_map: Union[Dict[str,str], None] = None) -> None:
        """
        Populates the replacements table with encoded mappings and creates
        the regex patterns used by the apply_replacements method.

        Args:
            host_map: An optional host mapping dictionary to replace the existing mapping.

        Raises:
            ValueError: If any entry is neither a valid domain nor IP address.
        """

        # If a host map is provided (including an empty dict), replace the
        # current map and rebuild all derived replacement structures.
        if host_map is not None:
            self._validate_host_map(host_map)
            # Normalize to lowercase
            self.host_map = {k.lower(): v.lower() for k, v in host_map.items()}
            self.replacements_table = {}

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in encoding_functions.items():
                encoded_original = encoding_function(original)
                encoded_replacement = encoding_function(replacement)

                # Avoid introducing encoded characters in a replacement if the original doesn't have any
                if encoded_original != original or encoding_name == "encoding_plain":
                    # Do not overwrite an existing entry for the same search key.
                    # This preserves the first-seen encoding style and avoids
                    # introducing extra encoded characters (for example, encoding
                    # hyphens when the matched input had none to encode).
                    self.replacements_table.setdefault(encoded_original, encoded_replacement)

        if self.engine == "auto":
            self.selected_engine = None
            self._auto_engine_locked = False
            # Keep compatibility attributes populated before the first call.
            self.hostname_regex = regex.compile(r"(?!x)x")
            self.hostname_regex_binary = regex.compile(rb"(?!x)x")
            self.replacement_engine = _UninitializedEngine()
        else:
            self._initialize_engine(self.engine)

    def apply_replacements(self, text: Union[str,bytes]) -> Union[str,bytes]:
        """
        Applies the hostname replacements to the input text.

        Args:
            text: The input text (str or bytes) to process.

        Returns:
            The text after all replacements have been applied.
        """

        if self.engine == "auto":
            should_initialize = not self._auto_engine_locked
            # Once initialized, auto mode can only upgrade regex -> automaton
            # as workload characteristics grow. This avoids backend churn while
            # still adapting when the first input underestimates steady-state size.
            should_consider_upgrade = self.selected_engine == "regex"

            if should_initialize or should_consider_upgrade:
                input_size_bytes = len(text.encode("utf-8")) if isinstance(text, str) else len(text)

                if should_initialize:
                    engine_choice = self._choose_auto_engine(input_size_bytes)
                    self._initialize_engine(engine_choice)
                    self._log_auto_selection(input_size_bytes)
                    self._auto_engine_locked = True

                elif should_consider_upgrade:
                    engine_choice = self._choose_auto_engine(input_size_bytes)
                    if engine_choice == "automaton":
                        self._initialize_engine("automaton")
                        self._log_auto_upgrade(input_size_bytes)

        if isinstance(text, str):
            return self.replacement_engine.replace_str(text, self._replace_str)
        return self.replacement_engine.replace_bytes(text, self._replace_bytes)

    def _choose_auto_engine(self, input_size_bytes: int) -> Literal["regex", "automaton"]:
        """Choose an engine for this instance based on workload heuristics."""
        host_count = len(self.host_map)

        # Calibrated against scripts/benchmark_engines.py --quick:
        # - quick-small  (100 hosts, 96 KiB): regex wins one-shot and repeated
        # - quick-medium (800 hosts, 384 KiB): regex wins one-shot,
        #   automaton wins repeated workloads
        #
        # Policy: keep one-shot conservative (regex), move to automaton only
        # when both map size and input size indicate enough throughput benefit.
        if self.expected_runs == 1:
            return "regex"

        if (
            self.expected_runs >= 2
            and host_count >= AUTO_ENGINE_LARGE_HOST_COUNT
            and input_size_bytes >= AUTO_ENGINE_LARGE_INPUT_BYTES
        ):
            return "automaton"

        if (
            self.expected_runs >= 3
            and host_count >= AUTO_ENGINE_MEDIUM_HOST_COUNT
            and input_size_bytes >= AUTO_ENGINE_MEDIUM_INPUT_BYTES
        ):
            return "automaton"

        if (
            self.expected_runs >= 5
            and host_count >= AUTO_ENGINE_SMALL_HOST_COUNT
            and input_size_bytes >= AUTO_ENGINE_SMALL_INPUT_BYTES
        ):
            return "automaton"

        return "regex"

    def _initialize_engine(self, engine_choice: Literal["regex", "automaton"]) -> None:
        """Initialize the selected backend engine."""
        self.selected_engine = engine_choice
        if not self.replacements_table:
            self.replacement_engine = _NoOpReplacementEngine()
            # Keep compatibility attributes populated.
            self.hostname_regex = regex.compile(r"(?!x)x")
            self.hostname_regex_binary = regex.compile(rb"(?!x)x")
            return

        if engine_choice == "regex":
            regex_engine = RegexReplacementEngine(self.replacements_table.keys())
            self.replacement_engine = regex_engine
            self.hostname_regex = regex_engine.hostname_regex
            self.hostname_regex_binary = regex_engine.hostname_regex_binary
            return

        self.replacement_engine = AutomatonReplacementEngine(self.replacements_table.keys())
        # Keep compatibility attributes populated.
        self.hostname_regex = regex.compile(r"(?!x)x")
        self.hostname_regex_binary = regex.compile(rb"(?!x)x")

    def _log_auto_selection(self, input_size_bytes: int) -> None:
        """Emit a one-time info log describing auto-engine selection details."""
        logger.info(
            "Auto-selected engine=%s (host_count=%d, input_size_bytes=%d, expected_runs=%d)",
            self.selected_engine,
            len(self.host_map),
            input_size_bytes,
            self.expected_runs,
        )

    def _log_auto_upgrade(self, input_size_bytes: int) -> None:
        """Emit an info log when auto mode upgrades regex to automaton."""
        logger.info(
            (
                "Auto-upgraded engine=automaton "
                "(host_count=%d, input_size_bytes=%d, expected_runs=%d)"
            ),
            len(self.host_map),
            input_size_bytes,
            self.expected_runs,
        )

    def _replace_str(self, original_str: str, start_offset: int) -> str:
        """
        Returns the replacement string, preserving upper or title case if present in the original.

        Args:
            original_str: The matched text.
            start_offset: Match start offset in the input text.

        Returns:
            The replacement string.
        """

        # It shouldn't be possible to fail to find original_str in the replacements table, but if this happens,
        # fall back to original_str as if the host is mapped to itself
        replacement_str = self.replacements_table.get(original_str.lower(), original_str)
        if replacement_str == original_str:
            return replacement_str

        if original_str.isupper():
            replacement_str = replacement_str.upper()

        elif original_str.istitle():
            replacement_str = replacement_str.title()

        logger.info("Replacing %s with %s at offset %d", original_str, replacement_str, start_offset)

        return replacement_str

    def _replace_bytes(self, original_bytes: bytes, start_offset: int) -> bytes:
        """Returns the replacement bytes, preserving upper or title case if present in the original.

        Args:
            original_bytes: The matched bytes.
            start_offset: Match start offset in the input text.

        Returns:
            The replacement bytes.
        """

        # It shouldn't be possible to fail to find original_str in the replacements table, but if this happens,
        # fall back to original_str as if the host is mapped to itself
        original_str = original_bytes.decode("utf-8", errors="replace")
        replacement_str = self.replacements_table.get(original_str.lower(), original_str)

        if replacement_str == original_str:
            return replacement_str.encode("utf-8")

        if original_str.isupper():
            replacement_str = replacement_str.upper()

        elif original_str.istitle():
            replacement_str = replacement_str.title()

        logger.info("Replacing %s with %s at offset %d", original_str, replacement_str, start_offset)

        return replacement_str.encode("utf-8")

def encoding_plain(s: str) -> str:
    """Return string without modification."""
    return s

def encoding_html_hex(s: str) -> str:
    """Return string with all non-alphanumeric characters except hyphens HTML entity encoded using hex notation."""
    return "".join(f"&#x{ord(c):02x};" if not (c.isalnum() or c == "-") else c for c in s)

def encoding_html_numeric(s: str) -> str:
    """Return string with all non-alphanumeric characters except hyphens HTML entity encoded using decimal notation."""
    return "".join(f"&#{ord(c)};" if not (c.isalnum() or c == "-") else c for c in s)

def encoding_url(s: str) -> str:
    """Return string with all non-alphanumeric characters except hyphens URL encoded."""
    return "".join(
        _percent_encode_utf8(c) if not (c.isalnum() or c == "-") else c for c in s
    )

def encoding_html_hex_not_alphanum(s: str) -> str:
    """Return string with all non-alphanumeric characters including hyphens HTML entity encoded using hex notation."""
    return "".join(c if c.isalnum() else f"&#x{ord(c):02x};" for c in s)

def encoding_html_numeric_not_alphanum(s: str) -> str:
    """Return string with all non-alphanumeric characters including hyphens HTML entity encoded using decimal notation."""
    return "".join(f"&#{ord(c)};" if not c.isalnum() else c for c in s)

def encoding_url_not_alphanum(s: str) -> str:
    """Return string with all non-alphanumeric characters including hyphens URL encoded."""
    return "".join(_percent_encode_utf8(c) if not c.isalnum() else c for c in s)

def encoding_html_hex_all(s: str) -> str:
    """Return string with all characters HTML entity encoded using hex notation."""
    return "".join(f"&#x{ord(c):02x};" for c in s)

def encoding_html_numeric_all(s: str) -> str:
    """Return string with all characters HTML entity encoded using decimal notation."""
    return "".join(f"&#{ord(c)};" for c in s)

def encoding_url_all(s: str) -> str:
    """Return string with all characters URL encoded."""
    return "".join(_percent_encode_utf8(c) for c in s)


def _percent_encode_utf8(char: str) -> str:
    """Percent-encode a character using its UTF-8 byte sequence."""
    return "".join(f"%{byte:02x}" for byte in char.encode("utf-8"))

# Note that the order of encoding functions matters.
encoding_functions = {
    "encoding_html_hex": encoding_html_hex,
    "encoding_html_hex_all": encoding_html_hex_all,
    "encoding_html_hex_not_alphanum": encoding_html_hex_not_alphanum,
    "encoding_html_numeric": encoding_html_numeric,
    "encoding_html_numeric_all": encoding_html_numeric_all,
    "encoding_html_numeric_not_alphanum": encoding_html_numeric_not_alphanum,
    "encoding_plain": encoding_plain,
    "encoding_url": encoding_url,
    "encoding_url_all": encoding_url_all,
    "encoding_url_not_alphanum": encoding_url_not_alphanum
}

# Regular expression patterns
ALPHANUMERIC_HEX_CODES = "(?:4[1-9a-f]|5[0-9a]|6[1-9a-f]|7[0-9a]|3[0-9])"
ALPHANUMERIC_PLUS_DOT_HEX_CODES = f"(?:2e|{ALPHANUMERIC_HEX_CODES})"

ALPHANUMERIC_DECIMAL_CODES = "(?:4[89]|5[0-7]|6[5-9]|[78][0-9]|9[07-9]|1[01][0-9]|12[012])"
ALPHANUMERIC_PLUS_DOT_DECIMAL_CODES = "(?:4[689]|5[0-7]|6[5-9]|[78][0-9]|9[07-9]|1[01][0-9]|12[012])"

HTML_HEX_ENCODED_ALPHANUMERIC = rf"(?:&\#x{ALPHANUMERIC_HEX_CODES};)"
HTML_DECIMAL_ENCODED_ALPHANUMERIC = rf"(?:&\#{ALPHANUMERIC_DECIMAL_CODES};)"
URL_ENCODED_ALPHANUMERIC = rf"(?:%{ALPHANUMERIC_HEX_CODES})"

HTML_ENCODED_ALPHANUMERIC = f"""
(?:
    {HTML_HEX_ENCODED_ALPHANUMERIC}
|
    {HTML_DECIMAL_ENCODED_ALPHANUMERIC}
)
"""

ANY_ALPHANUMERIC = f"""
(?:
    [a-z0-9]
|
    {URL_ENCODED_ALPHANUMERIC}
|
    {HTML_ENCODED_ALPHANUMERIC}
)
"""

DOT = r"(?:\.|%2e|&\#x2e;|&\#46;)"
HYPHEN = r"(?:-|%2d|&\#x2d;|&\#45;)"

# The LEFT_SIDE and RIGHT_SIDE patterns ensure that we match whole hostnames and avoid partial matches.
LEFT_SIDE = rf"""
# Look for any of...
(?<=
    (?:
        ^                                                               # ...the beginning of the string or line
    |
        [^a-z0-9\.;]                                                    # ...any character that's not alphanumeric, a dot, or a semicolon
                                                                        #    note that this includes hyphens, so apply an exclusion condition below
    |
        %(?!{ALPHANUMERIC_PLUS_DOT_HEX_CODES})[0-9a-f]{{2}}             # ...a URL-encoded character that's not alphanumeric or dot
    |
        {DOT}{{2,}}                                                     # ...two or more dots, since, e.g., "a...example.com" is not a subdomain of example.com
    |
        (?:
            (?<!
                (?:&\#x{ALPHANUMERIC_PLUS_DOT_HEX_CODES})
            |
                (?:&\#{ALPHANUMERIC_PLUS_DOT_DECIMAL_CODES})
            )
        ;                                                               # ...a semicolon not preceded by HTML-encoded alphanumeric or dot
        )
    ){DOT}?                                                         # optional dot after any of the above
)
(?<!{ANY_ALPHANUMERIC}{HYPHEN}+)                                # exclusion condition
"""

RIGHT_SIDE = rf"""
(?!
        (?:{HYPHEN}|{DOT})?
        {ANY_ALPHANUMERIC}
)
"""
