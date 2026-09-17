"""Smoke and contract tests for wc.py.

Run from the project root with either runner:

    python3 -m unittest test_wc
    pytest

The counting engine and the error mapping are exercised in-process by importing
``wc`` directly (no subprocess); the command line contract - streams and exit
codes - is exercised end-to-end in a fresh interpreter. Every subprocess gets an
explicit argument vector with ``shell=False``; no shell string is ever built.
"""

import dataclasses
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import wc

PROJECT_ROOT = Path(wc.__file__).resolve().parent
WC_SCRIPT = Path(wc.__file__).resolve()


def python_command(arguments=()):
    """Return the argument vector that runs wc.py under this interpreter.

    Built as a plain list of concrete strings: nothing is interpolated into a
    shell string, and no dynamic fragment is spread into the command.
    """
    command = [sys.executable, str(WC_SCRIPT)]
    for argument in arguments:
        command.append(argument)
    return command


def run_cli(arguments=(), cwd=None):
    """Run wc.py in a fresh interpreter and return the CompletedProcess (bytes mode)."""
    return subprocess.run(
        python_command(arguments),
        capture_output=True,
        cwd=str(cwd or PROJECT_ROOT),
        shell=False,
    )


def run_cli_in_module_mode(arguments=()):
    """Run the tool as `python -m wc` instead of as a script."""
    command = [sys.executable, "-m", "wc"]
    for argument in arguments:
        command.append(argument)
    return subprocess.run(
        command,
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        shell=False,
    )


def run_inline_python(source):
    """Run one snippet of Python in a fresh interpreter (no shell involved)."""
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        shell=False,
    )


def run_in_process(argv):
    """Call wc.main(argv) and return (status, stdout, stderr) as strings."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = wc.main(list(argv) if argv is not None else None)
    return status, out.getvalue(), err.getvalue()


class CountWordsTests(unittest.TestCase):
    """F1 - the counting engine, imported directly."""

    def test_punctuation_stays_attached_to_its_token(self):
        self.assertEqual(wc.count_words("hello, world!"), 2)

    def test_accented_and_non_latin_words_count(self):
        self.assertEqual(wc.count_words("café naïve 日本語"), 3)

    def test_empty_string_is_zero(self):
        self.assertEqual(wc.count_words(""), 0)

    def test_whitespace_only_string_is_zero(self):
        self.assertEqual(wc.count_words("   \t\n \t  \r\n "), 0)

    def test_final_token_without_trailing_newline_is_counted(self):
        self.assertEqual(wc.count_words("hello"), 1)

    def test_runs_of_whitespace_collapse(self):
        self.assertEqual(wc.count_words("  one\ttwo   three\n\nfour  "), 4)

    def test_multiline_text_counts_every_line(self):
        self.assertEqual(wc.count_words("first line\nsecond line\n"), 4)

    def test_returns_an_int(self):
        self.assertIsInstance(wc.count_words("a b"), int)

    def test_numbers_and_symbols_are_words(self):
        self.assertEqual(wc.count_words("42 x86-64 +3.5 --flag"), 4)


class ReadTextTests(unittest.TestCase):
    """F2 - file input, path validation and UTF-8 decoding."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_utf8_content_verbatim(self):
        target = self.tmp / "notes.txt"
        target.write_bytes("café\n".encode("utf-8"))
        self.assertEqual(wc.read_text(str(target)), "café\n")

    def test_missing_path_reports_no_such_file(self):
        with self.assertRaises(wc.WcError) as caught:
            wc.read_text(str(self.tmp / "absent.txt"))
        self.assertEqual(str(caught.exception), "no such file")

    def test_directory_reports_is_a_directory(self):
        with self.assertRaises(wc.WcError) as caught:
            wc.read_text(str(self.tmp))
        self.assertEqual(str(caught.exception), "is a directory")

    def test_invalid_utf8_reports_not_valid_utf8_text(self):
        target = self.tmp / "binary.dat"
        target.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x01]))
        with self.assertRaises(wc.WcError) as caught:
            wc.read_text(str(target))
        self.assertEqual(str(caught.exception), "not valid UTF-8 text")

    def test_permission_error_maps_to_permission_denied(self):
        denied = PermissionError(13, "Permission denied")
        with mock.patch.object(wc, "_read_bytes", side_effect=denied):
            with self.assertRaises(wc.WcError) as caught:
                wc.read_text("locked.txt")
        self.assertEqual(str(caught.exception), "permission denied")

    def test_other_os_errors_use_their_strerror(self):
        failure = OSError(5, "Input/output error")
        with mock.patch.object(wc, "_read_bytes", side_effect=failure):
            with self.assertRaises(wc.WcError) as caught:
                wc.read_text("broken.txt")
        self.assertEqual(str(caught.exception), "Input/output error")

    def test_os_error_without_strerror_still_gets_a_reason(self):
        with mock.patch.object(wc, "_read_bytes", side_effect=OSError()):
            with self.assertRaises(wc.WcError) as caught:
                wc.read_text("broken.txt")
        self.assertEqual(str(caught.exception), "cannot be read")

    def test_read_text_raises_only_wc_error(self):
        with self.assertRaises(wc.WcError) as caught:
            wc.read_text(str(self.tmp / "absent.txt"))
        self.assertIsInstance(caught.exception, Exception)


class CountResultTests(unittest.TestCase):
    """The CountResult model and the counting path that produces it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_the_model_carries_the_path_and_the_word_count(self):
        result = wc.CountResult(path="notes.txt", words=41)
        self.assertEqual(result.path, "notes.txt")
        self.assertEqual(result.words, 41)

    def test_the_model_is_immutable(self):
        result = wc.CountResult(path="notes.txt", words=41)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.words = 0

    def test_line_is_the_bare_integer_and_one_newline(self):
        self.assertEqual(wc.CountResult(path="a.txt", words=3).line, "3\n")
        self.assertEqual(wc.CountResult(path="a.txt", words=0).line, "0\n")

    def test_count_file_reads_the_path_and_counts_it(self):
        target = self.tmp / "notes.txt"
        target.write_bytes(b"one two three\n")
        result = wc.count_file(str(target))
        self.assertIsInstance(result, wc.CountResult)
        self.assertEqual(result.path, str(target))
        self.assertEqual(result.words, 3)
        self.assertEqual(result.line, "3\n")

    def test_count_file_keeps_the_path_exactly_as_given(self):
        (self.tmp / "words.txt").write_bytes(b"alpha beta\n")
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.tmp)
        result = wc.count_file("words.txt")
        self.assertEqual(result.path, "words.txt")
        self.assertEqual(result.words, 2)

    def test_count_file_reports_the_same_reasons_as_read_text(self):
        with self.assertRaises(wc.WcError) as caught:
            wc.count_file(str(self.tmp / "absent.txt"))
        self.assertEqual(str(caught.exception), "no such file")

        with self.assertRaises(wc.WcError) as caught:
            wc.count_file(str(self.tmp))
        self.assertEqual(str(caught.exception), "is a directory")

        binary = self.tmp / "binary.dat"
        binary.write_bytes(bytes([0xFF, 0xFE]))
        with self.assertRaises(wc.WcError) as caught:
            wc.count_file(str(binary))
        self.assertEqual(str(caught.exception), "not valid UTF-8 text")

    def test_main_prints_exactly_the_model_line(self):
        target = self.tmp / "words.txt"
        target.write_bytes(b"one two three\n")
        status, out, _ = run_in_process([str(target)])
        self.assertEqual(status, 0)
        self.assertEqual(out, wc.count_file(str(target)).line)

    def test_main_prints_the_model_line_for_a_zero_word_file(self):
        target = self.tmp / "empty.txt"
        target.write_bytes(b" \t\n ")
        status, out, _ = run_in_process([str(target)])
        self.assertEqual(status, 0)
        self.assertEqual(out, wc.count_file(str(target)).line)
        self.assertEqual(out, "0\n")


class CliFixtureMixin:
    """Builds the sample files the command line tests need."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, payload):
        target = self.tmp / name
        target.write_bytes(payload)
        return target


class CliSuccessTests(CliFixtureMixin, unittest.TestCase):
    """F4 - clean stdout contract on the success path."""

    def test_counts_words_in_a_file(self):
        target = self.write("words.txt", b"one two three\n")
        result = run_cli([str(target)])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"3\n")
        self.assertEqual(result.stderr, b"")

    def test_stdout_is_exactly_the_bare_integer_line(self):
        target = self.write("sample.txt", b"hello, world!")
        self.assertEqual(run_cli([str(target)]).stdout, b"2\n")

    def test_punctuation_only_file_counts_one_word(self):
        target = self.write("punct.txt", b"hello,\n")
        self.assertEqual(run_cli([str(target)]).stdout, b"1\n")

    def test_empty_file_prints_zero(self):
        target = self.write("empty.txt", b"")
        result = run_cli([str(target)])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"0\n")
        self.assertEqual(result.stderr, b"")

    def test_whitespace_only_file_prints_zero(self):
        target = self.write("blank.txt", b" \t\n  \r\n ")
        self.assertEqual(run_cli([str(target)]).stdout, b"0\n")

    def test_unterminated_final_line_is_included(self):
        target = self.write("ragged.txt", b"first line\nsecond line")
        self.assertEqual(run_cli([str(target)]).stdout, b"4\n")

    def test_utf8_file_counts_accented_and_non_latin_words(self):
        target = self.write("unicode.txt", "café naïve 日本語\n".encode("utf-8"))
        self.assertEqual(run_cli([str(target)]).stdout, b"3\n")

    def test_output_composes_when_captured_separately(self):
        target = self.write("words.txt", b"one two three\n")
        piped = subprocess.run(
            [sys.executable, str(WC_SCRIPT), str(target)],
            capture_output=True,
            shell=False,
        )
        self.assertEqual(piped.returncode, 0)
        self.assertEqual(piped.stdout.decode("utf-8").splitlines(), ["3"])

    def test_module_invocation_matches_the_script_invocation(self):
        target = self.write("words.txt", b"alpha beta\n")
        script = run_cli([str(target)])
        module = run_cli_in_module_mode([str(target)])
        self.assertEqual(module.returncode, 0)
        self.assertEqual(module.stdout, script.stdout)


class CliErrorTests(CliFixtureMixin, unittest.TestCase):
    """F2/F3 - one stderr line, empty stdout, honest exit status."""

    def test_missing_file_reports_one_line_and_exits_one(self):
        result = run_cli(["missing.txt"], cwd=self.tmp)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"wc.py: missing.txt: no such file\n")

    def test_error_message_echoes_the_exact_path_typed(self):
        result = run_cli(["./missing.txt"], cwd=self.tmp)
        self.assertEqual(result.stderr, b"wc.py: ./missing.txt: no such file\n")

    def test_directory_argument_reports_is_a_directory(self):
        directory = self.tmp / "docs"
        directory.mkdir()
        result = run_cli([str(directory)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, f"wc.py: {directory}: is a directory\n".encode("utf-8"))

    def test_directory_argument_relative_path(self):
        (self.tmp / "docs").mkdir()
        result = run_cli(["docs"], cwd=self.tmp)
        self.assertEqual(result.stderr, b"wc.py: docs: is a directory\n")

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root can read a mode-000 file, so the denial cannot be provoked",
    )
    def test_unreadable_file_reports_permission_denied(self):
        target = self.write("locked.txt", b"secret words\n")
        target.chmod(0o000)
        self.addCleanup(target.chmod, 0o600)
        result = run_cli([str(target)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, f"wc.py: {target}: permission denied\n".encode("utf-8"))

    def test_non_utf8_file_reports_not_valid_utf8_text(self):
        target = self.write("binary.dat", bytes([0xFF, 0xFE, 0x00, 0x01]))
        result = run_cli([str(target)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, f"wc.py: {target}: not valid UTF-8 text\n".encode("utf-8"))

    def test_every_path_failure_keeps_stdout_empty(self):
        binary = self.write("binary.dat", bytes([0xC3, 0x28]))
        failures = [
            (["missing.txt"], self.tmp),
            ([str(self.tmp)], None),
            ([str(binary)], None),
        ]
        for arguments, cwd in failures:
            with self.subTest(arguments=arguments):
                result = run_cli(arguments, cwd=cwd)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr.count(b"\n"), 1)
                self.assertNotIn(b"Traceback", result.stderr)


class HelpAndUsageTests(unittest.TestCase):
    """F3 - help on stdout, misuse on stderr, exit statuses 0 and 2."""

    def test_short_help_goes_to_stdout_and_exits_zero(self):
        result = run_cli(["-h"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertIn(b"usage: wc.py", result.stdout)
        self.assertIn(b"Count the whitespace-separated words in a UTF-8 text file.", result.stdout)
        self.assertIn(b"<path>", result.stdout)

    def test_long_help_matches_short_help(self):
        self.assertEqual(run_cli(["--help"]).stdout, run_cli(["-h"]).stdout)
        self.assertEqual(run_cli(["--help"]).returncode, 0)

    def test_no_arguments_is_a_usage_error_on_stderr(self):
        result = run_cli([])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage: wc.py", result.stderr)
        self.assertIn(b"required: <path>", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_unknown_option_is_a_usage_error_on_stderr(self):
        result = run_cli(["--bogus"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage: wc.py", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_unknown_option_with_a_path_names_the_option(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name) / "words.txt"
        target.write_bytes(b"one two\n")
        result = run_cli(["--bogus", str(target)])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"unrecognized arguments: --bogus", result.stderr)

    def test_help_mentions_the_exit_statuses(self):
        stdout = run_cli(["--help"]).stdout.decode("utf-8")
        self.assertIn("exit status", stdout)
        self.assertIn("1  the path could not be read as UTF-8 text", stdout)
        self.assertIn("2  the command line was malformed", stdout)


class MainFunctionTests(CliFixtureMixin, unittest.TestCase):
    """D4 - main(argv) returns the status instead of exiting, so it is testable."""

    def test_success_returns_zero_and_writes_the_bare_count(self):
        target = self.write("words.txt", b"one two three\n")
        status, out, err = run_in_process([str(target)])
        self.assertEqual(status, 0)
        self.assertEqual(out, "3\n")
        self.assertEqual(err, "")

    def test_help_returns_zero_on_stdout(self):
        status, out, err = run_in_process(["--help"])
        self.assertEqual(status, 0)
        self.assertIn("usage: wc.py", out)
        self.assertEqual(err, "")

    def test_no_arguments_returns_two_with_empty_stdout(self):
        status, out, err = run_in_process([])
        self.assertEqual(status, 2)
        self.assertEqual(out, "")
        self.assertIn("usage: wc.py", err)

    def test_unknown_option_returns_two_with_empty_stdout(self):
        status, out, err = run_in_process(["--nope"])
        self.assertEqual(status, 2)
        self.assertEqual(out, "")
        self.assertIn("usage: wc.py", err)

    def test_missing_file_returns_one_with_one_stderr_line(self):
        status, out, err = run_in_process(["missing.txt"])
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "wc.py: missing.txt: no such file\n")

    def test_main_accepts_no_argument_and_reads_the_real_argv(self):
        target = self.write("words.txt", b"alpha beta gamma\n")
        with mock.patch.object(sys, "argv", ["wc.py", str(target)]):
            status, out, _ = run_in_process(None)
        self.assertEqual((status, out), (0, "3\n"))


class DeliveryTests(unittest.TestCase):
    """The non-functionals: one shipped source file, silent, importable."""

    def test_the_product_is_a_single_source_file(self):
        shipped = sorted(
            entry.name
            for entry in PROJECT_ROOT.iterdir()
            if entry.name.endswith(".py") and not entry.name.startswith("test_")
        )
        self.assertEqual(shipped, ["wc.py"])
        self.assertEqual(WC_SCRIPT.name, "wc.py")

    def test_importing_the_module_prints_nothing_and_exits_zero(self):
        result = run_inline_python("import wc")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_the_engine_is_usable_from_an_import(self):
        result = run_inline_python("import wc; print(wc.count_words('a b c'))")
        self.assertEqual(result.stdout, b"3\n")

    def test_the_module_is_importable_by_name_from_its_own_directory(self):
        result = run_cli_in_module_mode(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"usage: wc.py", result.stdout)


class DesignDirectionTests(unittest.TestCase):
    """The committed design direction is present, exact, and cannot drift."""

    COMMITTED_PALETTE = {
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

    COMMITTED_IMPORT = (
        "@import url('https://fonts.googleapis.com/css2?"
        "family=Caveat:wght@400;700&family=Karla:wght@400;500;700&display=swap');"
    )

    def test_the_committed_accent_is_present(self):
        self.assertEqual(wc.DESIGN_TOKENS["accent"], "#5863d3")
        self.assertIn("--accent: #5863d3;", wc.design_css())

    def test_the_full_committed_palette_is_committed_verbatim(self):
        self.assertEqual(wc.DESIGN_TOKENS, self.COMMITTED_PALETTE)
        css = wc.design_css()
        for name, value in self.COMMITTED_PALETTE.items():
            with self.subTest(token=name):
                self.assertIn(f"--{name}: {value};", css)

    def test_surface_tokens_named_by_the_direction_are_declared(self):
        css = wc.design_css()
        for declaration in (
            "--background: #f8faff;",
            "--foreground: #10121c;",
            "--border: #dcdee5;",
            "--card: #feffff;",
            "--muted-foreground: #60636f;",
        ):
            self.assertIn(declaration, css)

    def test_the_token_block_is_a_root_custom_property_block(self):
        css = wc.design_css()
        self.assertIn(":root {", css)
        self.assertTrue(css.rstrip().endswith("}"))
        self.assertEqual(css.count("{"), css.count("}"))

    def test_the_committed_fonts_are_loaded(self):
        self.assertEqual(wc.FONT_HEADING, "Caveat")
        self.assertEqual(wc.FONT_BODY, "Karla")
        self.assertEqual(wc.FONT_IMPORT, self.COMMITTED_IMPORT)
        self.assertTrue(wc.design_css().startswith(wc.FONT_IMPORT))
        self.assertIn("family=Caveat:wght@400;700", wc.design_css())
        self.assertIn("family=Karla:wght@400;500;700", wc.design_css())

    def test_the_fonts_are_bound_to_the_heading_and_body_tokens(self):
        css = wc.design_css()
        self.assertIn('--font-heading: "Caveat", sans-serif;', css)
        self.assertIn('--font-body: "Karla", sans-serif;', css)

    def test_no_stock_default_font_is_shipped_as_the_ui_face(self):
        css = wc.design_css().lower()
        for stock in ("inter", "roboto", "system-ui", "-apple-system", "helvetica", "arial"):
            with self.subTest(font=stock):
                self.assertNotIn(stock, css)

    def test_the_accent_has_its_oklch_and_hex_forms(self):
        self.assertIn("--accent-oklch: oklch(0.55 0.17 275);", wc.design_css())
        self.assertEqual(wc.DESIGN_TOKENS["accent"], "#5863d3")

    def test_one_accent_hue_carries_the_direction(self):
        # The focus ring and the accent are the same committed hue;
        # --on-accent is the readable text colour on top of it, not a second
        # accent, so exactly one accent hue is shipped.
        self.assertEqual(wc.DESIGN_TOKENS["accent"], "#5863d3")
        self.assertEqual(wc.DESIGN_TOKENS["ring"], wc.DESIGN_TOKENS["accent"])
        self.assertEqual(wc.DESIGN_TOKENS["on-accent"], "#ffffff")


if __name__ == "__main__":
    unittest.main()
