"""Comprehensive unit tests for tsconfig and comment-tolerant jsonc parser."""

import json
import pytest

from cbi.jsonc import _jsonc, jsonc_loads, parse_jsonc


def test_aliases():
    """_jsonc and parse_jsonc are aliases to jsonc_loads."""
    assert _jsonc is jsonc_loads
    assert parse_jsonc is jsonc_loads

    sample = '{"key": "value", // comment\n}'
    expected = {"key": "value"}
    assert jsonc_loads(sample) == expected
    assert _jsonc(sample) == expected
    assert parse_jsonc(sample) == expected


def test_line_comments():
    """Line comments (//) at start, end, indented, or standalone are stripped."""
    data = """\
    // Leading comment at line start
    {
        // Indented comment before key
        "name": "cbi", // Comment at line end
        // Consecutive comment line 1
        // Consecutive comment line 2
        "enabled": true,
        //
        "count": 42
        // Trailing comment without newline
    }"""
    assert jsonc_loads(data) == {
        "name": "cbi",
        "enabled": True,
        "count": 42,
    }


def test_block_comments():
    """Block comments (/* ... */) single-line and multi-line are stripped."""
    data = """\
    /* Leading single-line block comment */
    {
        /*
         * Multi-line block comment
         * with asterisks and explanation
         */
        "host": /* inline block comment */ "localhost",
        "port": 8080, /**/
        /*** Decorative block comment ***/
        "active": false
    }
    /* Trailing block comment */
    """
    assert jsonc_loads(data) == {
        "host": "localhost",
        "port": 8080,
        "active": False,
    }


def test_comments_inside_strings():
    """Comment markers inside string literals must be preserved as literal characters."""
    data = """{
        "url": "https://example.com/api/v1",
        "glob": "src/*",
        "mapping": "@lib/*",
        "inline_line": "foo // not a comment bar",
        "inline_block": "foo /* not a comment */ bar",
        "slash_star": "/*",
        "double_slash": "//",
        "closing_block": "*/"
    }"""
    parsed = jsonc_loads(data)
    assert parsed == {
        "url": "https://example.com/api/v1",
        "glob": "src/*",
        "mapping": "@lib/*",
        "inline_line": "foo // not a comment bar",
        "inline_block": "foo /* not a comment */ bar",
        "slash_star": "/*",
        "double_slash": "//",
        "closing_block": "*/",
    }


def test_commas_inside_strings_preserved():
    """Commas preceding braces or brackets inside string literals must not be stripped."""
    data = """{
        "pattern1": "foo,}",
        "pattern2": "bar,]",
        "pattern3": "nested {,} pattern"
    }"""
    assert jsonc_loads(data) == {
        "pattern1": "foo,}",
        "pattern2": "bar,]",
        "pattern3": "nested {,} pattern",
    }


def test_trailing_commas_in_objects():
    """Trailing commas in objects with single or multiple properties are handled."""
    single_key = '{"key": "value",}'
    assert jsonc_loads(single_key) == {"key": "value"}

    multi_key_spaced = """{
        "a": 1,
        "b": "two",
        "c": true ,
    }"""
    assert jsonc_loads(multi_key_spaced) == {"a": 1, "b": "two", "c": True}

    nested_objects = """{
        "outer": {
            "inner": {
                "val": 99,
            },
        },
    }"""
    assert jsonc_loads(nested_objects) == {"outer": {"inner": {"val": 99}}}


def test_trailing_commas_in_arrays():
    """Trailing commas in arrays with single or multiple items are handled."""
    single_item = "[10,]"
    assert jsonc_loads(single_item) == [10]

    multi_items = """[
        "first",
        "second",
        3,
        false,
    ]"""
    assert jsonc_loads(multi_items) == ["first", "second", 3, False]

    nested_arrays = "[[1, 2,], [3, 4,],]"
    assert jsonc_loads(nested_arrays) == [[1, 2], [3, 4]]


def test_complex_tsconfig():
    """Nested tsconfig.json with compilerOptions, paths, comments, and trailing commas."""
    tsconfig = """\
    // tsconfig.json - build configuration
    {
        "compilerOptions": {
            "target": "ES2022", /* Output language level */
            "module": "NodeNext",
            "moduleResolution": "NodeNext",
            "baseUrl": ".",
            // Path aliases for workspace packages
            "paths": {
                "@app/*": ["src/app/*",],
                "@lib/*": [
                    "src/lib/*", // primary library path
                    "src/vendor/*",
                ],
                "/*": ["root/*"],
            },
            "strict": true,
            "skipLibCheck": true,
        },
        "include": [
            "src/**/*",
            "tests/**/*", // test specs
        ],
        "exclude": [
            "node_modules",
            "dist",
        ],
    }
    // End of tsconfig
    """
    parsed = jsonc_loads(tsconfig)
    assert parsed["compilerOptions"]["target"] == "ES2022"
    assert parsed["compilerOptions"]["module"] == "NodeNext"
    assert parsed["compilerOptions"]["paths"]["@app/*"] == ["src/app/*"]
    assert parsed["compilerOptions"]["paths"]["@lib/*"] == [
        "src/lib/*",
        "src/vendor/*",
    ]
    assert parsed["compilerOptions"]["paths"]["/*"] == ["root/*"]
    assert parsed["compilerOptions"]["strict"] is True
    assert parsed["include"] == ["src/**/*", "tests/**/*"]
    assert parsed["exclude"] == ["node_modules", "dist"]


def test_escaped_strings():
    """Escaped quotes and backslashes containing comment sequences or trailing commas."""
    # Escaped quote inside string with //
    data1 = r'{"msg": "with \" escaped quotes and // no comment"}'
    assert jsonc_loads(data1) == {"msg": 'with " escaped quotes and // no comment'}

    # Escaped backslash before quote
    data2 = r'{"path": "C:\\foo\\bar\\", "flag": true,}'
    assert jsonc_loads(data2) == {"path": "C:\\foo\\bar\\", "flag": True}

    # Escaped quote containing block comment syntax
    data3 = r'{"code": "/* not a comment \" */"}'
    assert jsonc_loads(data3) == {"code": '/* not a comment " */'}

    # Standard JSON escape characters
    data4 = r'{"escapes": "\n\t\r\b\f\/\u0041"}'
    assert jsonc_loads(data4) == {"escapes": "\n\t\r\b\f/A"}


def test_primitive_types_and_empty_containers():
    """Primitives and empty structures with comments and whitespace."""
    assert jsonc_loads("/* comment */ 123 // number\n") == 123
    assert jsonc_loads("-42.5") == -42.5
    assert jsonc_loads("1e-4") == 1e-4
    assert jsonc_loads("/* val */ true") is True
    assert jsonc_loads("false // boolean") is False
    assert jsonc_loads("null /* null */") is None
    assert jsonc_loads('"simple string"') == "simple string"

    assert jsonc_loads("{ /* empty object */ }") == {}
    assert jsonc_loads("[ // empty array\n ]") == []


def test_error_cases():
    """Malformed syntax raises json.JSONDecodeError."""
    # Unterminated string
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads('{"key": "unterminated')

    # Unquoted key
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads('{key: "value"}')

    # Double comma in array
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads("[1,, 2]")

    # Double comma in object
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads('{"a": 1,, "b": 2}')

    # Trailing comma without closing container
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads('{"a": 1,')

    # Unclosed block comment resulting in invalid JSON
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads('{"a": /* comment }')

    # Completely invalid tokens
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads("not valid json")

    # Empty string
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads("")

    # Single quotes instead of double quotes
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads("{'a': 1}")

    # Trailing unexpected token
    with pytest.raises(json.JSONDecodeError):
        jsonc_loads('{"a": 1} unexpected')
