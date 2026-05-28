#!/usr/bin/env python3
"""Unit tests for the Host Replace module"""

import unittest
import logging
import string
import urllib.parse
import html
import subprocess
import sys
import json
import pytest
import host_replace

logger = logging.getLogger(__name__)

class TestHostnameReplacement(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Unit test class for host_replace.HostnameReplacer"""

    # These sequences should act as delimiters, allowing the host to be replaced
    prefixes = ("",
                " ",
                "\n",
                "\r",
                "https://",
                "href='",
                'href="',
                "@",
                'b"',
                "b'",
                "=",
                "=.",
                ".",    # We don't want to match "undefined.example.com" for "example.com", but we do want to match, e.g., "=.example.com"
                "`",
                ".",
                " .",
                "=.",
                "-",    # A hyphen is not a valid start for a hostname, so this is a delimiter unless preceded by an alphanumeric
                "%",
                "-.",
                "..",
                "a..",
                "a-.",
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
                ":",
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

            # IPv4 and IPv6 addresses
            "127.0.0.1": "home.example.com",
            "2001:db8::": "ipv6.example.com",

            # Partial hostname contained in replacement hostname
            "en.us.example.com": "en.us.regions.example.com",

            # Hex sequence that could be confused with an encoded dot when preceded by %
            "2e.example.com": "dot.example.com",

            # Original is a subdomain of replacement
            "en.us.wiki.example.com": "wiki.example.com",

            # Replacement has a hyphen while original does not
            "us.example.com": "us-east-1.example.net",

            # Map second level domain
            "example.net": "example.org",

            # Map domain and subdomain
            "images.example.com": "cdn.example.org",

            # Unqualified hostname to FQDN
            "files": "cloud.example.com",

            # Unqualified hostname gains hyphens
            "intsrv": "internal-file-server",

            # Unqualified hostname gains dots and hyphens
            "inthost1": "external-host-1.example.com",
        }

        self.replacer = host_replace.HostnameReplacer(self.host_map)
        self.skip_count = 0

    def tearDown(self):
        logger.info("Skipped %s comparisons", self.skip_count)

    def skip(self, original, replacement, encoding_function):
        """
        Identify whether the transform of the encoded original is expected to
        differ from the transform of the encoded replacement.

        This helps us determine whether specific comparisons are meaningful.

        Returns:
            False for all unencoded comparisons
            True if the original contains no characters that would be encoded
            True if the replacement contains a hyphen
        """

        if encoding_function.__name__ == "encoding_plain":
            return False

        if encoding_function(original) == original or "-" in replacement:
            self.skip_count += 1
            logger.debug("Skipping comparison of %s to %s under %s", original, replacement, encoding_function.__name__)
            return True

        return False

    @staticmethod
    def decode_text(value):
        """Decode URL and HTML entity encodings for semantic comparisons."""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return urllib.parse.unquote(html.unescape(value))

    def test_encoding_functions(self):
        """Test that the encoding functions are correctly labeled and perform the expected encodings."""
        input_text = "1-a?./;&%"
        expected_outputs = {
            "encoding_plain": "1-a?./;&%",
            "encoding_html_hex": "1-a&#x3f;&#x2e;&#x2f;&#x3b;&#x26;&#x25;",
            "encoding_html_numeric": "1-a&#63;&#46;&#47;&#59;&#38;&#37;",
            "encoding_url": "1-a%3f%2e%2f%3b%26%25",
            "encoding_html_hex_not_alphanum": "1&#x2d;a&#x3f;&#x2e;&#x2f;&#x3b;&#x26;&#x25;",
            "encoding_html_numeric_not_alphanum": "1&#45;a&#63;&#46;&#47;&#59;&#38;&#37;",
            "encoding_url_not_alphanum": "1%2da%3f%2e%2f%3b%26%25",
            "encoding_html_hex_all": "&#x31;&#x2d;&#x61;&#x3f;&#x2e;&#x2f;&#x3b;&#x26;&#x25;",
            "encoding_html_numeric_all": "&#49;&#45;&#97;&#63;&#46;&#47;&#59;&#38;&#37;",
            "encoding_url_all": "%31%2d%61%3f%2e%2f%3b%26%25"
        }

        for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
            function_output = encoding_function(input_text)
            with self.subTest(encoding_name=encoding_name):
                assert expected_outputs[encoding_name] == function_output, f"Encoding error: {input_text} incorrectly results in {function_output} instead of {expected_outputs[encoding_name]} under {encoding_name} encoding."

    def test_url_encoding_uses_utf8_bytes_for_non_ascii(self):
        """URL encoders should percent-encode UTF-8 bytes, not code points."""
        encoding_functions = host_replace.host_replace.encoding_functions

        assert encoding_functions["encoding_url_all"]("é🙂") == "%c3%a9%f0%9f%99%82"
        assert encoding_functions["encoding_url_not_alphanum"]("a🙂-?") == "a%f0%9f%99%82%2d%3f"
        assert encoding_functions["encoding_url"]("a🙂-?") == "a%f0%9f%99%82-%3f"

    def test_replacements_table(self):
        """Test that the replacements table is correctly created for an
        unqualified hostname that is mapped to a fully qualified hostname that
        includes hyphens."""

        host_map = {"web-1a.example.com": "www-1a.example.com"}
        tmp_replacer = host_replace.HostnameReplacer(host_map)
        expected_replacements_table = {
            "web-1a.example.com": "www-1a.example.com",
            "web-1a&#x2e;example&#x2e;com": "www-1a&#x2e;example&#x2e;com",
            "web-1a&#46;example&#46;com": "www-1a&#46;example&#46;com",
            "web-1a%2eexample%2ecom": "www-1a%2eexample%2ecom",
            "web&#x2d;1a&#x2e;example&#x2e;com": "www&#x2d;1a&#x2e;example&#x2e;com",
            "web&#45;1a&#46;example&#46;com": "www&#45;1a&#46;example&#46;com",
            "web%2d1a%2eexample%2ecom": "www%2d1a%2eexample%2ecom",
            "&#x77;&#x65;&#x62;&#x2d;&#x31;&#x61;&#x2e;&#x65;&#x78;&#x61;&#x6d;&#x70;&#x6c;&#x65;&#x2e;&#x63;&#x6f;&#x6d;": "&#x77;&#x77;&#x77;&#x2d;&#x31;&#x61;&#x2e;&#x65;&#x78;&#x61;&#x6d;&#x70;&#x6c;&#x65;&#x2e;&#x63;&#x6f;&#x6d;",
            "&#119;&#101;&#98;&#45;&#49;&#97;&#46;&#101;&#120;&#97;&#109;&#112;&#108;&#101;&#46;&#99;&#111;&#109;": "&#119;&#119;&#119;&#45;&#49;&#97;&#46;&#101;&#120;&#97;&#109;&#112;&#108;&#101;&#46;&#99;&#111;&#109;",
            "%77%65%62%2d%31%61%2e%65%78%61%6d%70%6c%65%2e%63%6f%6d": "%77%77%77%2d%31%61%2e%65%78%61%6d%70%6c%65%2e%63%6f%6d"
        }

        for k,v in expected_replacements_table.items():
            with self.subTest(key=k, value=v):
                assert tmp_replacer.replacements_table.get(k) == v

        for k,v in tmp_replacer.replacements_table.items():
            with self.subTest(key=k, value=v):
                assert expected_replacements_table.get(k) == v

        # Split this into a separate test
        host_map = {"example": "us-east-1.example.net"}
        tmp_replacer = host_replace.HostnameReplacer(host_map)
        expected_replacements_table = {
            "example": "us-east-1.example.net",
            "&#x65;&#x78;&#x61;&#x6d;&#x70;&#x6c;&#x65;": "&#x75;&#x73;&#x2d;&#x65;&#x61;&#x73;&#x74;&#x2d;&#x31;&#x2e;&#x65;&#x78;&#x61;&#x6d;&#x70;&#x6c;&#x65;&#x2e;&#x6e;&#x65;&#x74;",
            "&#101;&#120;&#97;&#109;&#112;&#108;&#101;": "&#117;&#115;&#45;&#101;&#97;&#115;&#116;&#45;&#49;&#46;&#101;&#120;&#97;&#109;&#112;&#108;&#101;&#46;&#110;&#101;&#116;",
            "%65%78%61%6d%70%6c%65": "%75%73%2d%65%61%73%74%2d%31%2e%65%78%61%6d%70%6c%65%2e%6e%65%74"
        }

        for k,v in tmp_replacer.replacements_table.items():
            with self.subTest(key=k, value=v):
                assert expected_replacements_table.get(k) == v

    def test_no_extra_hyphen_encoding_for_colliding_keys(self):
        """If multiple encoders produce the same search key, avoid introducing
        extra encoded hyphens in the replacement."""

        host_map = {"us.example.com": "us-east-1.example.net"}
        tmp_replacer = host_replace.HostnameReplacer(host_map)
        encoding_functions = host_replace.host_replace.encoding_functions

        cases = [
            ("encoding_html_hex", "us-east-1&#x2e;example&#x2e;net"),
            ("encoding_html_numeric", "us-east-1&#46;example&#46;net"),
            ("encoding_url", "us-east-1%2eexample%2enet"),
        ]

        for encoding_name, expected_output in cases:
            input_text = encoding_functions[encoding_name]("us.example.com")
            actual_output = tmp_replacer.apply_replacements(input_text)
            with self.subTest(encoding_name=encoding_name):
                assert actual_output == expected_output

    def test_no_new_encoding_when_original_is_unchanged(self):
        """If an encoding does not change the original key, keep replacement
        plain instead of introducing new encoded characters."""

        host_map = {
            "files": "cloud.example.com",
            "intsrv": "internal-file-server",
            "inthost1": "external-host-1.example.com",
        }
        tmp_replacer = host_replace.HostnameReplacer(host_map)
        encoding_functions = host_replace.host_replace.encoding_functions

        for original, replacement in host_map.items():
            for encoding_name in (
                "encoding_html_hex",
                "encoding_html_hex_not_alphanum",
                "encoding_html_numeric",
                "encoding_html_numeric_not_alphanum",
                "encoding_url",
                "encoding_url_not_alphanum",
            ):
                encoding_function = encoding_functions[encoding_name]
                encoded_original = encoding_function(original)
                if encoded_original != original:
                    continue
                actual_output = tmp_replacer.apply_replacements(encoded_original)
                with self.subTest(original=original, encoding_name=encoding_name):
                    assert actual_output == replacement

    def test_delimiters(self):
        """Test every replacement in the table for all encodings with
        a variety of delimiters."""
        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():

                if self.skip(original, replacement, encoding_function):
                    continue

                # Test the prefixes and suffixes that should result in a replacement, in every combination
                for suffix in self.suffixes:
                    for prefix in self.prefixes:

                        # Encode the domain and the delimiters
                        input_text = encoding_function(prefix + original + suffix)

                        # Alternative test: encode only the domain
                        #input_text = prefix + encoding_function(original) + suffix

                        if prefix != "" and suffix != "" and input_text in self.host_map:
                            self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")

                        # Encode the domain and the delimiters
                        expected_output = encoding_function(prefix + replacement + suffix)

                        # Alternative test: encode only the domain
                        #expected_output = prefix + encoding_function(replacement) + suffix

                        actual_output = self.replacer.apply_replacements(input_text)

                        with self.subTest(original=original, prefix=prefix, suffix=suffix, encoding_name=encoding_name):
                            assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

    def test_skipped_cases_are_semantically_equivalent(self):
        """Ensure skipped style-ambiguous cases still produce correct decoded values."""

        # Keep this focused: representative delimiters catch boundary behavior
        # without exploding runtime like the full delimiter matrix.
        prefixes = ("", "https://", "href=\"", "a..")
        suffixes = ("", "/path", "?next=1")

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
                if encoding_name == "encoding_plain":
                    continue
                if not self.skip(original, replacement, encoding_function):
                    continue

                for prefix in prefixes:
                    for suffix in suffixes:
                        input_text = encoding_function(prefix + original + suffix)
                        expected_output = encoding_function(prefix + replacement + suffix)
                        actual_output = self.replacer.apply_replacements(input_text)

                        decoded_actual = self.decode_text(actual_output)
                        decoded_expected = self.decode_text(expected_output)

                        with self.subTest(
                            original=original,
                            replacement=replacement,
                            encoding_name=encoding_name,
                            prefix=prefix,
                            suffix=suffix,
                        ):
                            assert decoded_actual == decoded_expected, (
                                f"{input_text} decodes to {decoded_actual} instead of "
                                f"{decoded_expected} under {encoding_name} encoding."
                            )

    def test_nondelimiters(self):
        """Test every entry in the table for all encodings, with
        a variety of non-delimiting strings. No replacements should be made."""

        alphanumerics = tuple(string.ascii_letters + string.digits)

        for original in self.host_map:
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():

                # The negative prefixes and suffixes must be tested individually so that detection of
                # a prefix or suffix that incorrectly allows replacement is not "masked".

                for suffix in self.negative_suffixes + alphanumerics:
                    # Encode the domain and the suffix
                    input_text = encoding_function(original + suffix)

                    # Encode only the domain
                    #input_text = encoding_function(original) + suffix

                    if input_text in self.host_map:
                        self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")

                    # No change expected
                    expected_output = input_text
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, suffix=suffix, encoding_name=encoding_name):
                        assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

                for prefix in self.negative_prefixes + alphanumerics:
                    input_text = encoding_function(prefix + original)

                    if input_text in self.host_map:
                        self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")

                    # No change expected
                    expected_output = input_text
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, prefix=prefix, encoding_name=encoding_name):
                        assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

    def test_bad_unicode_bytes(self):
        """Test that invalid UTF-8 bytes do not raise exceptions and that they act as delimiters."""

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
                if self.skip(original, replacement, encoding_function):
                    continue

                for bad, reason in self.bad_unicode.items():
                    bad_bytes = bad.encode("latin-1")
                    input_text = bad_bytes + encoding_function(original).encode("utf-8") + bad_bytes
                    expected_output = bad_bytes + encoding_function(replacement).encode("utf-8") + bad_bytes
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, bad_bytes=bad_bytes, encoding_name=encoding_name, reason=reason):
                        assert actual_output == expected_output, f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} under encoding '{encoding_name}'."

    def test_bad_unicode_str(self):
        """Test that invalid UTF-8 strings do not raise exceptions and that they act as delimiters."""

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
                if self.skip(original, replacement, encoding_function):
                    continue

                for bad, reason in self.bad_unicode.items():
                    input_text = bad + encoding_function(original) + bad
                    expected_output = bad + encoding_function(replacement) + bad
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, encoding_name=encoding_name, reason=reason):
                        assert actual_output == expected_output, f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

    def test_no_undefined_subdomain_replacement(self):
        """Test whether an undefined subdomain is replaced."""
        for original in self.host_map:
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
                input_text = encoding_function(f"undefined.{original}")
                if input_text in self.host_map:
                    self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")
                expected_output = input_text
                actual_output = self.replacer.apply_replacements(input_text)

                with self.subTest(input_text=input_text, encoding_name=encoding_name):
                    assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

    def test_no_bare_domain_replacement(self):
        """Test whether a bare second level domain is replaced."""
        for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
            input_text = encoding_function("example.com")
            if input_text in self.host_map:
                self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")
            expected_output = input_text
            actual_output = self.replacer.apply_replacements(input_text)

            with self.subTest(input_text=input_text, encoding_name=encoding_name):
                assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

    def test_url_with_encoded_redirect(self):
        """Test whether an unencoded hostname and an encoded hostname are both replaced correctly."""
        for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
            for original_redirect, replacement_redirect in self.host_map.items():
                if self.skip(original_redirect, replacement_redirect, encoding_function):
                    continue

                for original_hostname, replacement_hostname in self.host_map.items():
                    encoded_original_redirect = encoding_function(f"https://{original_redirect}")
                    input_text = f"https://{original_hostname}?next={encoded_original_redirect}"
                    encoded_replacement_redirect = encoding_function(f"https://{replacement_redirect}")
                    expected_output = f"https://{replacement_hostname}?next={encoded_replacement_redirect}"

                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(input_text=input_text, encoding_name=encoding_name):
                        assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

    def test_no_wildcard_dots(self):
        """Test that dots in the hostname are treated as literal dots, not as wildcards."""
        if self.host_map.get("web.example.com") != "www.example.com" or "webxexamplexcom" in self.host_map:
            self.fail("Invalid test conditions: web.example.com must map to www.example.com and webxexamplexcom must not be in host map.")
        input_text = "webxexamplexcom"
        expected_output = input_text
        actual_output = self.replacer.apply_replacements(input_text)

        assert actual_output == expected_output, "The '.' character must be escaped so that it's not treated as a wildcard."

    def test_case_preservation(self):
        """Test basic post-encoding case preservation under simple encodings.

        Note that since encoding is performed first, this compares the
        representation of the encoded strings ("%2e" vs "%2E"), not their
        underlying values ("%41" vs "%61")
        """

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
                if self.skip(original, replacement, encoding_function):
                    continue

                # Test str
                input_text = encoding_function(original).upper()

                if not input_text.isupper():
                    continue

                expected_output = encoding_function(replacement).upper()
                actual_output = self.replacer.apply_replacements(input_text)

                with self.subTest(input_text=input_text, encoding_name=encoding_name):
                    assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

                # Test bytes
                input_text = encoding_function(original).encode("utf-8").upper()
                expected_output = encoding_function(replacement).encode("utf-8").upper()
                actual_output = self.replacer.apply_replacements(input_text)

                with self.subTest(input_text=input_text, encoding_name=encoding_name):
                    assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding."

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
                with self.subTest(input_text=input_text):
                    assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output}."

    @pytest.mark.skip(reason="pre-encoding case preservation is not implemented")
    def test_pre_encoding_case(self):
        """Test cosmetic and functional casing behavior. These tests fail due
        to the absence of pre-encoding case detection."""

        if self.host_map.get("web.example.com") != "www.example.com":
            self.fail("Invalid test conditions: web.example.com must map to www.example.com.")

        for encoding_name, encoding_function in host_replace.host_replace.encoding_functions.items():
            input_text = encoding_function("WEB.EXAMPLE.COM")
            expected_output = encoding_function("WWW.EXAMPLE.COM")
            actual_output = self.replacer.apply_replacements(input_text)

            decoded_expected_output = urllib.parse.unquote(html.unescape(expected_output))
            decoded_actual_output = urllib.parse.unquote(html.unescape(actual_output))

            if decoded_actual_output != decoded_expected_output:
                if decoded_actual_output.lower() == decoded_expected_output.lower():
                    # Cosmetic failure
                    logger.warning("Case is not preserved under %s encoding: %s results in %s instead of %s", encoding_name, input_text, actual_output, expected_output)
                else:
                    # Functional failure
                    with self.subTest(input_text=input_text, encoding_name=encoding_name):
                        assert actual_output == expected_output, f"{input_text} incorrectly results in {actual_output} instead of {expected_output}."

    def test_invalid_hostnames(self):
        """Test that exceptions are properly raised on invalid hostnames."""

        invalid_host_maps = [
            {"-test.example.com": "example.org"},
            {"test.example.com": "-example.org"},
            {"test.example.com": ""},
            {"/.com": "example.org"},
            {"127.0.-0.1": "example.org"},
            {"2001:db8::::": "invalid-ipv6.example.com"},
            {"..example.com": "example.org"},
            {"example.com": "example..org"},
            {1: "example.org"},
            {"test.example.com": True},
            {None: None},
            {"\xc1\x80test.example.com": "example.org"}
        ]

        for host_map in invalid_host_maps:
            with pytest.raises(ValueError):
                host_replace.HostnameReplacer(host_map)

    def test_invalid_host_map_types(self):
        """Test that invalid host map container/value types raise ValueError."""

        invalid_host_maps = [
            [],
            (),
            "not-a-dict",
            1,
            {"test.example.com": ["example.org"]},
            {"test.example.com": {"host": "example.org"}},
        ]

        for host_map in invalid_host_maps:
            with pytest.raises(ValueError):
                host_replace.HostnameReplacer(host_map)

if __name__ == "__main__":
    unittest.main()


def test_cli_output_write_error(tmp_path):
    """Test that CLI exits cleanly when output cannot be written."""

    mapping_path = tmp_path / "mapping.json"
    input_path = tmp_path / "input.txt"

    mapping_path.write_text(
        json.dumps({"web.example.com": "www.example.com"}),
        encoding="utf-8",
    )
    input_path.write_text("web.example.com", encoding="utf-8")

    # Use a directory as output path to force an OSError.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host_replace.cli",
            "-m",
            str(mapping_path),
            "-o",
            str(tmp_path),
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Cannot write output" in result.stderr


def test_cli_auto_engine_runs(tmp_path):
    """Test CLI execution with auto engine selection."""

    mapping_path = tmp_path / "mapping.json"
    input_path = tmp_path / "input.txt"

    mapping_path.write_text(
        json.dumps({"web.example.com": "www.example.com"}),
        encoding="utf-8",
    )
    input_path.write_text("https://web.example.com", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host_replace.cli",
            "-m",
            str(mapping_path),
            "-v",
            "--engine",
            "auto",
            "--expected-runs",
            "2",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "https://www.example.com" in result.stdout
    assert "Auto-selected engine=" in result.stderr


def test_cli_empty_mapping_automaton_is_noop(tmp_path):
    """Test CLI accepts empty mapping under automaton engine as a no-op."""

    mapping_path = tmp_path / "mapping.json"
    input_path = tmp_path / "input.txt"

    mapping_path.write_text("{}", encoding="utf-8")
    input_path.write_text("https://web.example.com", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host_replace.cli",
            "-m",
            str(mapping_path),
            "--engine",
            "automaton",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "https://web.example.com"


def test_cli_invalid_expected_runs_is_reported_as_argument_error(tmp_path):
    """Test CLI rejects non-positive --expected-runs values as argument errors."""

    mapping_path = tmp_path / "mapping.json"
    input_path = tmp_path / "input.txt"

    mapping_path.write_text(
        json.dumps({"web.example.com": "www.example.com"}),
        encoding="utf-8",
    )
    input_path.write_text("https://web.example.com", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host_replace.cli",
            "-m",
            str(mapping_path),
            "--engine",
            "auto",
            "--expected-runs",
            "0",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must be a positive integer" in result.stderr
