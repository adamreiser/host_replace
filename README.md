# Host Replace

A Python package for replacing host and domain names in text under common encoding schemes.

## Features

- Replace hostnames in text under common encodings (URL, HTML entity) while avoiding partial matches
- Replacements are encoded in the same way
- Supports UTF-8 string and byte inputs
- Supports unqualified hostnames and IPv4 addresses
- Partial support for case preservation

See `sample.txt` for detailed examples.

## Installation

```bash
pip install hostreplace
```

## Usage

### CLI

```
usage: hostreplace [-h] [-o OUTPUT] -m MAPPING [-v] [input]

Replace hostnames and domains based on a provided mapping.

positional arguments:
  input                 input file to read from. If not provided, read from stdin

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        output file to write the replaced content. If not provided, write to stdout
  -m MAPPING, --mapping MAPPING
                        JSON file that contains the host mapping dictionary (e.g., {"web.example.com": "www.example.net"})
  -v, --verbose         display the replacements made
```

### API
`host_map`: dict of str:str mappings
`input_text`: str or bytes

```
replacer = HostnameReplacer(host_map)
output_text = replacer.apply_replacements(input_text)
```

## Limitations

- Does not detect encoded uppercase characters. This typically occurs only when an entire hostname (not just the special characters) is URL or entity encoded.

- Preserving the case of individual characters is not supported. For example, if we were mapping "WWW.example.com" to "example.org", would we capitalize anything?

- Similar ambiguity applies to post-encoding casing (e.g., "%2F" vs "%2f"; "&#x2f" vs "&#X2f"), which can lead to inconsistent representation.

- Does not process binary data beyond searching for exact byte sequences. Encodings that are not straight character-to-sequence translations (such as base64) are not supported.

- Hostnames beginning with a hex code are ambiguous when preceded by "%". For example, should "%00example.com" match "example.com" or "00example.com"?

- International domains have not been tested.

- IPv6 is not supported.
