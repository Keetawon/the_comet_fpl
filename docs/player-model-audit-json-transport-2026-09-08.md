# Canonical audit JSON transport repair

The invalid `player_model_gw1_3_20260908_v1` remains unchanged. Its encoder sorted
integer dictionary keys before converting them into JSON strings; subsequent
lexical sorting changed the bytes. No inference or outcome scoring occurred.

The additive `fpl.validate.audit_json.canonical` normalizes every mapping key before
sorting. Supported audit keys are strings and integers. Their string identities
must be unique: `{1: "a", "1": "b"}` fails closed. Other key types are rejected.
Nested mappings and list/tuple values follow the same rule. Datetimes retain their
existing ISO representation. Encoding uses UTF-8, fixed ASCII escaping, compact
separators, sorted string keys, one trailing LF, and rejects NaN/Infinity.

The existing write-once publisher and byte-replay guard remain unchanged. The new
transport satisfies `canonical(x) == canonical(json.loads(canonical(x)))` for
supported audit metadata, including the retained full historical-input metadata.
The old serializer and its invalidation tests remain available to reproduce V1.

This repair changes no prediction, metric, cutoff, input, parameter or scientific
rule. It does not itself authorize an audit execution. The separate V2 identity
must be committed and pushed before one formal rerun can use this transport.
