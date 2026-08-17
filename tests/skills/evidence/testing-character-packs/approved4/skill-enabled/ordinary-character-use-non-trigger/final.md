The cause is clear. Your file can be valid YAML and still be rejected here, because this parser deliberately accepts only a restricted, data-only YAML subset.

It rejects every alias before constructing the document, so anchors are unusable too—even if expanding them would yield valid YAML. Its custom safe loader also rejects duplicate mapping keys and merge keys; permissive YAML parsers may accept those or silently select a value, but this one refuses the ambiguity. Finally, the top-level value must be a mapping. In pack references, paths must also be relative YAML paths inside the pack and comply with Windows filename rules.

Expand anchors manually, remove aliases and merge keys, ensure every mapping key is unique, and make the root a mapping. If it still fails, send the exact error envelope and the relevant file fragment; then I can identify the specific gate rather than merely the rules it enforces.

Without the rejected file or its error envelope, I can identify the parser's rules, but I will not pretend to know which one your file triggered.