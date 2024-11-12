#!/usr/bin/env python3
"""Unit tests for the Host Replace module"""

import unittest
import logging
import string
import urllib.parse
import html
import host_replace

def skip(original, replacement, encoding_function):
    """
    Identify whether the transform of the encoded original is expected to differ from the encoded replacement.

    Returns:
        True if the encoding alters the replacement but not the original (to avoid introducing new encodings)
        True if the original does not contain hyphens, the replacement does, and the encoding encodes hyphens
        False otherwise
    """

    charset = "-"

    if encoding_function(original) == original and encoding_function(replacement) != replacement:
        return True

    for char in charset:
        if char not in original and char in replacement and encoding_function(char) == char:
            return True
    return False

class TestHostnameReplacement(unittest.TestCase):
    """Unit test class for host_replace.HostnameReplacer"""
    alphanumerics = tuple(string.ascii_letters + string.digits)

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
                "%",
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


    def setUp(self):
        self.host_map = {
            # Basic subdomain change
            "web.example.com": "www.example.com",

            # Numbers
            "web-1a.example.com": "www-1a.example.com",

            # Partial hostname contained in subsequent hostnames
            "en.us.example.com": "en.us.regions.example.com",

            # Hex sequence that could be confused with an encoded dot when precede by %
            "2e.example.com": "dot.example.com",

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

            # Gain both dots and hyphens (test against potential one-to-many mapping)
            "inthost1": "external-host-1.example.com",
        }

        self.replacer = host_replace.HostnameReplacer(self.host_map)

    def test_encoding_functions(self):
        """Test that the encoding functions are correctly labeled and perform the expected encodings."""
        input_text = "1-a?./;&%"
        expected_outputs = {
            "plain": "1-a?./;&%",
            "html_hex": "1-a&#x3f;&#x2e;&#x2f;&#x3b;&#x26;&#x25;",
            "html_numeric": "1-a&#63;&#46;&#47;&#59;&#38;&#37;",
            "url": "1-a%3f%2e%2f%3b%26%25",
            "html_hex_not_alphanum": "1&#x2d;a&#x3f;&#x2e;&#x2f;&#x3b;&#x26;&#x25;",
            "html_numeric_not_alphanum": "1&#45;a&#63;&#46;&#47;&#59;&#38;&#37;",
            "url_not_alphanum": "1%2da%3f%2e%2f%3b%26%25",
            "html_hex_all": "&#x31;&#x2d;&#x61;&#x3f;&#x2e;&#x2f;&#x3b;&#x26;&#x25;",
            "html_numeric_all": "&#49;&#45;&#97;&#63;&#46;&#47;&#59;&#38;&#37;",
            "url_all": "%31%2d%61%3f%2e%2f%3b%26%25"
        }

        for encoding_name, encoding_function in host_replace.encoding_functions.items():
            function_output = encoding_function(input_text)

            self.assertEqual(expected_outputs[encoding_name], function_output, msg=f"Encoding error: {input_text} incorrectly results in {function_output} instead of {expected_outputs[encoding_name]} under {encoding_name} encoding.")

    def test_delimiters(self):
        """Test every replacement in the table for all encodings with
        a variety of delimiters."""
        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():

                if skip(original, replacement, encoding_function):
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
        """Test every entry in the table for all encodings, with
        a variety of non-delimiting strings. No replacements should be made."""
        for original in self.host_map:
            for encoding_name, encoding_function in host_replace.encoding_functions.items():

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
        """Test that invalid UTF-8 bytes do not raise exceptions and that they act as delimiters."""

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                if skip(original, replacement, encoding_function):
                    continue
                for bad, reason in self.bad_unicode.items():
                    bad_bytes = bad.encode("latin-1")
                    input_text = bad_bytes + encoding_function(original).encode("utf-8") + bad_bytes
                    expected_output = bad_bytes + encoding_function(replacement).encode("utf-8") + bad_bytes
                    actual_output = self.replacer.apply_replacements(input_text)

                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} under encoding '{encoding_name}'.")

    def test_bad_unicode_str(self):
        """Test that invalid UTF-8 strings do not raise exceptions and that they act as delimiters."""

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                if skip(original, replacement, encoding_function):
                    continue
                for bad, reason in self.bad_unicode.items():
                    input_text = bad + encoding_function(original) + bad
                    expected_output = bad + encoding_function(replacement) + bad
                    actual_output = self.replacer.apply_replacements(input_text)

                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_undefined_subdomain_replacement(self):
        """Test whether an undefined subdomain is replaced."""
        for original in self.host_map:
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                self.assertNotIn(f"undefined.{original}", self.host_map, msg="Invalid test conditions")
                input_text = encoding_function("undefined." + original)
                expected_output = input_text
                actual_output = self.replacer.apply_replacements(input_text)
                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_bare_domain_replacement(self):
        """Test whether a bare second level domain is replaced."""
        self.assertNotIn("example.com", self.host_map, msg="Invalid test conditions")
        for encoding_name, encoding_function in host_replace.encoding_functions.items():
            input_text = encoding_function("example.com")
            expected_output = input_text
            actual_output = self.replacer.apply_replacements(input_text)
            self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_url_with_encoded_redirect(self):
        """Test whether an unencoded hostname and an encoded hostname are both replaced correctly."""
        for encoding_name, encoding_function in host_replace.encoding_functions.items():
            for original_redirect, replacement_redirect in self.host_map.items():
                if skip(original_redirect, replacement_redirect, encoding_function):
                    continue
                for original_hostname, replacement_hostname in self.host_map.items():
                    encoded_original_redirect = encoding_function(f"https://{original_redirect}")
                    input_text = f"https://{original_hostname}?next={encoded_original_redirect}"

                    encoded_replacement_redirect = encoding_function(f"https://{replacement_redirect}")
                    expected_output = f"https://{replacement_hostname}?next={encoded_replacement_redirect}"

                    actual_output = self.replacer.apply_replacements(input_text)

                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

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
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                if skip(original, replacement, encoding_function):
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
            transitive_replacements = host_replace.HostnameReplacer(host_map)

            for original, replacement in host_map.items():
                input_text = original
                expected_output = replacement
                actual_output = transitive_replacements.apply_replacements(input_text)
                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output}.")

    def _disabled_test_pre_encoding_case(self):
        """Display cosmetic and functional casing behavior."""
        self.assertEqual(self.host_map["web.example.com"], "www.example.com", msg="Invalid test conditions")
        for encoding_function in host_replace.encoding_functions.values():
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
