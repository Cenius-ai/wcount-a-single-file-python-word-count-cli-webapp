#!/usr/bin/env python3
"""wc.py - print the number of whitespace-separated words in a UTF-8 text file.

wc.py is the single shipped source file: the counting engine and the command
line interface live here, its test suite ships beside it in test_wc.py and the
contract is written up in README.md. Copy wc.py onto any machine with
Python 3.9+ and run it - no virtualenv, no requirements file, no build step, no
configuration file, no environment variables, no state, no network.

Shape
-----
Three small pieces and one value object: :func:`count_words` is the pure engine,
:func:`read_text` validates the path and decodes UTF-8, and :func:`count_file`
composes them into a :class:`CountResult` - the path exactly as the caller gave
it plus the word count - which :func:`main` renders to stdout via
``CountResult.line``. The model carries no state and touches no disk: it is the
one value that crosses from "a file was read" to "a line was printed".

Quickstart
----------
    $ printf 'one two three\\n' > /tmp/words.txt
    $ python3 wc.py /tmp/words.txt
    3
    $ printf 'hello, world!' | ...   # wc.py reads a file, not stdin
    $ python3 wc.py --help

Usage
-----
    wc.py [-h] <path>

    <path>      one positional path, resolved against the current working
                directory; read as bytes and decoded as UTF-8
    -h, --help  usage, the exit-status reference and an example on stdout, exit 0

    `python3 -m wc <path>` is the same command when module invocation is wanted.

Word definition (the documented contract)
-----------------------------------------
Words are the runs of non-whitespace characters produced by Python's
``str.split()``:

  * repeated spaces, tabs and newlines collapse into a single separator
  * leading and trailing whitespace is ignored
  * punctuation stays attached to its token, so ``hello,`` is one word
  * accented Latin and non-Latin scripts count as words (``café``, ``日本語``)
  * a final token with no trailing newline is still counted

Output contract
---------------
Success writes exactly one line to stdout: the decimal integer followed by a
single newline - no label, no padding, no progress text, no trailing blank
line, so ``python3 wc.py f.txt | ...`` composes. A zero-word file prints ``0``
rather than nothing. Every failure leaves stdout completely empty and reports
on stderr only.

Exit statuses
-------------
    0   success - the count was written to stdout
    1   the path could not be read as UTF-8 text (`wc.py: <path>: <reason>`)
    2   the command line was malformed (usage is shown on stderr)

Error message shape
-------------------
    wc.py: <path>: no such file
    wc.py: <path>: is a directory
    wc.py: <path>: permission denied
    wc.py: <path>: not valid UTF-8 text

The message echoes the exact path string that was typed, and a Python traceback
never reaches the terminal.

Self-tests
----------
    $ python3 -m unittest test_wc    # standard library runner, nothing to install
    $ pytest                         # the same suite, if pytest is available

The suite in test_wc.py covers the engine's edge cases, the path/encoding error
mapping, the byte-exact stdout contract and the exit status of every surface,
and it generates its own fixtures in temporary directories. Keeping the tests
out of this file is deliberate: wc.py stays the one shipped source file.

Design source of truth (the committed direction)
--------------------------------------------------
This build commits one design direction. It is recorded here because this file
is the whole deliverable: "Paper & Ink" - a reading-machine calm, warm paper
surface with near-black ink text and structure from typography and 1px ink
rules alone (no coloured cards, no shadows, one weight of rule line) - paired
with the Caveat / Karla type set ("Caveat Notebook": oversized handwritten
headings over a humanist body face).

``design_css()`` emits the stylesheet that is the source of truth for every
surface of this product: the Google Fonts ``@import`` for Caveat + Karla first,
then the ``:root`` custom-property block carrying the full committed palette
and the heading/body font bindings. ``DESIGN_TOKENS`` exposes the same palette
programmatically, and the test suite pins both, so the direction cannot drift.

wc.py itself is a terminal program with no visual surface - its stdout is
contractually one bare integer, so nothing here is styled at runtime. The
tokens and fonts are still committed verbatim rather than improvised: no second
palette, no stock default font stack, no substituted accent.

Non-goals (named, so nothing looks silently dropped)
----------------------------------------------------
    * reading from stdin, multiple paths, globs, recursive directory walks
    * GNU wc(1) parity flags (-c, -l, -w) and column-aligned output
    * locale-aware, Unicode-boundary or CJK segmentation, stemming, hyphenation
    * non-UTF-8 encodings (latin-1, UTF-16) and BOM stripping
    * --version, subcommands, shell completion, a man page
    * packaging, distribution, Docker, CI configuration
    * any GUI, web or HTTP surface, config files, environment variables or
      credentials
    * concurrency, streaming reads for multi-gigabyte inputs, plugins
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Design source of truth - the committed direction for this product.
#
# Palette committed verbatim (accent #5863d3; its oklch twin seeds CSS ramps
# and is what any chart/canvas/native theming would receive). Type committed as
# the Caveat + Karla pair, loaded through the Google Fonts @import and bound to
# the heading/body font tokens. Nothing else styles this product.
# ---------------------------------------------------------------------------

DESIGN_TOKENS = {
    "card": "#feffff",
    "ring": "#5863d3",
    "muted": "#ebecf4",
    "accent": "#5863d3",
    "border": "#dcdee5",
    "primary": "#1b1e2e",
    "on-accent": "#ffffff",
    "secondary": "#ebecf4",
    "background": "#f8faff",
    "foreground": "#10121c",
    "on-primary": "#ffffff",
    "destructive": "#c9302d",
    "on-secondary": "#10121c",
    "on-destructive": "#ffffff",
    "card-foreground": "#10121c",
    "muted-foreground": "#60636f",
}

# Hex twin of the accent for APIs that cannot parse oklch() (charts, canvas,
# native theming); the oklch form is what the CSS ramps use.
ACCENT_OKLCH = "oklch(0.55 0.17 275)"

FONT_HEADING = "Caveat"
FONT_BODY = "Karla"
FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=Caveat:wght@400;700&family=Karla:wght@400;500;700&display=swap');"


def design_css() -> str:
    """Return the committed stylesheet: the font import, then the token block.

    Every surface of this product consumes these declarations; the token values
    come from :data:`DESIGN_TOKENS`, so the palette has exactly one definition.
    """
    properties = "\n".join(
        f"  --{name}: {value};" for name, value in DESIGN_TOKENS.items()
    )
    return (
        f"{FONT_IMPORT}\n"
        "\n"
        ":root {\n"
        f"{properties}\n"
        f"  --accent-oklch: {ACCENT_OKLCH};\n"
        f'  --font-heading: "{FONT_HEADING}", sans-serif;\n'
        f'  --font-body: "{FONT_BODY}", sans-serif;\n'
        "}\n"
    )

PROG = "wc.py"

DESCRIPTION = "Count the whitespace-separated words in a UTF-8 text file."

EPILOG = """\
exit status:
  0  success - the count was written to stdout
  1  the path could not be read as UTF-8 text (message on stderr)
  2  the command line was malformed (usage is shown above)

examples:
  python wc.py notes.txt          print the number of words in notes.txt
  python wc.py notes.txt | ...    stdout carries the bare count and nothing else
"""


class WcError(Exception):
    """A path, read or decoding failure worth reporting as one short line."""


def count_words(text: str) -> int:
    """Return the number of whitespace-separated words in ``text``.

    Runs of whitespace collapse into a single separator, leading and trailing
    whitespace is ignored, punctuation stays attached to its token and a final
    token that has no trailing newline is still counted.
    """
    return len(text.split())


def _read_bytes(path: str) -> bytes:
    """Read ``path`` as raw bytes.

    Kept separate from :func:`read_text` so the OS error mapping can be
    exercised in tests without depending on file permissions.
    """
    return Path(path).read_bytes()


def read_text(path: str) -> str:
    """Return the contents of ``path`` decoded as UTF-8.

    Raises :class:`WcError` with a short reason when the path is missing, is a
    directory, cannot be read or does not hold valid UTF-8 text; ``main()``
    turns that into the single stderr line and exit status 1.
    """
    try:
        data = _read_bytes(path)
    except FileNotFoundError:
        raise WcError("no such file") from None
    except IsADirectoryError:
        raise WcError("is a directory") from None
    except PermissionError:
        raise WcError("permission denied") from None
    except OSError as error:
        raise WcError(error.strerror or "cannot be read") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise WcError("not valid UTF-8 text") from None


@dataclass(frozen=True)
class CountResult:
    """The outcome of counting one file: the path and its word count.

    ``path`` is the path string exactly as the caller supplied it, so a report
    or an error message can echo what the user typed; ``words`` is the plain
    integer produced by :func:`count_words`.
    """

    path: str
    words: int

    @property
    def line(self) -> str:
        """The stdout representation: the bare decimal integer and one newline."""
        return f"{self.words}\n"


def count_file(path: str) -> CountResult:
    """Read ``path`` as UTF-8 text and return its :class:`CountResult`.

    Raises :class:`WcError`, with the same reasons as :func:`read_text`, when the
    path is missing, is a directory, cannot be read or is not valid UTF-8 text.
    """
    return CountResult(path=path, words=count_words(read_text(path)))


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser that defines the command line contract."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        metavar="<path>",
        help="UTF-8 text file whose words should be counted",
    )
    return parser


def main(argv=None) -> int:
    """Run the CLI for ``argv`` (default: the real command line) and return its exit status."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_signal:
        # argparse has already written help to stdout or usage to stderr.
        code = exit_signal.code
        return code if isinstance(code, int) else 2

    try:
        result = count_file(args.path)
    except WcError as error:
        print(f"{PROG}: {args.path}: {error}", file=sys.stderr)
        return 1

    sys.stdout.write(result.line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
