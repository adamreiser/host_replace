"""
Replace hostnames in input based on a provided host mapping.

This module provides a command-line tool and an API to replace hostnames
in text, automatically handling various text-compatible encodings (URL, HTML
entity).

Command-line:
    host-replace [-h] [-o OUTPUT] -m MAPPING [-v] [input]

API:
    import host_replace

    host_map = {"web.example.com": "www.example.com"}

    replacer = host_replace.HostnameReplacer(host_map)

    output_text = replacer.apply_replacements("Visit us at https://web.example.com")

    # Output: Visit us at https://www.example.com
    print(output_text)
"""
from .host_replace import HostnameReplacer, encoding_functions, HYPHEN, DOT
__all__ = ["HostnameReplacer"]
