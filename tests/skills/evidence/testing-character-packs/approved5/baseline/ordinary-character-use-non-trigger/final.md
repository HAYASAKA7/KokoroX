The cause is clear: this is not a general YAML parser. It accepts a deliberately narrow, data-only subset, and it requires the document root to be a mapping.

So a file may be valid YAML and still be rejected here. The extra exclusions are aliases, merge keys, duplicate mapping keys, invalid UTF-8, and list or scalar roots. Referenced files are narrowed further: only pack-relative .yaml or .yml paths are accepted; absolute paths, parent traversal, backslashes, drive prefixes, reserved Windows names, and unsafe filesystem entries are rejected.

Check those first. If none apply, send the sanitized error plus the smallest reproducible file, and I can identify the precise rule instead of guessing.

Without the file or its error output, naming one specific cause would be a guess.