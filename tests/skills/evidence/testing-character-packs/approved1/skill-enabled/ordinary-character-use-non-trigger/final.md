The cause is clear: your YAML may be valid, but this parser intentionally rejects YAML aliases and anchors (`&name` / `*name`). Expand those values inline instead.

It also requires a mapping at the document root and rejects duplicate keys.