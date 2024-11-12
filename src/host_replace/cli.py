"""Entry point for command-line invocation."""
import sys
import argparse
import logging
import json
from .host_replace import HostnameReplacer

def main() -> None:
    """
    Parses command-line arguments and performs hostname replacements in the
    specified input file, writing the results to the output file or stdout.
    """
    parser = argparse.ArgumentParser(description="Replace hostnames and domains based on a provided mapping.")

    parser.add_argument(
        "input", type=argparse.FileType("rb"), nargs="?", default=sys.stdin.buffer,
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
        format="%(levelname)s: %(message)s"
    )

    try:
        with open(args.mapping, "r", encoding="utf-8") as mapping_file:
            host_map = json.load(mapping_file)
    except IOError as e:
        logging.error("Cannot open host map file: %s", e)
        sys.exit(1)
    except (json.decoder.JSONDecodeError, UnicodeDecodeError) as e:
        logging.error("%s is not a valid UTF-8 JSON file: %s", args.mapping, e)
        sys.exit(1)

    try:
        replacer = HostnameReplacer(host_map)
    except ValueError as e:
        logging.error("%s is not a valid host map: %s", args.mapping, e)
        sys.exit(1)

    input_text = args.input.read()
    output_text = replacer.apply_replacements(input_text)

    # Since input_text is bytes, output_text is bytes. We check explicitly for
    # type safety, however
    if isinstance(output_text, bytes):
        if args.output:
            with open(args.output, mode="wb") as outfile:
                outfile.write(output_text)
        else:
            if sys.stdout.isatty():
                try:
                    output_text.decode("utf-8")
                    sys.stdout.buffer.write(output_text)
                except UnicodeDecodeError:
                    logging.warning("Output contains binary data that may corrupt your terminal.")
            else:
                sys.stdout.buffer.write(output_text)

if __name__ == "__main__":
    main()
