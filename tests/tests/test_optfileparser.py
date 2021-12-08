"""Tests for e3.testsuite.optfileparser."""

import os.path

from e3.os.process import Run
from e3.testsuite.optfileparser import BadFormattingError, OptFileParse


def parse_file(filename, tags=None):
    """Parse an optfile in the "optfiles" subdirectory."""
    tags = tags if tags is not None else []
    return OptFileParse(
        tags, os.path.join(os.path.dirname(__file__), "optfiles", filename)
    )


def parse(lines, tags=None):
    """Parse an optfile from its list of lines."""
    tags = tags if tags is not None else []
    return OptFileParse(tags, lines)


def test_in_memory():
    """Check the parsing of an optfile from a list of text lines."""
    of = parse_file("empty.opt")
    of = OptFileParse([], ["ALL"])
    assert of.get_values({}) == {}


def test_empty():
    """Test that parsing an empty file gives the expected values."""
    of = parse_file("empty.opt")
    assert of.get_value("XFAIL") is None
    assert of.get_values({}) == {}
    assert of.get_values({"XFAIL": "yes"}) == {"XFAIL": "yes"}


def test_tags():
    """Test the handling of system tags."""
    of = parse_file("tags.opt", [])
    assert of.get_value("CMD") == "default.cmd"
    assert of.get_value("XFAIL") == ""
    assert of.get_note() == ""
    assert of.get_note("") == []

    of = parse_file("tags.opt", ["linux"])
    assert of.get_value("CMD") == "linux.cmd"
    assert of.get_value("XFAIL") is None

    of = parse_file("tags.opt", ["powerpc"])
    assert of.get_value("CMD") == "default.cmd"
    assert of.get_value("XFAIL") == ""

    of = parse_file("tags.opt", ["linux", "powerpc"])
    assert of.get_value("CMD") == "linux.cmd"
    assert of.get_value("XFAIL") is None

    of = parse_file("tags.opt", ["aix", "powerpc"])
    assert of.get_value("CMD") == "aix.cmd"
    assert of.get_value("XFAIL") == ""

    # Tags can also be encoded as a comma-separated string
    of = parse_file("tags.opt", "vms,alpha")
    assert of.get_value("CMD") == "default.cmd"
    assert of.get_value("XFAIL") == ""


def test_dead():
    """Test the handling of DEAD entries."""
    of = parse_file("dead.opt")
    assert of.is_dead
    assert of.get_value("dead") == "true"
    assert of.get_value("xfail") is None
    assert of.get_note() == ""
    assert str(of) == 'dead="true"'

    of = parse_file("dead.opt", "linux")
    assert not of.is_dead
    assert of.get_value("dead") is None
    assert of.get_value("xfail") == ""
    assert of.get_value("cmd") is None
    assert of.get_note() == "linux"
    assert str(of) == 'xfail=""\nactivating_tag="linux"'

    of = parse_file("dead.opt", "darwin")
    assert not of.is_dead
    assert of.get_value("dead") is None
    assert of.get_value("xfail") == "Indeed!"
    assert of.get_value("cmd") is None
    assert of.get_note() == "darwin"

    of = parse_file("dead.opt", "windows")
    assert not of.is_dead
    assert of.get_value("dead") is None
    assert of.get_value("xfail") is None
    assert of.get_value("cmd") == "windows.cmd"
    assert of.get_note() == "windows"

    of = parse_file("dead.opt", "windows,powerpc")
    assert not of.is_dead
    assert of.get_value("dead") is None
    assert of.get_value("xfail") is None
    assert of.get_value("cmd") == "windows.cmd"
    assert of.get_note() == "windows"

    of = parse_file("dead.opt", "aix")
    assert of.is_dead
    assert of.get_value("dead") == "true"
    assert of.get_value("xfail") is None
    assert of.get_value("cmd") is None
    assert of.get_note() == ""

    of = parse_file("dead.opt", "powerpc,aix")
    assert not of.is_dead
    assert of.get_value("dead") is None
    assert of.get_value("xfail") is None
    assert of.get_value("cmd") == "aix-ppc.cmd"
    assert of.get_note() == "aix,powerpc"
    assert of.get_note("") == ["aix", "powerpc"]


def test_default_cmd():
    """Test the handling of default commands."""
    of = parse_file("default_cmd.opt", "linux")
    assert not of.is_dead

    of = parse_file("default_cmd.opt", "windows")
    assert of.is_dead


def test_syntax_error():
    """Test the handling of syntax errors."""
    try:
        parse_file("syntax_error.opt")
    except BadFormattingError as exc:
        assert str(exc) == "Can not parse line: ? ?\n"
    else:
        raise AssertionError()


def test_required():
    """Test the handling of REQUIRED commands."""
    of = parse_file("required.opt", "linux")
    assert of.is_dead

    of = parse_file("required.opt", "linux,ada")
    assert of.is_dead

    of = parse_file("required.opt", "linux,ada,c")
    assert not of.is_dead


def run_opt_parser_script(filename, tags=None):
    """Call e3-opt-parser and returning the corresponding e3.os.process.Run object."""
    parser_cmd = [
        "e3-opt-parser",
        os.path.join(os.path.dirname(__file__), "optfiles", filename),
    ]
    if tags is not None:
        parser_cmd.extend(tags)
    return Run(parser_cmd)


def test_main():
    """Test the function called by the command-line wrapper to OptFileParse."""
    p = run_opt_parser_script("tags.opt", None)
    assert p.status == 0
    assert (
        p.out
        == """\
cmd="default.cmd"
xfail=""
"""
    )

    p = run_opt_parser_script("tags.opt", ["linux"])
    assert p.status == 0
    assert (
        p.out
        == """\
cmd="linux.cmd"
"""
    )

    p = run_opt_parser_script("tags.opt", ["linux", "powerpc"])
    assert p.status == 0
    assert (
        p.out
        == """\
cmd="linux.cmd"
"""
    )
