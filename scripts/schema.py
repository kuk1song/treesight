#!/usr/bin/env python3
"""Validate treesight JSON against the schemas in ../schema, with the standard library only.

Supports the subset of JSON Schema 2020-12 that the treesight schemas use, plus x-maxUnits.
unevaluatedProperties: false is handled statically: the allowed names are the properties declared
by the schema itself and by every schema it reaches through $ref or allOf. That is exact for these
schemas, which have no conditional keywords. Any other keyword is an error, so a schema can never
rely on a rule this file silently skips.

Usage: python3 schema.py <extract|session|path/to/x.schema.json> <file.json>
"""
import json
import os
import re
import sys

SCHEMA_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schema"))

_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
_WORD = re.compile(r"[^\W_]+(?:['’.\-_/+][^\W_]+)*")


def units(text):
    """Length as a reader counts it: one CJK character, or one word or number, is one unit."""
    n = len(_CJK.findall(text))
    return n + len(_WORD.findall(_CJK.sub(" ", text)))


_ANNOTATIONS = {"$schema", "$id", "$defs", "title", "description"}
_KNOWN = _ANNOTATIONS | {
    "$ref", "type", "enum", "const", "properties", "required", "additionalProperties", "unevaluatedProperties",
    "items", "prefixItems", "minItems", "maxItems", "minLength", "maxLength", "pattern", "minimum", "maximum",
    "oneOf", "anyOf", "allOf", "x-maxUnits",
}
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class Validator:
    def __init__(self, schema_dir=SCHEMA_DIR):
        self.dir = schema_dir
        self.files = {}

    def load(self, name):
        if name not in self.files:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                self.files[name] = json.load(f)
        return self.files[name]

    def resolve(self, ref, base):
        file_part, _, pointer = ref.partition("#")
        name = file_part or base
        node = self.load(name)
        for part in [p for p in pointer.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node, name

    def declared(self, schema, base, seen=None):
        """Property names a schema declares directly or through $ref and allOf."""
        seen = seen if seen is not None else set()
        if id(schema) in seen:
            return set()
        seen.add(id(schema))
        names = set(schema.get("properties", {}))
        if "$ref" in schema:
            target, tbase = self.resolve(schema["$ref"], base)
            names |= self.declared(target, tbase, seen)
        for sub in schema.get("allOf", []):
            names |= self.declared(sub, base, seen)
        return names

    def errors(self, value, schema, base, path="$"):
        unknown = set(schema) - _KNOWN
        if unknown:
            raise ValueError("%s: unsupported schema keyword(s) %s" % (base, sorted(unknown)))
        out = []
        if "$ref" in schema:
            target, tbase = self.resolve(schema["$ref"], base)
            out += self.errors(value, target, tbase, path)
        for sub in schema.get("allOf", []):
            out += self.errors(value, sub, base, path)
        for key in ("oneOf", "anyOf"):
            if key in schema:
                ok = sum(1 for sub in schema[key] if not self.errors(value, sub, base, path))
                if (key == "oneOf" and ok != 1) or (key == "anyOf" and ok == 0):
                    out.append("%s: matches %d of the %s choices" % (path, ok, key))
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_TYPES[t](value) for t in types):
                return out + ["%s: expected %s, got %s" % (path, "/".join(types), type(value).__name__)]
        if "const" in schema and value != schema["const"]:
            out.append("%s: must be %r" % (path, schema["const"]))
        if "enum" in schema and value not in schema["enum"]:
            out.append("%s: %r is not one of %s" % (path, value, schema["enum"]))
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                out.append("%s: shorter than %d characters" % (path, schema["minLength"]))
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                out.append("%s: longer than %d characters" % (path, schema["maxLength"]))
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append("%s: %r does not match %s" % (path, value, schema["pattern"]))
            if "x-maxUnits" in schema and units(value) > schema["x-maxUnits"]:
                out.append("%s: %d units, at most %d allowed: %r" % (path, units(value), schema["x-maxUnits"], value))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append("%s: below %s" % (path, schema["minimum"]))
            if "maximum" in schema and value > schema["maximum"]:
                out.append("%s: above %s" % (path, schema["maximum"]))
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                out.append("%s: fewer than %d items" % (path, schema["minItems"]))
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                out.append("%s: more than %d items" % (path, schema["maxItems"]))
            prefix = schema.get("prefixItems", [])
            for i, item in enumerate(value):
                sub = prefix[i] if i < len(prefix) else schema.get("items")
                if sub is not None:
                    out += self.errors(item, sub, base, "%s[%d]" % (path, i))
        if isinstance(value, dict):
            for name in schema.get("required", []):
                if name not in value:
                    out.append("%s: missing %r" % (path, name))
            props = schema.get("properties", {})
            for name, item in value.items():
                if name in props:
                    out += self.errors(item, props[name], base, "%s.%s" % (path, name))
            extra = schema.get("additionalProperties", True)
            if extra is not True:
                for name in value:
                    if name not in props:
                        if extra is False:
                            out.append("%s: unexpected property %r" % (path, name))
                        else:
                            out += self.errors(value[name], extra, base, "%s.%s" % (path, name))
            if schema.get("unevaluatedProperties", True) is False:
                allowed = self.declared(schema, base)
                out += ["%s: unexpected property %r" % (path, n) for n in value if n not in allowed]
        return out

    def validate(self, value, schema_name):
        """Return a list of error strings; empty means valid."""
        return self.errors(value, self.load(schema_name), schema_name)


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    name = argv[1]
    if os.sep in name or name.endswith(".json"):
        v, name = Validator(os.path.dirname(os.path.abspath(name))), os.path.basename(name)
    else:
        v, name = Validator(), name + ".schema.json"
    with open(argv[2], encoding="utf-8") as f:
        errs = v.validate(json.load(f), name)
    for e in errs:
        print(e)
    print("valid" if not errs else "%d error(s)" % len(errs), file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
