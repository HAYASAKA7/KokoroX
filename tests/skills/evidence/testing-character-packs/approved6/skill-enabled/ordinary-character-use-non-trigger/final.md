The rejection is caused by the parser's stricter safety contract, not by ordinary JSON syntax alone.

It rejects duplicate object keys even though many JSON parsers silently retain the last value. It also rejects non-finite numeric tokens such as NaN and Infinity, invalid UTF-8, non-regular or linked files, oversized inputs, and JSON nesting deeper than 64 levels.

Check the file for repeated keys and non-finite number tokens first; then ensure it is a regular UTF-8 file within the size and nesting limits.

No input file or parser error was supplied, so the specific failing condition cannot be identified with certainty.