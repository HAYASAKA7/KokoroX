The cause is clear: I cannot attribute this rejection to one particular file from the evidence here, but this parser is stricter than general YAML.

It rejects every YAML alias before it builds the document. That means a file may be perfectly valid YAML and still fail when it contains an alias such as *defaults. An anchor by itself is not the triggering event; using it through an alias is.

Replace alias-based reuse with explicit values if this parser must read the file. If there are no aliases, send the exact error plus the file—or a minimal reproduction. Without either, a more specific diagnosis would be a guess.

So do not treat this as proof that your YAML syntax is wrong. It is an application-level compatibility rule.