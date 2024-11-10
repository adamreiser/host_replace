#!/usr/bin/env python3
"""Unit tests for the Host Replace module"""

import unittest
import logging
import string
import re
import urllib.parse
import html
from host_replace import HostnameReplacer, encoding_functions, HYPHEN, DOT

#logging.basicConfig(level=logging.DEBUG)

class TestHostnameReplacement(unittest.TestCase):
    """Unit test class for hostreplace.HostnameReplacer"""
    alphanumerics = tuple(string.ascii_letters + string.digits)

    hyphen = re.compile(HYPHEN, flags=re.I)
    hyphen_binary = re.compile(HYPHEN.encode("utf-8"), flags=re.I)

    dot = re.compile(DOT, flags=re.I)
    dot_binary = re.compile(DOT.encode("utf-8"), flags=re.I)

    # These sequences should act as delimiters, allowing the host to be replaced
    prefixes = ("",
                " ",
                "\n",
                "\r",
                "https://",
                "href='",
                'href="',
                'b"',
                "b'",
                "=",
                "=.",
                ".",    # We don't want to match "undefined.example.com" for "example.com", but we do want to match, e.g., "=.example.com"
                "`",
                ".",
                " .",
                "=.",
                "-",    # A hyphen is not a valid start for a hostname, so this is a delimiter
                "%",    # A "%" prefix is ambiguous and will cause failures for domains beginning with hex codes
                "-.",
                "..",
                "a..",
                "a-."
                "\\",
                #"-a-", # These should act as delimiters but currently do not
                #".-",
                #"$-",
                #"*-",
                #"a*-"
    )

    # These sequences should act as delimiters, allowing the host to be replaced
    suffixes = ("",
                " ",
                "\n",
                "\r",
                '"',
                "'",
                "`",
                "\\",
                "?",
                "?foo=bar",
                "/",
                "/path",
                "/path?foo=bar")

    # These sequences should be treated as part of the host, and prevent replacement
    negative_prefixes = ("a.", "a-", "a--", ".a.", "..a", "-a.", "A", "z")
    negative_suffixes = ("A", "z", "0", "9", "-a", ".a")

    def setUp(self):
        self.host_map = {
            # Basic subdomain change
            "web.example.com": "www.example.com",

            # Numbers
            "web-1a.example.com": "www-1a.example.com",

            # Partial hostname contained in subsequent hostnames
            "en.us.example.com": "en.us.regions.example.com",

            # Original is a partial match of a prior replacement
            "regions.example.com": "geo.example.com",

            # Deeper subdomain level in replacement
            "boards.example.com": "forums.en.us.example.com",

            # Deeper subdomain level in original; replacement inside original
            "en.us.wiki.example.com": "wiki.example.com",

            # Replacement has a hyphen while original does not
            "us.example.com": "us-east-1.example.net",

            # Map a second level domain to a different second level domain
            "example.net": "example.org",

            # Map both domain and subdomain
            "images.example.com": "cdn.example.org",

            # Unqualified hostname to FQDN
            "files": "cloud.example.com",

            # Unqualified hostname gains a hyphen
            "intsrv": "internal-file-server",

            # Gain both dots and hyphens
            "inthost1": "external-host-1.example.com",

        }

        self.replacer = HostnameReplacer(self.host_map)

    def test_delimiters(self):
        """Tests every replacement in the table for all encodings with
        a variety of delimiters."""
        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in encoding_functions.items():

                # Skip the encoding functions that are unencoded-equivalent for the original hostname
                # These comparisons would fail if the function is not unencoded-equivalent for the replacement hostname
                if encoding_function(original) == original and encoding_name != "plain":
                    logging.debug("Skipping %s comparison of %s", encoding_name, original)
                    continue

                # Test the prefixes and suffixes that should result in a replacement, in every combination
                for suffix in self.suffixes:
                    for prefix in self.prefixes:

                        # Encode the domain and the delimiters
                        input_text = encoding_function(prefix + original + suffix)

                        # Encode only the domain
                        #input_text = prefix + encoding_function(original) + suffix

                        if prefix != "" and suffix != "":
                            self.assertNotIn(input_text, self.host_map, msg="Invalid test conditions")

                        # Encode the domain and the delimiters
                        expected_output = encoding_function(prefix + replacement + suffix)

                        # Encode only the domain
                        #expected_output = prefix + encoding_function(replacement) + suffix

                        actual_output = self.replacer.apply_replacements(input_text)

                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_nondelimiters(self):
        """Tests every entry in the table for all encodings, with
        a variety of non-delimiting strings. No replacements should be made."""
        for original in self.host_map:
            for encoding_name, encoding_function in encoding_functions.items():

                # Test the prefixes and suffixes that should not result in a replacement

                # The negative cases must be tested separately so that a failing negative case
                # (one that fails to prevent replacement) is not "masked" by a succeeding one.

                for suffix in self.negative_suffixes + self.alphanumerics:
                    # Encode the domain and the suffix
                    input_text = encoding_function(original + suffix)

                    # Encode only the domain
                    #input_text = encoding_function(original) + suffix
                    self.assertNotIn(input_text, self.host_map, msg="Invalid test conditions")

                    # No change expected
                    expected_output = input_text
                    actual_output = self.replacer.apply_replacements(input_text)
                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

                for prefix in self.negative_prefixes + self.alphanumerics:
                    input_text = encoding_function(prefix + original)
                    self.assertNotIn(input_text, self.host_map, msg="Invalid test conditions")

                    # No change expected
                    expected_output = input_text
                    actual_output = self.replacer.apply_replacements(input_text)
                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_bad_unicode_bytes(self):
        """Test that invalid unicode bytes does not result in errors and that it acts as a delimiter."""

        bad_unicode = {
            b"\xc1\x80":         "invalid start byte",
            b"\x80":             "invalid start byte",
            b"\xf5\x80\x80\x80": "invalid start byte",
            b"\xf8\x88\x80\x80": "invalid start byte",
            b"\xe0\x80\x80":     "invalid continuation byte",
            b"\xf0\x80\x80\x80": "invalid continuation byte",
            b"\xed\xa0\x80":     "invalid continuation byte",
            b"\xf4\x90\x80\x80": "invalid continuation byte",
            b"\xc2":             "unexpected end of data",
            b"\xe1\x80":         "unexpected end of data",
            b"\xf0\x90\x80":     "unexpected end of data",
        }

        for bad, reason in bad_unicode.items():
            try:
                bad.decode("utf-8")
            except UnicodeDecodeError as e:
                self.assertEqual(e.args[4], reason, msg="Invalid test conditions")

            for original,replacement in self.host_map.items():
                for encoding_name, encoding_function in encoding_functions.items():

                    # Skip the encoding functions that are unencoded-equivalent for the original hostname
                    # These comparisons would fail if the function is not unencoded-equivalent for the replacement hostname
                    if encoding_function(original) == original and encoding_name != "plain":
                        logging.debug("Skipping %s comparison of %s", encoding_name, original)
                        continue

                    input_text = bad + encoding_function(original).encode("utf-8") + bad
                    expected_output = bad + encoding_function(replacement).encode("utf-8") + bad
                    actual_output = self.replacer.apply_replacements(input_text)

                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} under encoding '{encoding_name}'.")

    def test_bad_unicode_str(self):
        """Test that invalid unicode str does not result in errors and that it acts as a delimiter."""

        bad_unicode = {
            "\xc1\x80":         "invalid start byte",
            "\x80":             "invalid start byte",
            "\xf5\x80\x80\x80": "invalid start byte",
            "\xf8\x88\x80\x80": "invalid start byte",
            "\xe0\x80\x80":     "invalid continuation byte",
            "\xf0\x80\x80\x80": "invalid continuation byte",
            "\xed\xa0\x80":     "invalid continuation byte",
            "\xf4\x90\x80\x80": "invalid continuation byte",
            "\xc2":             "unexpected end of data",
            "\xe1\x80":         "unexpected end of data",
            "\xf0\x90\x80":     "unexpected end of data",
        }

        for bad, reason in bad_unicode.items():
            for original, replacement in self.host_map.items():
                for encoding_name, encoding_function in encoding_functions.items():
                    # Skip the encoding functions that are unencoded-equivalent for the original hostname
                    # These comparisons would fail if the function is not unencoded-equivalent for the replacement hostname
                    if encoding_function(original) == original and encoding_name != "plain":
                        logging.debug("Skipping %s comparison of %s", encoding_name, original)
                        continue

                    input_text = bad + encoding_function(original) + bad
                    expected_output = bad + encoding_function(replacement) + bad
                    actual_output = self.replacer.apply_replacements(input_text)

                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_undefined_subdomain_replacement(self):
        """Test whether an undefined subdomain is replaced.""" 
        for original in self.host_map:
            for encoding_name, encoding_function in encoding_functions.items():
                self.assertNotIn(f"undefined.{original}", self.host_map, msg="Invalid test conditions")
                input_text = encoding_function("undefined." + original)
                expected_output = input_text
                actual_output = self.replacer.apply_replacements(input_text)
                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_bare_domain_replacement(self):
        """Test whether a bare second level domain is replaced.""" 
        self.assertNotIn("example.com", self.host_map, msg="Invalid test conditions")
        for encoding_name, encoding_function in encoding_functions.items():
            input_text = encoding_function("example.com")
            expected_output = input_text
            actual_output = self.replacer.apply_replacements(input_text)
            self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_url_with_encoded_redirect(self):
        """Test whether an unencoded primary hostname and an encoded secondary hostname are both replaced correctly."""
        for original_primary, replacement_primary in self.host_map.items():
            for original_secondary, replacement_secondary in self.host_map.items():
                for encoding_name, encoding_function in encoding_functions.items():
                    # Skip the encoding functions that are unencoded-equivalent for the original hostname
                    # These comparisons would fail if the function is not unencoded-equivalent for the replacement hostname
                    if encoding_function(original_secondary) == original_secondary and encoding_name != "plain":
                        logging.debug("Skipping %s comparison of %s", encoding_name, original_secondary)
                        continue

                    # Encode only the parameter
                    encoded_original_secondary = encoding_function(f"https://{original_secondary}")
                    input_text = f"https://{original_primary}?next={encoded_original_secondary}"
                    encoded_replacement_secondary = encoding_function(f"https://{replacement_secondary}")
                    expected_output = f"https://{replacement_primary}?next={encoded_replacement_secondary}"
                    actual_output = self.replacer.apply_replacements(input_text)

                    self.assertEqual(actual_output, expected_output, msg="{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_wildcard_dots(self):
        """Test that dots in the hostname are treated as literal dots, not as wildcards."""
        self.assertEqual(self.host_map["web.example.com"], "www.example.com", msg="Invalid test conditions")
        input_text = "webxexamplexcom"
        expected_output = input_text
        actual_output = self.replacer.apply_replacements(input_text)
        self.assertEqual(actual_output, expected_output, msg="The '.' character must be escaped so that it's not treated as a wildcard.")

    def test_case_preservation(self):
        """Test basic post-encoding case preservation under simple encodings.

        Note that since encoding is performed first, this compares the
        representation of the encoded strings ("%2e" vs "%2E"), not their
        underlying values ("%41" vs "%61").
        """

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in encoding_functions.items():

                # Skip the encoding functions that are unencoded-equivalent for the original hostname
                # These comparisons would fail if the function is not unencoded-equivalent for the replacement hostname
                if encoding_function(original) == original and encoding_name != "plain":
                    logging.debug("Skipping %s comparison of %s", encoding_name, original)
                    continue

                # Test str
                input_text = encoding_function(original).upper()
                expected_output = encoding_function(replacement).upper()
                actual_output = self.replacer.apply_replacements(input_text)

                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

                # Test bytes
                input_text = encoding_function(original).encode("utf-8").upper()
                expected_output = encoding_function(replacement).encode("utf-8").upper()
                actual_output = self.replacer.apply_replacements(input_text)

                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_transitive(self):
        """Test that host maps containing A-to-B and B-to-C mappings do not
        result in A being mapped to C. Verify that it is not dependent on
        ordering."""

        transitive_host_maps = [
            {
                "a.b": "c.d",
                "c.d": "e.f"
            },

            {
                "c.d": "e.f",
                "a.b": "c.d"
            },

            {
                "test.example.com": "example.org",
                "example.org": "test.example.com"
            }
        ]

        for host_map in transitive_host_maps:
            transitive_replacements = HostnameReplacer(host_map)

            for original, replacement in host_map.items():
                input_text = original
                expected_output = replacement
                actual_output = transitive_replacements.apply_replacements(input_text)
                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output}.")

    def _disabled_test_pre_encoding_case(self):
        """Display cosmetic and functional casing behavior."""
        self.assertEqual(self.host_map["web.example.com"], "www.example.com", msg="Invalid test conditions")
        for encoding_function in encoding_functions.values():
            input_text = encoding_function("WEB.EXAMPLE.COM")
            expected_output = encoding_function("WWW.EXAMPLE.COM")
            actual_output = self.replacer.apply_replacements(input_text)

            decoded_expected_output = urllib.parse.unquote(html.unescape(expected_output))
            decoded_actual_output = urllib.parse.unquote(html.unescape(actual_output))

            if decoded_actual_output != decoded_expected_output:
                if decoded_actual_output.lower() == decoded_expected_output.lower():
                    # Cosmetic failure
                    logging.warning("Case is not preserved: %s results in %s instead of %s", input_text, actual_output, expected_output)
                else:
                    # Functional failure
                    logging.error("%s incorrectly results in %s instead of %s.", input_text, actual_output, expected_output)
                    #self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output}.")

if __name__ == "__main__":
    unittest.main()
