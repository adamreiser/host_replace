#!/usr/bin/env python3
"""
Replace host and domain names in text using encoding-aware transformations.

This module provides a command-line interface and an API to replace hostnames in text and byte arrays, handling various text-compatible encodings
(URL, HTML entity). It accepts a JSON map file (CLI) or Python dict (API). See `mappings.json` for an example.

CLI:

usage: hostreplace [-h] [-o OUTPUT] -m MAPPING [-v] [input]

Replace hostnames in the input file based on a provided host mapping.

positional arguments:
  input                 input file to read from. If not provided, read from stdin

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        output file to write the replaced content. If not provided, write to stdout
  -m MAPPING, --mapping MAPPING
                        JSON file that contains the host mapping dictionary (e.g., {"web.example.com": "www.example.net"})
  -v, --verbose         display the replacements made

API:

replacer = HostnameReplacer(host_map)
output_text = replacer.apply_replacements(input_text)
"""

from typing import Dict, Union
import sys
import logging
import argparse
import json
import idna
import regex

__all__ = ["HostnameReplacer", "main", "encoding_functions", "HYPHEN", "DOT"]

class HostnameReplacer:
    """A class for performing host and domain replacements on a str or byte array.

    Args:
        host_map = {
            "web.example.com": "www.example.net",
            "example.org": "example.net"
        }

    Usage:
        replacer = HostnameReplacer(host_map)
        output_text = replacer.apply_replacements(input_text)
    """

    def __init__(self, host_map: Dict[str,str]):
        self.validate_host_map(host_map)
        self.host_map = host_map

        self.replacements_table: Dict[str,str] = {}
        self.hostname_regex: regex.Pattern[str]
        self.hostname_regex_binary: regex.Pattern[bytes]

        self.compute_replacements()

    def validate_host_map(self, host_map: Dict[str,str]):
        """Validate the provided host map entries."""
        for hostname in list(host_map.keys()) + list(host_map.values()):
            try:
                idna.decode(hostname)
            except idna.core.IDNAError as e:
                e.args = (f"{e.args[0]} ({hostname})",)
                raise e

    def compute_replacements(self, host_map: Union[Dict[str,str], None] = None):
        """Populates the replacements table with encoded mappings and creates
        the regex patterns used by the apply_replacements method."""

        if host_map:
            self.validate_host_map(host_map)
            self.host_map = host_map

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in encoding_functions.items():
                encoded_original = encoding_function(original)
                encoded_replacement = encoding_function(replacement)

                # Avoid introducing encoded characters in a replacement if the original doesn't have any
                if encoded_original != original or encoding_name == 'plain':
                    self.replacements_table[encoded_original] = encoded_replacement

        search_str = "(" + "|".join([regex.escape(search) for search in self.replacements_table]) + ")"
        pattern_str = f"{LEFT_SIDE}{search_str}{RIGHT_SIDE}"

        self.hostname_regex = regex.compile(pattern_str, flags=regex.I | regex.M | regex.X)
        self.hostname_regex_binary = regex.compile(pattern_str.encode("utf-8"), flags=regex.I | regex.M | regex.X)

    def apply_replacements(self, text: Union[str,bytes]) -> Union[str,bytes]:
        """Applies the regex replacements table to the input str or byte array.

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
        """Returns the replacement str. If all the cased characters in the
        original str are uppercase or title case, then the replacement string
        will be as well. It does not otherwise attempt to preserve the case."""

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
        """Returns the replacement bytes. If all the cased characters in the
        original bytes are uppercase or title case, then the replacement bytes
        will be as well. It does not otherwise attempt to preserve the case."""

        original_str = m.group().decode("utf-8", errors="ignore")
        replacement_str = self.replacements_table.get(original_str.lower(), original_str)

        if replacement_str == original_str:
            logging.warning("%s not found in replacements table (coding error) or the table maps it to itself", original_str)

        if original_str.isupper():
            replacement_str = replacement_str.upper()

        elif original_str.istitle():
            replacement_str = replacement_str.title()

        logging.info("Replacing %s with %s at offset %d", original_str, replacement_str, m.start())

        return replacement_str.encode("utf-8")


encoding_functions = {
    # No encoding
    'plain': lambda s: s,

    # Encode all non-alphanumeric characters except hyphens
    'html_hex': lambda s: ''.join(f'&#x{ord(c):x};' if not c.isalnum() or c == '-' else c for c in s),
    'html_numeric': lambda s: ''.join(f'&#{ord(c)};' if not c.isalnum() or c == '-' else c for c in s),
    'url': lambda s: ''.join(f'%{ord(c):02x}' if not c.isalnum() or c == '-' else c for c in s),

    # Encode all non-alphanumeric characters, including hyphens
    'html_hex_not_alphanum': lambda s: ''.join(f'&#x{ord(c):x};' if not c.isalnum() else c for c in s),
    'html_numeric_not_alphanum': lambda s: ''.join(f'&#{ord(c)};' if not c.isalnum() else c for c in s),
    'url_not_alphanum': lambda s: ''.join(f'%{ord(c):02x}' if not c.isalnum() else c for c in s),

    # Encode all characters
    'html_hex_all': lambda s: ''.join(f'&#x{ord(c):x};' for c in s),
    'html_numeric_all': lambda s: ''.join(f'&#{ord(c)};' for c in s),
    'url_all': lambda s: ''.join(f'%{ord(c):02x}' for c in s)
}

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
        ;                                                               # ...a semicolon when not preceded by HTML-encoded alphanumeric or dot
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

def main():
    """Entry point for command-line invocation.

    Parses command-line arguments and performs hostname replacements in the
    specified input file, writing the results to the output file or stdout.
    """
    parser = argparse.ArgumentParser(description="Replace hostnames and domains based on a provided mapping.")

    parser.add_argument(
        "input", type=argparse.FileType('rb'), nargs='?', default=sys.stdin.buffer,
        help="input file to read from. If not provided, read from stdin"
    )

    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="output file to write the replaced content. If not provided, write to stdout"
    )

    parser.add_argument(
        "-m", "--mapping", type=str, required=True,
        help='JSON file that contains the host mapping dictionary (e.g., {"web.example.com": "www.example.net"})'
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="display the replacements made"
    )

    args = parser.parse_args()

    logging.basicConfig(level=
        logging.INFO if args.verbose else logging.WARNING,
        format='%(levelname)s: %(message)s'
    )

    try:
        with open(args.mapping, "r", encoding="utf-8") as mapping_file:
            host_map = json.load(mapping_file)
    except IOError as e:
        logging.error("Cannot open host map file: %s", e)
        sys.exit(1)
    except json.decoder.JSONDecodeError as e:
        logging.error("%s is not a valid JSON file: %s", args.mapping, e)
        sys.exit(1)

    try:
        replacer = HostnameReplacer(host_map)
    except ValueError as e:
        logging.error("%s is not a valid host map: %s", args.mapping, e)
        sys.exit(1)

    input_text = args.input.read()
    output_text = replacer.apply_replacements(input_text)

    if args.output:
        with open(args.output, mode="wb", encoding=None) as outfile:
            outfile.write(output_text)
    else:
        sys.stdout.buffer.write(output_text)

if __name__ == '__main__':
    main()
