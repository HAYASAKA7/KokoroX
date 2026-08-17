The cause is clear. Your file can be valid YAML and still be rejected here: the parser intentionally accepts only a restricted YAML subset.

It refuses YAML aliases, including values referenced with `*name`, before ordinary loading. It also refuses merge keys such as `<<: *defaults`. Those features can hide sharing or expand data indirectly, so this parser requires every value and mapping to be explicit.

Inline the referenced values and write the full mapping directly; then retry without aliases or merge keys.

If neither construct appears in your file, I would need the exact parser error or the relevant snippet before naming the specific trigger.