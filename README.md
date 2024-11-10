# Host Replace

A Python package for replacing host and domain names in text under common encoding schemes.

## Features

- Replace hostnames in text under common encodings (URL, HTML entity) while avoiding partial matches.
- Replacements maintain the same encoding as the original text.
- Provides both a CLI interface and importable module.
- Supports both UTF-8 string and byte inputs.
- Supports FQDNS, second level domains, unqualified hostnames, and IPv4 addresses.

## Installation

Install with pip: `pip install host-replace`

Install from source:
```
git clone https://github.com/adamreiser/host_replace
cd host-replace
pip install -e .
```

You can also simply run `host_replace.py` if you have the dependencies in `requirements.txt` installed.

## Usage

### Command-line interface

Transform the following text file using the provided mapping: `host-replace -m mappings.json sample.txt --verbose`

```sample.txt
1. https://web.example.com/path/to/resource?query=param
2. <a href="https&#x3a;&#x2f;&#x2f;boards&#x2e;example&#x2e;com&#x2f;thread&#x2f;123">Discussion Board</a>
3. Redirecting to https%3A%2F%2Fen.us.wiki.example.com%2Fwelcome
4. https://web-1a.example.com/redirect?q=%65%6e%2e%75%73%2e%77%69%6b%69%2e%65%78%61%6d%70%6c%65%2e%63%6f%6d
5. <meta http-equiv="refresh" content="0; url=https%3A%2F%2Fweb.example.com%2Fhome">
6. Our domain is still example.com and archived wiki will remain at archive.en.us.wiki.example.com.
```

```mappings.json
{
    "web.example.com": "www.example.com",
    "web-1a.example.com": "www-1a.example.com",
    "boards.example.com": "forums.en.us.example.com",
    "en.us.wiki.example.com": "wiki.example.com",
    "us.example.com": "us-east-1.example.net",
    "example.net": "example.org",
    "images.example.com": "cdn.example.org"
}
```

Output:
```
INFO: Replacing web.example.com with www.example.com at offset 11
INFO: Replacing boards&#x2e;example&#x2e;com with forums&#x2e;en&#x2e;us&#x2e;example&#x2e;com at offset 91
INFO: Replacing en.us.wiki.example.com with wiki.example.com at offset 195
INFO: Replacing web-1a.example.com with www-1a.example.com at offset 239
INFO: Replacing %65%6e%2e%75%73%2e%77%69%6b%69%2e%65%78%61%6d%70%6c%65%2e%63%6f%6d with %77%69%6b%69%2e%65%78%61%6d%70%6c%65%2e%63%6f%6d at offset 269
INFO: Replacing web.example.com with www.example.com at offset 396
1. https://www.example.com/path/to/resource?query=param
2. <a href="https&#x3a;&#x2f;&#x2f;forums&#x2e;en&#x2e;us&#x2e;example&#x2e;com&#x2f;thread&#x2f;123">Discussion Board</a>
3. Redirecting to https%3A%2F%2Fwiki.example.com%2Fwelcome
4. https://www-1a.example.com/redirect?q=%77%69%6b%69%2e%65%78%61%6d%70%6c%65%2e%63%6f%6d
5. <meta http-equiv="refresh" content="0; url=https%3A%2F%2Fwww.example.com%2Fhome">
6. Our domain is still example.com and archived wiki will remain at archive.en.us.wiki.example.com.
```

### API

To use the module in your Python application:

```python3
import host_replace

host_map = {
    "web.example.com": "www.example.com",
    "boards.example.com": "forums.example.net"
}

replacer = host_replace.HostnameReplacer(host_map)

# Input text (str or bytes)
input_text = "Visit us at https://web.example.com or leave a comment at https://boards.example.com."

# Apply replacements
output_text = replacer.apply_replacements(input_text)

print(output_text)
# Output: Visit us at https://www.example.com or leave a comment at https://forums.example.net.
```

## Limitations

- Does not detect encoded uppercase characters. This is generally rare and occurs when an entire hostname is URL or entity encoded with uppercase letters.

- Full case preservation of individual characters is not supported due to its inherent ambiguity. For example, when mapping `WWW.example.com` to `example.org`, it's unclear which if any letters should be capitalized.

- Variations in encoding representation (e.g., "%2F" vs "%2f"; "&#x2f" vs "&#X2f") can lead to inconsistent outputs.

- Does not process binary data beyond exact byte sequence matching. Encodings like base64 are not supported.

- Hostnames starting with hex codes can be ambiguous when preceded by %. For instance, `%00example.com` could be interpreted as `example.com` or `00example.com`.

- Hostnames beginning with a hex code are ambiguous when preceded by "%". For example, should "%00example.com" match "example.com" or "00example.com"?

- Support for Internationalized Domain Names (IDNs) is not thoroughly tested and may not function as expected.

- The module does not currently support IPv6 address replacements.
