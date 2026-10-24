#!/usr/bin/env python3
"""Read-only checks for the legacy PSF NuSEDS PICES baseline artifacts.

This is a bounded regression audit, not SHACL validation or release certification.
It reads the saved TriG and package; it never fetches data or runs an agent/build.
Only an explicitly requested --output receipt is written. Exit codes: 0 scoped
checks passed (warnings may remain), 1 blockers found, 2 missing/malformed input.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zlib

import pyoxigraph as ox

SLUG = "psf-nuseds-cleaned"
LEGACY_BASE = "https://w3id.org/salmon-demo-corpus/"
GCD = "https://w3id.org/gcdfo/salmon#"
AUDIT_ID = "legacy-psf-nuseds-pices-baseline-v2"
PREFIXES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "qb": "http://purl.org/linked-data/cube#",
    "smn": "https://w3id.org/smn/",
    "gcdfo": GCD,
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "csvw": "http://www.w3.org/ns/csvw#",
    "iop": "https://w3id.org/iadopt/ont/",
}


class AuditInputError(ValueError):
    """The audit could not inspect its intended artifacts."""


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AuditInputError(f"Cannot read {path}: {exc.strerror}") from exc


def _json(path: Path) -> dict:
    try:
        value = json.loads(_read(path))
    except (ValueError, UnicodeError) as exc:
        raise AuditInputError(f"Malformed JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditInputError(f"Expected a JSON object: {path}")
    return value


def _query(store: ox.Store, query: str) -> list:
    # A union graph makes schema and data in different named graphs visible to
    # property paths. SELECT DISTINCT below prevents graph repetition counting.
    return list(store.query(query, prefixes=PREFIXES, use_default_graph_as_union=True))


def _check(identifier: str, status: str, message: str, evidence: dict) -> dict:
    return {"id": identifier, "status": status, "message": message, "evidence": evidence}


def _critical_identity_candidates(store: ox.Store, base_iri: str) -> dict:
    """Check the legacy, unasserted RDF 1.1 candidate profile per relationship.

    A mark elsewhere in a graph cannot qualify an unmarked mapping. Critical
    candidates are not live join edges in this legacy format: it has no reviewed
    query view. Human decision formats and RDF 1.2 reifiers need their own audit.
    """
    kinds = _query(store, """SELECT DISTINCT ?s ?kind WHERE {
        ?s rdf:type/rdfs:subClassOf* ?kind .
        VALUES ?kind { gcdfo:ConservationUnit smn:Population }
    }""")
    cus = {row["s"] for row in kinds if row["kind"].value == GCD + "ConservationUnit"}
    populations = {row["s"] for row in kinds if row["kind"].value == PREFIXES["smn"] + "Population"}
    mappings = " ".join("skos:" + name for name in ("exactMatch", "closeMatch", "broadMatch", "narrowMatch"))
    predicates = {PREFIXES["skos"] + name for name in ("exactMatch", "closeMatch", "broadMatch", "narrowMatch")}

    def kind_of(s, p, o):
        if not all(isinstance(term, ox.NamedNode) for term in (s, p, o)):
            return None
        is_cu = lambda term: term in cus or term.value.startswith(base_iri + "id/cu/")
        if p.value in predicates and is_cu(s) and is_cu(o):
            return "cu_to_cu"
        is_population = s in populations or s.value.startswith(base_iri + "id/population/")
        if p.value == PREFIXES["smn"] + "populationOf" and is_population and is_cu(o):
            return "population_to_cu"
        return None

    live = set()
    records = {}
    for row in _query(store, f"""SELECT DISTINCT ?s ?p ?o WHERE {{
        ?s ?p ?o . VALUES ?p {{ {mappings} smn:populationOf }}
    }}"""):
        key = (row["s"], row["p"], row["o"])
        if kind_of(*key):
            live.add(key)
    # Include unasserted candidates and records missing rdf:type, so dropping
    # either the live triple or a required type cannot evade the review gate.
    for row in _query(store, f"""SELECT DISTINCT ?r ?s ?p ?o WHERE {{
        ?r rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o .
        VALUES ?p {{ {mappings} smn:populationOf }}
    }}"""):
        key = (row["s"], row["p"], row["o"])
        if kind_of(*key):
            records.setdefault(key, set()).add(row["r"])

    profile, rdf = base_iri + "profile/", PREFIXES["rdf"]
    valid_confidence = {ox.NamedNode(profile + x) for x in ("lowConfidence", "mediumConfidence", "highConfidence")}
    violations, reasons_count, by_kind = [], Counter(), Counter()
    valid, record_count = 0, 0
    for key in sorted(live | set(records), key=lambda terms: tuple(map(str, terms))):
        by_kind[kind_of(*key)] += 1
        nodes, reasons = sorted(records.get(key, set()), key=str), set()
        if key in live:
            reasons.add("live_unreviewed_critical_bridge")
        if not nodes:
            reasons.add("missing_statement_record")
        elif len(nodes) != 1:
            reasons.add("multiple_statement_records_unsupported")
        record_count += len(nodes)
        for node in nodes:
            props = {}
            for q in store.quads_for_pattern(node, None, None, None):
                props.setdefault(q.predicate.value, set()).add(q.object)
            if not isinstance(node, ox.NamedNode):
                reasons.add("statement_identifier_must_be_iri")
            if ox.NamedNode(rdf + "Statement") not in props.get(rdf + "type", set()):
                reasons.add("missing_rdf_statement_type")
            for name, value in zip(("subject", "predicate", "object"), key):
                if props.get(rdf + name) != {value}:
                    reasons.add("ambiguous_or_incorrect_statement_" + name)
            for predicate, name in (("wasAttributedTo", "agent"), ("wasGeneratedBy", "activity")):
                values = props.get(PREFIXES["prov"] + predicate, set())
                if len(values) != 1 or not all(isinstance(v, ox.NamedNode) for v in values):
                    reasons.add("missing_or_invalid_" + name + "_iri")
            sources = props.get(PREFIXES["dcterms"] + "source", set())
            if not sources or not all(isinstance(v, ox.NamedNode) for v in sources):
                reasons.add("missing_or_invalid_source_evidence")
            comments = props.get(PREFIXES["rdfs"] + "comment", set())
            if not any(isinstance(v, ox.Literal) and v.value.strip() for v in comments):
                reasons.add("missing_context_comment")
            confidence = props.get(profile + "confidence", set())
            if len(confidence) != 1 or not confidence <= valid_confidence:
                reasons.add("missing_or_invalid_confidence")
            if props.get(profile + "criticality") != {ox.NamedNode(profile + "critical")}:
                reasons.add("missing_or_invalid_criticality")
            if props.get(profile + "reviewStatus") != {ox.NamedNode(profile + "awaitingReview")}:
                reasons.add("missing_invalid_or_unsupported_review_status")
        if reasons:
            reasons_count.update(reasons)
            violations.append({"subject": key[0].value, "predicate": key[1].value, "object": key[2].value,
                               "statement_records": list(map(str, nodes)), "reasons": sorted(reasons)})
        else:
            valid += 1
    unsupported = {q.subject for q in store.quads_for_pattern(None, ox.NamedNode(rdf + "reifies"), None, None)}
    return _check(
        "critical_identity_candidate_review", "blocker" if violations or unsupported else "pass",
        "Legacy critical identity candidates require per-statement provenance and awaitingReview marks, with no live join edge. Structural passage is not scientific approval.",
        {"candidate_relationships": sum(by_kind.values()), "by_kind": dict(sorted(by_kind.items())),
         "statement_records": record_count, "valid_awaiting_review_candidates": valid,
         "live_critical_bridges": len(live), "invalid_relationships": len(violations),
         "violations_by_reason": dict(sorted(reasons_count.items())), "violations_sample": violations[:10],
         "unsupported_rdf_reifies_records": len(unsupported),
         "profile_limit": "One RDF 1.1 statement per relationship; only unasserted awaitingReview candidates are accepted. Human decisions and RDF 1.2 reification are unsupported."},
    )


def audit(root: Path, base_iri: str = LEGACY_BASE) -> dict:
    root = root.resolve()
    package_dir = root / "packages" / SLUG
    summary_path = package_dir / "review/graph-summary.json"
    package_path = package_dir / "datapackage.json"
    summary, package = _json(summary_path), _json(package_path)
    reported = summary.get("quads_dataset")
    per_graph = summary.get("per_graph")
    if (type(reported) is not int or reported < 0 or not isinstance(per_graph, dict)
            or not per_graph or any(not isinstance(k, str) or type(v) is not int or v < 0
                                    for k, v in per_graph.items())):
        raise AuditInputError("graph-summary.json needs non-negative integer quads_dataset/per_graph counts")
    graph_file = summary.get("graph_file")
    if not isinstance(graph_file, str):
        raise AuditInputError("graph-summary.json needs graph_file")
    graph_path = (root / graph_file).resolve()
    if not graph_path.is_relative_to(root):
        raise AuditInputError("graph_file must stay inside --root")
    graph_bytes = _read(graph_path)
    # Parse decompressed content, but retain the saved compressed artifact as
    # the input whose bytes/hash appear in the evidence receipt.
    parse_bytes = graph_bytes
    if graph_path.suffix == ".gz":
        try:
            parse_bytes = gzip.decompress(graph_bytes)
        except (OSError, EOFError, zlib.error) as exc:
            raise AuditInputError(f"Malformed or truncated gzip graph: {graph_path}") from exc
    store = ox.Store()
    try:
        store.load(input=parse_bytes, format=ox.RdfFormat.TRIG)
    except (SyntaxError, ValueError, OSError) as exc:
        raise AuditInputError(f"Malformed TriG: {graph_path}") from exc

    inputs = [summary_path, package_path, graph_path]
    actual_graphs = Counter(str(q.graph_name) for q in store)
    expected_names = {
        role: str(ox.NamedNode(f"{base_iri}graph/{SLUG}/{role}")) for role in per_graph
    }
    unknown = sorted(set(actual_graphs) - set(expected_names.values()))
    missing = sorted(role for role, name in expected_names.items()
                     if per_graph[role] > 0 and name not in actual_graphs)
    counts = {
        role: {"reported": per_graph[role], "parsed_unique": actual_graphs.get(name, 0)}
        for role, name in sorted(expected_names.items())
    }
    mismatch = (reported != len(store) or sum(per_graph.values()) != reported
                or unknown or missing or any(v["reported"] != v["parsed_unique"] for v in counts.values()))
    checks = [_check(
        "saved_graph_counts", "blocker" if mismatch else "pass",
        "Summary counts must describe the saved unique quads, not builder add calls.",
        {"reported_dataset": reported, "parsed_unique_dataset": len(store),
         "per_graph": counts, "missing_graph_roles": missing, "unknown_graphs": unknown,
         "not_checked": "quads_store_total includes vocabulary graphs absent from this TriG"},
    )]

    # This policy names the reviewed legacy site class explicitly. --base-iri
    # supports a namespace migration with the same legacy graph/class layout.
    domain_rows = _query(store, f"""
        SELECT DISTINCT ?s ?p ?kind WHERE {{
            ?s ?p ?cu ; rdf:type/rdfs:subClassOf* ?kind .
            FILTER(?p = gcdfo:hasConservationUnit ||
                   EXISTS {{ ?p rdfs:subPropertyOf+ gcdfo:hasConservationUnit }})
            VALUES ?kind {{ smn:Population qb:Observation <{base_iri}def/SurveySite> }}
        }} ORDER BY ?kind ?s ?p
    """)
    by_kind = Counter(row["kind"].value for row in domain_rows)
    checks.append(_check(
        "has_conservation_unit_domain", "blocker" if domain_rows else "pass",
        "Population/site/observation use would entail StockManagementUnit membership through the reviewed gcdfo domain; this is not an OWL inconsistency claim.",
        {"subject_predicate_type_pairs": len(domain_rows),
         "distinct_subjects": len({row["s"] for row in domain_rows}),
         "by_explicit_or_superclass": dict(sorted(by_kind.items())),
         "sample": [{key: row[key].value for key in ("s", "p", "kind")} for row in domain_rows[:5]]},
    ))
    checks.append(_critical_identity_candidates(store, base_iri))

    resources = package.get("resources")
    if not isinstance(resources, list) or any(not isinstance(r, dict) for r in resources):
        raise AuditInputError("datapackage.json needs a resources list of objects")
    risky_fields = []
    for resource in resources:
        schema = resource.get("schema")
        if not isinstance(schema, dict):
            continue  # Metadata resources legitimately refer to an external schema.
        fields = schema.get("fields")
        if not isinstance(fields, list) or any(not isinstance(f, dict) for f in fields):
            raise AuditInputError(f"Malformed fields in resource {resource.get('name')}")
        for field in fields:
            is_max = field.get("name") == "MAX_ESTIMATE"
            is_max_sum = (field.get("name") == "spawner_abundance"
                          and "MAX_ESTIMATE" in str(field.get("description", "")))
            if (is_max or is_max_sum) and field.get("term_iri") == GCD + "SpawnerAbundance":
                risky_fields.append({"resource": resource.get("name"), "field": field.get("name"),
                                     "term_iri": field["term_iri"]})
    risky_measures = _query(store, """
        SELECT DISTINCT ?measure ?comment WHERE {
            ?measure rdf:type qb:MeasureProperty ; qb:concept gcdfo:SpawnerAbundance ;
                     rdfs:comment ?comment .
            FILTER(CONTAINS(UCASE(STR(?comment)), "MAX_ESTIMATE"))
        } ORDER BY ?measure ?comment
    """)
    residual_contexts = _query(store, f"""SELECT DISTINCT ?column ?variable WHERE {{
        ?column csvw:name ?name ; <{base_iri}def/variable> ?variable .
        FILTER(STR(?name) = "MAX_ESTIMATE")
        ?variable (iop:hasConstraint|iop:hasObjectOfInterest|iop:hasContextObject|iop:hasProperty)+ smn:SpawnerStageContext .
    }} ORDER BY ?column ?variable""")
    decomposition_path = package_dir / "metadata/semantic/measurement-decompositions.csv"
    residual_package_contexts = []
    if decomposition_path.exists():
        inputs.append(decomposition_path)
        try:
            rows = csv.DictReader(_read(decomposition_path).decode("utf-8").splitlines())
            required = {"table_id", "column_name", "component_iri", "component_role"}
            if not rows.fieldnames or not required <= set(rows.fieldnames):
                raise AuditInputError("Malformed measurement-decompositions.csv columns")
            for row in rows:
                if None in row or any(row.get(k) is None for k in required):
                    raise AuditInputError("Malformed measurement-decompositions.csv row")
                if row["column_name"] == "MAX_ESTIMATE" and row["component_iri"] == PREFIXES["smn"] + "SpawnerStageContext":
                    residual_package_contexts.append({key: row[key] for key in sorted(required)})
        except (UnicodeError, csv.Error) as exc:
            raise AuditInputError("Malformed measurement-decompositions.csv") from exc
    checks.append(_check(
        "max_estimate_spawner_semantics", "blocker" if risky_fields or risky_measures or residual_contexts or residual_package_contexts else "pass",
        "Source MAX_ESTIMATE is not established as spawner-only; its biological scope needs source review. No literal row-maximum equation or replacement semantics are inferred here.",
        {"fields": sorted(risky_fields, key=lambda f: (str(f["resource"]), f["field"])),
         "cube_measures": [{"iri": row["measure"].value, "comment": row["comment"].value}
                           for row in risky_measures],
         "residual_graph_spawner_contexts": [{"column": row["column"].value, "variable": row["variable"].value}
                                              for row in residual_contexts],
         "residual_package_spawner_contexts": residual_package_contexts},
    ))

    # Only flag rows that explicitly say the corpus agent supplied them. A
    # manual label on an upstream mapping alone is not proof it lacks review.
    sssom_paths = sorted((package_dir / "metadata/semantic").glob("*.sssom.tsv"))
    manual_agent_rows = []
    for path in sssom_paths:
        inputs.append(path)
        try:
            lines = _read(path).decode("utf-8").splitlines()
            rows = csv.DictReader((line for line in lines if not line.startswith("#")), delimiter="\t")
            if not rows.fieldnames or not {"subject_id", "mapping_justification", "comment"} <= set(rows.fieldnames):
                raise AuditInputError(f"Missing required SSSOM columns: {path}")
            for row in rows:
                if None in row or any(row.get(k) is None for k in rows.fieldnames):
                    raise AuditInputError(f"Malformed SSSOM row: {path}")
                if ("source: corpus agent" in row["comment"].lower()
                        and row["mapping_justification"] == "semapv:ManualMappingCuration"):
                    manual_agent_rows.append({"file": str(path.relative_to(root)),
                                              "subject_id": row["subject_id"], "comment": row["comment"]})
        except (UnicodeError, csv.Error) as exc:
            raise AuditInputError(f"Malformed SSSOM: {path}") from exc
    checks.append(_check(
        "agent_mapping_curation_claim", "warning" if manual_agent_rows or not sssom_paths else "pass",
        "Explicit corpus-agent rows labelled ManualMappingCuration need provenance/review confirmation; this does not assess upstream curators.",
        {"files_checked": len(sssom_paths), "rows_needing_review": manual_agent_rows},
    ))

    return {
        "audit": AUDIT_ID, "parser": f"pyoxigraph {ox.__version__}",
        "scope": "Saved legacy PSF NuSEDS artifacts only; not full SHACL validation, scientific approval, or release certification.",
        "limitations": ["No external ontology, source data, licence, or human-review record is fetched.",
                        "Domain check covers smn:Population, qb:Observation and the configured legacy SurveySite class, including declared subclass/subproperty paths.",
                        "Identity review checks cover known CU SKOS mappings and Population-to-CU populationOf candidates only, using the legacy RDF 1.1 awaitingReview profile. Human decisions and RDF 1.2 reifiers fail closed.",
                        "Absence of a flagged MAX_ESTIMATE annotation does not prove remaining measures are scientifically correct."],
        "base_iri": base_iri, "status": "blocked" if any(c["status"] == "blocker" for c in checks) else "scoped_checks_passed",
        "inputs": [{"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(_read(path)).hexdigest()} for path in sorted(set(inputs))],
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-iri", default=LEGACY_BASE, help="Legacy graph/class namespace, ending in /")
    parser.add_argument("--output", type=Path, help="Also save the JSON receipt here; inputs are never overwritten")
    args = parser.parse_args(argv)
    try:
        # Validate before interpolating the configured IRI into SPARQL.
        ox.NamedNode(args.base_iri)
        if not args.base_iri.endswith("/"):
            raise AuditInputError("--base-iri must end in /")
        report = audit(args.root, args.base_iri)
        if args.output:
            protected = {(args.root.resolve() / item["path"]).resolve() for item in report["inputs"]}
            if args.output.resolve() in protected:
                raise AuditInputError("--output would overwrite an audited input")
        text = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        sys.stdout.write(text)
        return 1 if report["status"] == "blocked" else 0
    except (AuditInputError, ValueError, OSError) as exc:
        sys.stdout.write(json.dumps({"audit": AUDIT_ID, "status": "input_error",
                                    "error": str(exc)}, indent=2, sort_keys=True) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
