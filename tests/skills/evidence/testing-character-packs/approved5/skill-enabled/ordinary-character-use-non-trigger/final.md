The cause is clear. Your file can be valid JSON and still be rejected by this parser, because it applies stricter safety rules.

It refuses duplicate object keys rather than silently keeping one value. It also refuses non-finite numeric constants such as NaN and Infinity, and it rejects input paths that point through links, junctions, or hard links. Those conditions produce INPUT_INVALID_JSON or INPUT_PATH_UNSAFE.

The strictness is intentional: a permissive reader can let two components see different effective values. Check for repeated keys and non-finite numbers, then supply the real regular file path rather than an indirection.

A generic JSON validator may still say the file is valid; that only means it meets JSON syntax, not this parser’s application-level safety contract.