from __future__ import annotations

import sys

from doc_extractor.cli import main as cli_main


def main() -> int:
    arguments = sys.argv[1:]
    if not arguments or any(
        argument == "--smoke-test"
        or argument == "--smoke-test-timeout"
        or argument.startswith("--smoke-test-timeout=")
        for argument in arguments
    ):
        from doc_extractor.app import main as gui_main

        return gui_main(arguments)
    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
