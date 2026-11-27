"""Audit the declared types of native SDP measurements and explicit numeric views."""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

NUMERIC = {"integer", "number"}
VALUE_TYPES = NUMERIC | {"string", "boolean", "date", "datetime"}
SEMANTICS = ("term_iri", "property_iri", "entity_iri", "unit_iri", "constraint_iri", "statistical_modifier_iri")
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")
INTEGER = re.compile(r"[+-]?[0-9]+")
GROUPED_NUMBER = re.compile(r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]+)?")


def unique_index(records, keys):
    result = {}
    for record in records:
        key = tuple(record[name] for name in keys)
        if not all(key) or key in result:
            raise ValueError(f"empty or repeated identifier in {', '.join(keys)}")
        result[key] = record
    return result


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        header = reader.fieldnames or []
        if not header or len(header) != len(set(header)):
            raise ValueError(f"missing or duplicate CSV headers in {path.name}")
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f"wrong field count in {path.name} at line {reader.line_num}")
            yield row


def metadata(package):
    resources = unique_index(json.loads((package / "datapackage.json").read_text())["resources"], ["path"])
    tables = unique_index(read_csv(package / "metadata/tables.csv"), ["dataset_id", "table_id"])
    schemas = {}
    for key, table in tables.items():
        path = (package / table["file_name"]).resolve()
        if not path.is_relative_to(package.resolve()):
            raise ValueError("data resource must be a local package file")
        schema = resources[(table["file_name"],)]["schema"]
        fields = unique_index(schema["fields"], ["name"])
        schemas[key] = (path, schema, fields, table["primary_key"])

    columns = unique_index(read_csv(package / "metadata/column_dictionary.csv"), ["dataset_id", "table_id", "column_name"])
    measurements = {key: row for key, row in columns.items() if row["column_role"] == "measurement"}
    for key, row in measurements.items():
        value_type = row["value_type"]
        field = schemas[key[:2]][2][(key[2],)]
        if value_type not in VALUE_TYPES or field.get("type") != value_type:
            raise ValueError(f"invalid or inconsistent native measurement type for {key}")
        for name in SEMANTICS:
            if name in field and field[name] != row.get(name, ""):
                raise ValueError(f"inconsistent {name} for {key}")
    return measurements, schemas


def decision_key(value):
    if not isinstance(value, list) or len(value) != 3 or not all(isinstance(item, str) and item for item in value):
        raise ValueError("field identifiers must be [dataset_id, table_id, column_name]")
    return tuple(value)


def validate_missing_override(record):
    tokens = record["source_missing_tokens"]
    evidence = record["source_missing_evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"locator", "rationale"} or not all(
        isinstance(text, str) and text.strip() for text in evidence.values()
    ):
        raise ValueError("source_missing_evidence requires a nonempty locator and rationale")
    if not isinstance(tokens, list) or not tokens or not all(isinstance(t, str) and t.strip() for t in tokens):
        raise ValueError("source_missing_tokens requires a nonempty list of nonblank strings")
    if len(tokens) != len(set(tokens)):
        raise ValueError("repeated source_missing_token")
    for token in tokens:
        try:
            number = Decimal(token)
        except InvalidOperation:
            continue
        if number.is_finite() and (number >= 0 or not DECIMAL.fullmatch(token)):
            raise ValueError("a numeric source_missing_token must be an exact negative decimal literal")
        if number.is_infinite():
            raise ValueError("infinite source_missing_token")


def read_decisions(path, measurements):
    if path is None:
        return {}
    records = json.loads(path.read_text())
    if not isinstance(records, list):
        raise ValueError("decisions must be a JSON array")
    decisions = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each decision must be an object")
        keys = set(record) - {"source_number_format"}
        if keys not in ({"source", "view"}, {"source", "view", "source_missing_tokens", "source_missing_evidence"}, {"source", "unresolved"}):
            raise ValueError("each decision needs a source and either a view or an unresolved reason")
        if "source_number_format" in record:
            fmt = record["source_number_format"]
            if "view" not in record or not isinstance(fmt, dict) or set(fmt) != {"grouping", "locator", "rationale"} or fmt["grouping"] != "comma_thousands":
                raise ValueError("source_number_format requires a direct view, comma_thousands grouping, locator and rationale")
            if not all(isinstance(fmt[k], str) and fmt[k].strip() for k in ("locator", "rationale")):
                raise ValueError("source_number_format needs nonblank source evidence")
        source = decision_key(record["source"])
        if source in decisions or source not in measurements or measurements[source]["value_type"] in NUMERIC:
            raise ValueError(f"unknown, already numeric or repeated decision source {source}")
        if "unresolved" in record:
            if not isinstance(record["unresolved"], str) or not record["unresolved"].strip():
                raise ValueError("unresolved decisions need a nonempty reason")
        else:
            decision_key(record["view"])
            if "source_missing_tokens" in record:
                validate_missing_override(record)
                if "source_number_format" in record and any(GROUPED_NUMBER.fullmatch(t) for t in record["source_missing_tokens"]):
                    raise ValueError("a grouped number cannot be a field missing token")
        decisions[source] = record
    return decisions


def keyed_values(key, schema_info, value_type, field_tokens=(), *, grouped=False):
    path, schema, fields, table_key = schema_info
    keys = [name.strip() for name in table_key.split(",")]
    resource_key = schema.get("primaryKey")
    if isinstance(resource_key, str):
        resource_key = [resource_key]
    if not all(keys) or resource_key != keys or any((name,) not in fields for name in keys):
        raise ValueError("table and data resource must declare matching primary keys")
    missing = schema.get("missingValues", [""])
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise ValueError("resource missingValues must be an array of strings")
    if set(missing).intersection(field_tokens):
        raise ValueError("source_missing_tokens repeats a resource missing token")
    token_counts = dict.fromkeys(field_tokens, 0)
    values = {}
    for row in read_csv(path):
        identity = tuple(row[name] for name in keys)
        if any(part in missing or part == "" for part in identity) or identity in values:
            raise ValueError("empty or repeated row key")
        token = row[key[2]]
        if token in token_counts:
            token_counts[token] += 1
            values[identity] = None
        elif token in missing:
            values[identity] = None
        else:
            pattern = INTEGER if value_type == "integer" else DECIMAL
            if grouped and GROUPED_NUMBER.fullmatch(token):
                token = token.replace(",", "")
            if not pattern.fullmatch(token):
                raise ValueError("a nonmissing cell cannot be read as the declared numeric type")
            values[identity] = Decimal(token)
    return keys, values, token_counts


def verify_view(source, view, measurements, schemas, field_tokens, *, grouped=False):
    if view not in measurements or measurements[view]["value_type"] not in NUMERIC:
        raise ValueError("view must identify a native numeric measurement")
    if source[0] != view[0] or measurements[source]["value_type"] != "string":
        raise ValueError("direct views require a string measurement in the same dataset")
    source_column = measurements[source]
    view_column = measurements[view]
    term = source_column.get("term_iri", "")
    if not urlsplit(term).scheme or term.upper().startswith("REVIEW:"):
        raise ValueError("source needs a resolved variable IRI")
    attributes = SEMANTICS if source_column.get("unit_iri") else (*SEMANTICS, "unit_label")
    if any(source_column.get(name, "") != view_column.get(name, "") for name in attributes):
        raise ValueError("source and view declare different variable, unit or I-ADOPT roles")
    source_keys, original, token_counts = keyed_values(source, schemas[source[:2]], "number", field_tokens, grouped=grouped)
    view_keys, typed, _ = keyed_values(view, schemas[view[:2]], measurements[view]["value_type"])
    if source_keys != view_keys or original.keys() != typed.keys():
        raise ValueError("source and view must cover the same row keys")
    if original != typed:
        raise ValueError("source and view differ in values or missingness")
    observed = sum(value is not None for value in typed.values())
    if observed == 0:
        raise ValueError("no paired nonmissing numeric values")
    result = {"rows": len(typed), "nonmissing": observed}
    if field_tokens:
        result["source_missing_token_counts"] = token_counts
    return result


def numeric_evidence(measurements, schemas):
    """Read each table once and count valid, missing and invalid cells per native numeric field."""
    evidence = {}
    for table, (path, schema, _, _) in schemas.items():
        numeric_fields = {
            key: INTEGER if row["value_type"] == "integer" else DECIMAL
            for key, row in measurements.items() if key[:2] == table and row["value_type"] in NUMERIC
        }
        if not numeric_fields:
            continue
        missing = schema.get("missingValues", [""])
        if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
            raise ValueError("resource missingValues must be an array of strings")
        for key in numeric_fields:
            evidence[key] = {"nonmissing": 0, "missing": 0, "invalid": 0}
        for row in read_csv(path):
            for key, pattern in numeric_fields.items():
                token = row[key[2]]
                if token in missing:
                    state = "missing"
                elif pattern.fullmatch(token):
                    state = "nonmissing"
                else:
                    state = "invalid"
                evidence[key][state] += 1
    return evidence


def audit(package, decisions_path, *, check_numeric=False):
    measurements, schemas = metadata(package)
    decisions = read_decisions(decisions_path, measurements)
    direct = numeric_evidence(measurements, schemas) if check_numeric else {}
    fields = []
    for key, row in sorted(measurements.items()):
        item = {"field": list(key), "value_type": row["value_type"]}
        decision = decisions.get(key, {})
        if row["value_type"] in NUMERIC:
            item["status"] = "declared_numeric"
            if check_numeric:
                item["cells"] = direct[key]
        elif "unresolved" in decision:
            item.update(status="explicitly_unresolved", reason=decision["unresolved"])
        elif "view" in decision:
            view = decision_key(decision["view"])
            item["view"] = list(view)
            field_tokens = decision.get("source_missing_tokens", [])
            if field_tokens:
                item["source_missing_tokens"] = field_tokens
                item["source_missing_evidence"] = decision["source_missing_evidence"]
            try:
                grouped = "source_number_format" in decision
                if grouped:
                    item["source_number_format"] = decision["source_number_format"]
                item.update(verify_view(key, view, measurements, schemas, field_tokens, grouped=grouped), status="verified_view")
            except ValueError as error:
                item.update(status="invalid_view", reason=str(error))
        else:
            item["status"] = "undeclared"
        fields.append(item)
    counts = Counter(item["status"] for item in fields)
    report = {
        "measurement_slots": len(fields),
        "text_measurement_slots": sum(item["value_type"] == "string" for item in fields),
        "by_status": {status: counts[status] for status in ("declared_numeric", "verified_view", "explicitly_unresolved", "undeclared", "invalid_view")},
        "fields": fields,
        "accounted": bool(fields) and not (counts["undeclared"] or counts["invalid_view"]),
    }
    if check_numeric:
        report["numeric_ready"] = bool(fields) and all(
            item["status"] == "verified_view" or
            (item["status"] == "declared_numeric" and item["cells"]["nonmissing"] > 0 and item["cells"]["invalid"] == 0)
            for item in fields
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="native SDP directory")
    parser.add_argument("--decisions", type=Path, help="reviewer's JSON array of explicit field decisions")
    parser.add_argument("--require-accounted", action="store_true", help="fail for unreviewed slots, invalid views or no measurements")
    parser.add_argument("--require-numeric", action="store_true", help="also require usable numeric observations or a verified numeric view for every declared measurement")
    args = parser.parse_args()
    try:
        report = audit(args.package, args.decisions, check_numeric=args.require_numeric)
    except (OSError, KeyError, TypeError, ValueError, csv.Error, ArithmeticError) as error:
        parser.exit(2, f"cannot audit package: {error}\n")
    print(json.dumps(report, indent=2))
    return int((args.require_accounted and not report["accounted"]) or (args.require_numeric and not report["numeric_ready"]))


if __name__ == "__main__":
    sys.exit(main())
