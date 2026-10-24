"""Installation-source provenance without inferring a commit from a version."""

import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from test_nuseds import C, Vocabulary, nuseds, stored


COMMIT = "943fe1f50d7ac5b88b8be81250dca2e7aeb0f632"
URL = f"https://github.com/salmon-data-mobilization/metasalmonpy/archive/{COMMIT}.tar.gz"
DIGEST = "a8eda518be43b1049a089a63b1d9fbea7196c0e6a1f07288d6e3b222464ec2ac"


class SDKProvenanceContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.module = SimpleNamespace(__version__="0.6.0", __file__=str(self.root / "metasalmonpy/__init__.py"))
        self.attempts = []
        def forbidden(*args, **kwargs):
            self.attempts.append(args)
            raise AssertionError("SDK provenance tests must remain offline")
        for name in ("create_connection", "getaddrinfo"):
            guard = patch.object(socket, name, forbidden)
            guard.start()
            self.addCleanup(guard.stop)
        self.addCleanup(lambda: self.assertEqual(self.attempts, []))

    def distribution(self, record):
        raw = json.dumps(record) if isinstance(record, dict) else record
        return SimpleNamespace(locate_file=lambda name: self.root / name,
                               read_text=lambda name: raw, version="0.6.0")

    def source(self, record):
        return nuseds.sdk_provenance(module=self.module, distribution=self.distribution(record))

    def test_commit_archive_is_distinct_from_the_reported_version(self):
        source = self.source({"url": URL, "archive_info": {"hashes": {"sha256": DIGEST}}})
        self.assertEqual(source["source_commit"], COMMIT)
        self.assertEqual(source["archive_sha256"], DIGEST)
        self.assertEqual(source["reported_version"], "0.6.0")
        self.assertEqual(source["source_url"], URL)
        self.assertIn("git commit " + COMMIT, nuseds.sdk_source_label(source))
        self.assertIn("reported version 0.6.0", nuseds.sdk_source_label(source))

    def test_codeload_and_legacy_archive_hash_metadata_are_supported(self):
        source = self.source({"url": f"https://codeload.github.com/salmon-data-mobilization/metasalmonpy/tar.gz/{COMMIT}",
                              "archive_info": {"hash": "sha256=" + DIGEST}})
        self.assertEqual(source["source_commit"], COMMIT)
        self.assertEqual(source["archive_sha256"], DIGEST)

    def test_git_uses_commit_id_not_requested_branch_or_version(self):
        source = self.source({"url": "https://github.com/salmon-data-mobilization/metasalmonpy.git",
                              "vcs_info": {"vcs": "git", "commit_id": COMMIT, "requested_revision": "main"}})
        self.assertEqual(source["source_commit"], COMMIT)
        for vcs in ({"vcs": "git", "requested_revision": COMMIT},
                    {"vcs": "git", "commit_id": "943fe1f"},
                    {"vcs": "hg", "commit_id": COMMIT}):
            with self.subTest(vcs=vcs):
                self.assertIsNone(self.source({"url": URL, "vcs_info": vcs})["source_commit"])

    def test_tags_branches_short_refs_and_other_archive_hosts_do_not_prove_a_commit(self):
        for url in (
            "https://github.com/salmon-data-mobilization/metasalmonpy/archive/refs/tags/v0.6.0.tar.gz",
            "https://github.com/salmon-data-mobilization/metasalmonpy/archive/refs/heads/main.tar.gz",
            "https://github.com/salmon-data-mobilization/metasalmonpy/archive/943fe1f.tar.gz",
            f"https://example.test/archive/{COMMIT}.tar.gz",
        ):
            with self.subTest(url=url):
                source = self.source({"url": url, "archive_info": {}})
                self.assertIsNone(source["source_commit"])
                self.assertIn("source commit unknown", nuseds.sdk_source_label(source))

    def test_local_editable_index_and_invalid_metadata_stay_explicitly_unknown(self):
        for record, kind in ((None, "index-or-unknown"),
                             ({"url": "file:///private/local/sdk", "dir_info": {"editable": True}}, "editable"),
                             ("invalid JSON", "metadata-invalid")):
            with self.subTest(kind=kind):
                source = self.source(record)
                self.assertIsNone(source["source_commit"])
                self.assertEqual(source["install_kind"], kind)
                self.assertNotIn("/private/local", str(source))

    def test_unrelated_installed_metadata_cannot_identify_a_bound_source_checkout(self):
        module = SimpleNamespace(__version__="0.6.0", __file__=str(self.root / "other-checkout/__init__.py"))
        source = nuseds.sdk_provenance(module=module, distribution=self.distribution({"url": URL, "archive_info": {}}))
        self.assertIsNone(source["source_commit"])
        self.assertIsNone(source["source_url"])
        self.assertEqual(source["install_kind"], "metadata-mismatch")

    def test_missing_distribution_metadata_never_uses_the_version_as_commit(self):
        with patch.object(nuseds.importlib_metadata, "distribution", side_effect=nuseds.importlib_metadata.PackageNotFoundError("metasalmonpy")):
            source = nuseds.sdk_provenance(module=self.module)
        self.assertIsNone(source["source_commit"])
        self.assertEqual(source["reported_version"], "0.6.0")
        self.assertEqual(source["install_kind"], "metadata-unavailable")

    def test_graph_software_agent_has_commit_identity_and_separate_version(self):
        source = self.source({"url": URL, "archive_info": {}})
        graph, activity = nuseds.GRAPHS["provenance"], C.BASE + "fixture/build"
        builder = C.G()
        agent = nuseds.add_sdk_provenance(builder, activity, graph, source)
        self.assertTrue(agent.endswith("metasalmonpy-commit-" + COMMIT))
        self.assertNotIn("0.6.0", agent)
        store = stored(builder)
        self.assertTrue(any(store.quads_for_pattern(C.N(agent), C.N("prov:hadPrimarySource"), C.N(URL), None)))
        self.assertTrue(any(store.quads_for_pattern(C.N(agent), C.N("schema:softwareVersion"), C.L("0.6.0"), None)))
        unknown = self.source(None)
        other = nuseds.add_sdk_provenance(builder, activity, graph, unknown)
        self.assertTrue(other.endswith("metasalmonpy-source-unknown"))
        labels = [q.object.value for q in builder.quads if q.subject == C.N(other) and q.predicate == C.N("rdfs:label")]
        self.assertTrue(any("source commit unknown" in text for text in labels))

    def test_crosswalk_and_sssom_provenance_uses_the_actual_source_descriptor(self):
        source = self.source({"url": URL, "archive_info": {}})
        with patch.object(nuseds, "sdk_provenance", return_value=source):
            crosswalks = nuseds.crosswalks(Vocabulary())
            for frame in crosswalks.values():
                inherited = frame.loc[frame.source != "corpus agent", "source"]
                self.assertTrue(inherited.str.contains(COMMIT, regex=False).all())
            codes = pd.DataFrame({"column_name": ["ESTIMATE_CLASSIFICATION", "ESTIMATE_CLASSIFICATION"],
                                  "code_value": ["NO SURVEY", "TRUE ABUNDANCE (TYPE-1)"]})
            paths = nuseds.write_sssom(codes, self.root, "a" * 64, Vocabulary())
        text = "\n".join(p.read_text() for p in paths)
        self.assertIn("reported version 0.6.0", text)
        self.assertIn(COMMIT, text)
        self.assertNotIn("from metasalmonpy 0.6.0 crosswalks", text)
        rows = pd.concat([pd.read_csv(p, sep="\t", comment="#", keep_default_na=False) for p in paths])
        inherited = rows.loc[rows.subject_label == "TRUE ABUNDANCE (TYPE-1)"].iloc[0]
        proposed = rows.loc[rows.subject_label == "NO SURVEY"].iloc[0]
        for path in paths:
            if not pd.read_csv(path, sep="\t", comment="#").empty:
                parsed = nuseds.ms.read_sssom_mapping_set(str(path))
                self.assertIn(COMMIT, parsed.metadata["mapping_set_description"])
        self.assertEqual(inherited.mapping_justification, "semapv:ManualMappingCuration")
        self.assertEqual(inherited.author_id, "")
        self.assertIn(COMMIT, inherited.mapping_tool)
        self.assertEqual(proposed.mapping_justification, "semapv:AgentBasedMatching")
        self.assertEqual(proposed.author_id, nuseds.AGENT)


if __name__ == "__main__":
    unittest.main()
