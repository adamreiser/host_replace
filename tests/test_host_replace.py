#!/usr/bin/env python3
"""Unit tests for the Host Replace module"""

import unittest
import logging
import string
import urllib.parse
import html
import host_replace


class TestHostnameReplacement(unittest.TestCase):
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

            # Partial hostname contained in subsequent hostnames
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
        logging.info("Skipped %s comparisons", self.skip_count)

    def skip(self, original, replacement, encoding_function):
        """
        Identify whether the transform of the encoded original is expected to
        differ from the transform of the encoded replacement.

        This helps us determine whether specific comparisons are meaningful.

        Returns:
            False for all unencoded comparisons
            True if the original contains no characters that would be encoded
            True if the encoded replacement contains an unencoded hyphen
        """

        if encoding_function.__name__ == "encoding_plain":
            return False

        if encoding_function(original) == original or "-" in encoding_function(replacement):
            self.skip_count += 1
            logging.debug("Skipping comparison of %s to %s under %s", original, replacement, encoding_function.__name__)
            return True

        return False

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

        for encoding_name, encoding_function in host_replace.encoding_functions.items():
            function_output = encoding_function(input_text)
            with self.subTest(encoding_name=encoding_name):
                self.assertEqual(expected_outputs[encoding_name], function_output, msg=f"Encoding error: {input_text} incorrectly results in {function_output} instead of {expected_outputs[encoding_name]} under {encoding_name} encoding.")

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

        with self.subTest(test="Mapping FQDN 'web-1a.example.com' to 'www-1a.example.com'"):
            self.assertEqual(tmp_replacer.replacements_table, expected_replacements_table, msg=f"{host_map} failed to correctly create expected replacements table")

        host_map = {"example": "us-east-1.example.net"}
        tmp_replacer = host_replace.HostnameReplacer(host_map)
        expected_replacements_table = {
            "example": "us-east-1.example.net",
            "&#x65;&#x78;&#x61;&#x6d;&#x70;&#x6c;&#x65;": "&#x75;&#x73;&#x2d;&#x65;&#x61;&#x73;&#x74;&#x2d;&#x31;&#x2e;&#x65;&#x78;&#x61;&#x6d;&#x70;&#x6c;&#x65;&#x2e;&#x6e;&#x65;&#x74;",
            "&#101;&#120;&#97;&#109;&#112;&#108;&#101;": "&#117;&#115;&#45;&#101;&#97;&#115;&#116;&#45;&#49;&#46;&#101;&#120;&#97;&#109;&#112;&#108;&#101;&#46;&#110;&#101;&#116;",
            "%65%78%61%6d%70%6c%65": "%75%73%2d%65%61%73%74%2d%31%2e%65%78%61%6d%70%6c%65%2e%6e%65%74"
        }

        with self.subTest(test="Mapping unqualified hostname 'example' to 'us-east-1.example.net'"):
            self.assertEqual(tmp_replacer.replacements_table, expected_replacements_table, msg=f"{host_map} failed to correctly create expected replacements table")

    def test_delimiters(self):
        """Test every replacement in the table for all encodings with
        a variety of delimiters."""
        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():

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
                            self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_nondelimiters(self):
        """Test every entry in the table for all encodings, with
        a variety of non-delimiting strings. No replacements should be made."""

        alphanumerics = tuple(string.ascii_letters + string.digits)

        for original in self.host_map:
            for encoding_name, encoding_function in host_replace.encoding_functions.items():

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
                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

                for prefix in self.negative_prefixes + alphanumerics:
                    input_text = encoding_function(prefix + original)

                    if input_text in self.host_map:
                        self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")

                    # No change expected
                    expected_output = input_text
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, prefix=prefix, encoding_name=encoding_name):
                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_bad_unicode_bytes(self):
        """Test that invalid UTF-8 bytes do not raise exceptions and that they act as delimiters."""

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                if self.skip(original, replacement, encoding_function):
                    continue

                for bad, reason in self.bad_unicode.items():
                    bad_bytes = bad.encode("latin-1")
                    input_text = bad_bytes + encoding_function(original).encode("utf-8") + bad_bytes
                    expected_output = bad_bytes + encoding_function(replacement).encode("utf-8") + bad_bytes
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, bad_bytes=bad_bytes, encoding_name=encoding_name, reason=reason):
                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} under encoding '{encoding_name}'.")

    def test_bad_unicode_str(self):
        """Test that invalid UTF-8 strings do not raise exceptions and that they act as delimiters."""

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                if self.skip(original, replacement, encoding_function):
                    continue

                for bad, reason in self.bad_unicode.items():
                    input_text = bad + encoding_function(original) + bad
                    expected_output = bad + encoding_function(replacement) + bad
                    actual_output = self.replacer.apply_replacements(input_text)

                    with self.subTest(original=original, encoding_name=encoding_name, reason=reason):
                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} (UTF-8 with {reason}) incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_undefined_subdomain_replacement(self):
        """Test whether an undefined subdomain is replaced."""
        for original in self.host_map:
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                input_text = encoding_function(f"undefined.{original}")
                if input_text in self.host_map:
                    self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")
                expected_output = input_text
                actual_output = self.replacer.apply_replacements(input_text)

                with self.subTest(input_text=input_text, encoding_name=encoding_name):
                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_bare_domain_replacement(self):
        """Test whether a bare second level domain is replaced."""
        for encoding_name, encoding_function in host_replace.encoding_functions.items():
            input_text = encoding_function("example.com")
            if input_text in self.host_map:
                self.fail(f"Invalid test conditions: {input_text} should not be in the host map.")
            expected_output = input_text
            actual_output = self.replacer.apply_replacements(input_text)

            with self.subTest(input_text=input_text, encoding_name=encoding_name):
                self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_url_with_encoded_redirect(self):
        """Test whether an unencoded hostname and an encoded hostname are both replaced correctly."""
        for encoding_name, encoding_function in host_replace.encoding_functions.items():
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
                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

    def test_no_wildcard_dots(self):
        """Test that dots in the hostname are treated as literal dots, not as wildcards."""
        if self.host_map.get("web.example.com") != "www.example.com" or "webxexamplexcom" in self.host_map:
            self.fail("Invalid test conditions: web.example.com must map to www.example.com and webxexamplexcom must not be in host map.")
        input_text = "webxexamplexcom"
        expected_output = input_text
        actual_output = self.replacer.apply_replacements(input_text)

        self.assertEqual(actual_output, expected_output, msg="The '.' character must be escaped so that it's not treated as a wildcard.")

    def test_case_preservation(self):
        """Test basic post-encoding case preservation under simple encodings.

        Note that since encoding is performed first, this compares the
        representation of the encoded strings ("%2e" vs "%2E"), not their
        underlying values ("%41" vs "%61")
        """

        for original, replacement in self.host_map.items():
            for encoding_name, encoding_function in host_replace.encoding_functions.items():
                if self.skip(original, replacement, encoding_function):
                    continue

                # Test str
                input_text = encoding_function(original).upper()

                if not input_text.isupper():
                    continue

                expected_output = encoding_function(replacement).upper()
                actual_output = self.replacer.apply_replacements(input_text)

                with self.subTest(input_text=input_text, encoding_name=encoding_name):
                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output} under {encoding_name} encoding.")

                # Test bytes
                input_text = encoding_function(original).encode("utf-8").upper()
                expected_output = encoding_function(replacement).encode("utf-8").upper()
                actual_output = self.replacer.apply_replacements(input_text)

                with self.subTest(input_text=input_text, encoding_name=encoding_name):
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
                with self.subTest(input_text=input_text):
                    self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output}.")

    def _disabled_test_pre_encoding_case(self):
        """Test cosmetic and functional casing behavior. These tests fail due
        to the absence of pre-encoding case detection."""

        if self.host_map.get("web.example.com") != "www.example.com":
            self.fail("Invalid test conditions: web.example.com must map to www.example.com.")

        for encoding_name, encoding_function in host_replace.encoding_functions.items():
            input_text = encoding_function("WEB.EXAMPLE.COM")
            expected_output = encoding_function("WWW.EXAMPLE.COM")
            actual_output = self.replacer.apply_replacements(input_text)

            decoded_expected_output = urllib.parse.unquote(html.unescape(expected_output))
            decoded_actual_output = urllib.parse.unquote(html.unescape(actual_output))

            if decoded_actual_output != decoded_expected_output:
                if decoded_actual_output.lower() == decoded_expected_output.lower():
                    # Cosmetic failure
                    logging.warning("Case is not preserved under %s encoding: %s results in %s instead of %s", encoding_name, input_text, actual_output, expected_output)
                else:
                    # Functional failure
                    with self.subTest(input_text=input_text, encoding_name=encoding_name):
                        self.assertEqual(actual_output, expected_output, msg=f"{input_text} incorrectly results in {actual_output} instead of {expected_output}.")

if __name__ == "__main__":
    unittest.main()
