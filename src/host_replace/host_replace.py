"""Host Replace module"""
from typing import Dict, Union
import logging
import ipaddress
import idna
import regex

__all__ = ["HostnameReplacer"]

class HostnameReplacer:
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

    def __init__(self, host_map: Dict[str,str]):
        """
        Initializes the HostnameReplacer with a host mapping dictionary.

        Args:
            host_map: The host mapping dictionary.

        Raises:
            idna.core.IDNAError: If any of the hostnames in the host map are invalid according to IDNA encoding.
        """
        self.validate_host_map(host_map)
        self.host_map = host_map

        self.replacements_table: Dict[str,str] = {}
        self.hostname_regex: regex.Pattern[str]
        self.hostname_regex_binary: regex.Pattern[bytes]

        self.compute_replacements()

    def validate_host_map(self, host_map: Dict[str,str]) -> None:
        """
        Validates the provided host map entries.

        Args:
            host_map: The host mapping dictionary to validate.

        Raises:
            ValueError: If any entry is neither a valid IDN nor IP address.
        """

        for hostname in set(host_map.keys()).union(host_map.values()):
            try:
                if not isinstance(hostname, str):
                    raise ValueError(f"{hostname} is not a str")
                idna.decode(hostname)
            except idna.core.IDNAError:
                try:
                    ipaddress.IPv6Address(hostname)
                except ipaddress.AddressValueError as e:
                    raise ValueError(f"{hostname} is not a valid domain name or IP address") from e

    def compute_replacements(self, host_map: Union[Dict[str,str], None] = None) -> None:
        """
        Populates the replacements table with encoded mappings and creates
        the regex patterns used by the apply_replacements method.

        Args:
            host_map: An optional host mapping dictionary to replace the existing mapping.

        Raises:
            idna.core.IDNAError: If any of the hostnames in the host map are invalid according to IDNA encoding.
        """

        if host_map:
            self.validate_host_map(host_map)
            self.host_map = host_map
            self.replacements_table = {}

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in encoding_functions.items():
                encoded_original = encoding_function(original)
                encoded_replacement = encoding_function(replacement)

                # Avoid introducing encoded characters in a replacement if the original doesn't have any
                if encoded_original != original or encoding_name == "encoding_plain":
                    self.replacements_table[encoded_original] = encoded_replacement

        search_str = "(" + "|".join([regex.escape(search) for search in self.replacements_table]) + ")"
        pattern_str = f"{LEFT_SIDE}{search_str}{RIGHT_SIDE}"

        self.hostname_regex = regex.compile(pattern_str, flags=regex.I | regex.M | regex.X)

        self.hostname_regex_binary = regex.compile(pattern_str.encode("utf-8"), flags=regex.I | regex.M | regex.X)

    def apply_replacements(self, text: Union[str,bytes]) -> Union[str,bytes]:
        """
        Applies the hostname replacements to the input text.

        Args:
            text: The input text (str or bytes) to process.

        Returns:
            The text after all replacements have been applied.
        """

        if isinstance(text, str):
            text = self.hostname_regex.sub(self._replace_str, text)
        else:
            text = self.hostname_regex_binary.sub(self._replace_bytes, text)

        return text

    def _replace_str(self, m: regex.Match[str]) -> str:
        """
        Returns the replacement string, preserving upper or title case if present in the original.

        Args:
            m: The regex match object.

        Returns:
            The replacement string.
        """

        original_str = m.group()
        replacement_str = self.replacements_table.get(original_str.lower(), original_str)

        if replacement_str == original_str:
            logging.warning("%s not found in replacements table (coding error) or the table maps it to itself", original_str)

        if original_str.isupper():
            replacement_str = replacement_str.upper()

        elif original_str.istitle():
            replacement_str = replacement_str.title()

        logging.info("Replacing %s with %s at offset %d", original_str, replacement_str, m.start())

        return replacement_str

    def _replace_bytes(self, m: regex.Match[bytes]) -> bytes:
        """Returns the replacement bytes, preserving upper or title case if present in the original.

        Args:
            m: The regex match object.

        Returns:
            The replacement bytes.
        """

        original_str = m.group().decode("utf-8", errors="replace")
        replacement_str = self.replacements_table.get(original_str.lower(), original_str)

        if replacement_str == original_str:
            logging.warning("%s not found in replacements table (coding error) or the table maps it to itself", original_str)

        if original_str.isupper():
            replacement_str = replacement_str.upper()

        elif original_str.istitle():
            replacement_str = replacement_str.title()

        logging.info("Replacing %s with %s at offset %d", original_str, replacement_str, m.start())

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
    return "".join(f"%{ord(c):02x}" if not (c.isalnum() or c == "-") else c for c in s)

def encoding_html_hex_not_alphanum(s: str) -> str:
    """Return string with all non-alphanumeric characters including hyphens HTML entity encoded using hex notation."""
    return "".join(f"&#x{ord(c):02x};" if not c.isalnum() else c for c in s)

def encoding_html_numeric_not_alphanum(s: str) -> str:
    """Return string with all non-alphanumeric characters including hyphens HTML entity encoded using decimal notation."""
    return "".join(f"&#{ord(c)};" if not c.isalnum() else c for c in s)

def encoding_url_not_alphanum(s: str) -> str:
    """Return string with all non-alphanumeric characters including hyphens URL encoded."""
    return "".join(f"%{ord(c):02x}" if not c.isalnum() else c for c in s)

def encoding_html_hex_all(s: str) -> str:
    """Return string with all characters HTML entity encoded using hex notation."""
    return "".join(f"&#x{ord(c):02x};" for c in s)

def encoding_html_numeric_all(s: str) -> str:
    """Return string with all characters HTML entity encoded using decimal notation."""
    return "".join(f"&#{ord(c)};" for c in s)

def encoding_url_all(s: str) -> str:
    """Return string with all characters URL encoded."""
    return "".join(f"%{ord(c):02x}" for c in s)

encoding_functions = {}

for name in dir():
    if name.startswith("encoding_"):
        function = globals().get(name, None)
        if callable(function):
            encoding_functions[name] = function

# Regular expression patterns
ALPHANUMERIC_HEX_CODES = "(?:4[1-9a-f]|5[0-9a]|6[1-9a-f]|7[0-9a]|3[0-9])"
ALPHANUMERIC_PLUS_DOT_HEX_CODES = f"(?:2e|{ALPHANUMERIC_HEX_CODES})"

ALPHANUMERIC_DECIMAL_CODES = "(?:4[89]|5[0-7]|6[5-9]|[78][0-9]|9[0,7-9]|1[01][0-9]|12[012])"
ALPHANUMERIC_PLUS_DOT_DECIMAL_CODES = "(?:4[689]|5[0-7]|6[5-9]|[78][0-9]|9[0,7-9]|1[01][0-9]|12[012])"

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
