"""Check the portable reader wheel without importing its code or dependencies."""
import base64
import csv
import email.parser
import hashlib
import io
from pathlib import Path
import sys
import zipfile

MODULES = {
    "salmongraph/__init__.py", "salmongraph/config.py", "salmongraph/iri.py",
    "salmongraph/graph.py", "salmongraph/provenance.py", "salmongraph/review.py",
    "salmongraph/discovery.py", "salmongraph/contribution.py", "salmongraph/native_references.py", "salmongraph/io/__init__.py", "salmongraph/io/det.py",
    "salmongraph/_stub.py", "salmongraph/serve/__init__.py", "salmongraph/serve/sparql_server.py",
}
DIST = "smn_data_graph-0.1.0.dist-info/"
METADATA = {DIST + name for name in ("METADATA", "WHEEL", "top_level.txt", "RECORD")}


def check(path):
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        assert len(names) == len(set(names)), "Duplicate wheel paths."
        assert set(names) == MODULES | METADATA, "Wheel contains an unexpected or missing file."
        assert wheel.testzip() is None, "Wheel CRC failure."
        for name in names:
            data = wheel.read(name)
            for marker in (b"/Users/", b"/home/", b"file://", b"3f5320abcc9cba653cee4bd78bae4c580d3b8477"):
                assert marker not in data, "Wheel contains a private path or local/held dependency."
        metadata = email.parser.BytesParser().parsebytes(wheel.read(DIST + "METADATA"))
        assert metadata["Name"] == "smn-data-graph" and metadata["Version"] == "0.1.0"
        requirements = metadata.get_all("Requires-Dist", [])
        assert "pyoxigraph==0.5.13" in requirements
        assert len(requirements) == 4
        for requirement in requirements:
            if requirement != "pyoxigraph==0.5.13":
                assert requirement.split("==")[0] in {"pytest", "rdflib", "pyparsing"}
                assert 'extra == "test"' in requirement
        records = list(csv.reader(io.StringIO(wheel.read(DIST + "RECORD").decode())))
        assert {row[0] for row in records} == set(names) and len(records) == len(names)
        for name, digest, size in records:
            if name == DIST + "RECORD":
                assert digest == size == ""
                continue
            data = wheel.read(name)
            actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert digest == "sha256=" + actual and size == str(len(data)), "Wheel RECORD mismatch."
    return {"wheel": Path(path).name, "files": len(names), "python_modules": len(MODULES),
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "requirements": requirements}


if __name__ == "__main__":
    import json
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_wheel.py PATH.whl")
    print(json.dumps(check(sys.argv[1]), sort_keys=True))
