import unittest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

# Import dependent models to configure mapper relationships cleanly
from protein_information_system.operation.extraction.quick_go_extractor import (
    QuickGOAnnotationExtractor,
)
from protein_information_system.sql.model.entities.go_annotation.go_annotation import (
    ProteinGOTermAnnotation,
)
from protein_information_system.sql.model.entities.go_annotation.go_term import (  # noqa: F401
    GOTerm,
)
from protein_information_system.sql.model.entities.protein.accesion import (  # noqa: F401
    Accession,
)
from protein_information_system.sql.model.entities.protein.protein import (  # noqa: F401
    Protein,
)
from protein_information_system.sql.model.entities.sequence.sequence import (  # noqa: F401
    Sequence,
)
from protein_information_system.sql.model.entities.structure.chain import (  # noqa: F401
    Chain,
)
from protein_information_system.sql.model.entities.structure.state import (  # noqa: F401
    State,
)
from protein_information_system.sql.model.entities.structure.structure import (  # noqa: F401
    Structure,
)

# Ensure all SQLAlchemy model relationships are mapped
configure_mappers()


class TestReferenceParsing(unittest.TestCase):
    """
    Unit tests for reference extraction logic.
    Verifies that extract_publication_id correctly parses PMIDs and GO_REFs
    while leaving existing behavior and unreferenced/malformed inputs intact.
    """

    def test_existing_pmid_extraction_unchanged(self):
        # Bare numeric string preserved
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id("PMID:30514107"),
            "30514107",
        )
        # Whitespace and case handling
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id("pmid: 12345"),
            "12345",
        )
        # Empty PMID suffix
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("PMID:")
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("PMID:   ")
        )

    def test_go_ref_retention_with_prefix_and_leading_zeros(self):
        # Canonical GO_REF with prefix and leading zeros retained
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id(
                "GO_REF:0000024"
            ),
            "GO_REF:0000024",
        )
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id(
                "GO_REF:0000002"
            ),
            "GO_REF:0000002",
        )
        # Case normalization to uppercase prefix, stripping internal whitespace
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id(
                "go_ref: 0000024 "
            ),
            "GO_REF:0000024",
        )

    def test_malformed_and_unsupported_references(self):
        # Truncated or missing leading zeros (not 7 digits)
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("GO_REF:12")
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("GO_REF:24")
        )
        # Non-numeric GO_REF identifiers
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id(
                "GO_REF:abcdefg"
            )
        )
        # Empty GO_REF suffix
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("GO_REF:")
        )
        # Unsupported external namespaces
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id(
                "Reactome:R-HSA-123"
            )
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id(
                "DOI:10.1016/j.cell"
            )
        )
        # Missing, empty, or whitespace inputs
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id(None)
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("")
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id("   ")
        )

    def test_list_reference_handling_unchanged(self):
        # List returns first valid identifier
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id(
                ["invalid", "PMID:30514107"]
            ),
            "30514107",
        )
        self.assertEqual(
            QuickGOAnnotationExtractor.extract_publication_id(
                ["invalid", "GO_REF:0000024"]
            ),
            "GO_REF:0000024",
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id(
                ["invalid1", "invalid2"]
            )
        )
        self.assertIsNone(
            QuickGOAnnotationExtractor.extract_publication_id([])
        )


class TestQuickGOStorageAndDeduplicationMocked(unittest.TestCase):
    """
    Component tests using isolated mocks to verify deduplication, lookup,
    and insertion behavior without connecting to any real database.
    """

    def setUp(self):
        self.mock_conf = {
            "DB_HOST": "localhost",
            "DB_PORT": 5432,
            "DB_USERNAME": "test_user",
            "DB_PASSWORD": "test_password",
            "DB_NAME": "test_db",
            "quickgo_page_size": 100,
            "quickgo_timeout": 30,
        }
        self.extractor = QuickGOAnnotationExtractor.__new__(
            QuickGOAnnotationExtractor
        )
        self.extractor.conf = self.mock_conf
        self.extractor.logger = MagicMock()
        self.extractor.session = MagicMock()
        self.extractor.allowed_evidences = None
        self.extractor.allowed_eco_codes = None

    def test_distinct_go_refs_retained(self):
        """Two annotations with different GO_REFs for same protein and GO term."""
        protein_id = "PROT_1"
        go_id = "GO:0008150"

        # First annotation with GO_REF:0000002
        self.extractor.session.query().filter_by().first.return_value = None
        status1 = self.extractor.get_or_create_association(
            protein_id=protein_id,
            go_id=go_id,
            annotation_data={
                "goEvidence": "IEA",
                "reference": "GO_REF:0000002",
            },
        )
        self.assertEqual(status1, "created")

        # Second annotation with GO_REF:0000024
        status2 = self.extractor.get_or_create_association(
            protein_id=protein_id,
            go_id=go_id,
            annotation_data={
                "goEvidence": "IEA",
                "reference": "GO_REF:0000024",
            },
        )
        self.assertEqual(status2, "created")

        # Verify two distinct associations were added to the session
        added_objects = [
            call.args[0]
            for call in self.extractor.session.add.call_args_list
        ]
        self.assertEqual(len(added_objects), 2)
        self.assertEqual(added_objects[0].publication_id, "GO_REF:0000002")
        self.assertEqual(added_objects[1].publication_id, "GO_REF:0000024")

    def test_coexistence_pmid_and_go_ref(self):
        """Annotations with PMID and GO_REF for same protein and GO term."""
        protein_id = "PROT_1"
        go_id = "GO:0008150"

        self.extractor.session.query().filter_by().first.return_value = None

        status_pmid = self.extractor.get_or_create_association(
            protein_id=protein_id,
            go_id=go_id,
            annotation_data={
                "goEvidence": "EXP",
                "reference": "PMID:30514107",
            },
        )
        self.assertEqual(status_pmid, "created")

        status_goref = self.extractor.get_or_create_association(
            protein_id=protein_id,
            go_id=go_id,
            annotation_data={
                "goEvidence": "EXP",
                "reference": "GO_REF:0000024",
            },
        )
        self.assertEqual(status_goref, "created")

        added_objects = [
            call.args[0]
            for call in self.extractor.session.add.call_args_list
        ]
        self.assertEqual(len(added_objects), 2)
        self.assertEqual(added_objects[0].publication_id, "30514107")
        self.assertEqual(added_objects[1].publication_id, "GO_REF:0000024")

    def test_existing_go_ref_lookup_skips_insert(self):
        """Existing DB record with GO_REF returns 'existing' with 0 inserts."""
        mock_existing = MagicMock(spec=ProteinGOTermAnnotation)
        self.extractor.session.query().filter_by().first.return_value = (
            mock_existing
        )

        status = self.extractor.get_or_create_association(
            protein_id="PROT_1",
            go_id="GO:0008150",
            annotation_data={
                "goEvidence": "IEA",
                "reference": "GO_REF:0000024",
            },
        )
        self.assertEqual(status, "existing")
        self.extractor.session.add.assert_not_called()

    def test_in_memory_batch_deduplication(self):
        """Identical annotations in the same batch are deduplicated in-memory."""
        annotations = [
            {
                "goId": "GO:0008150",
                "goEvidence": "IEA",
                "reference": "GO_REF:0000024",
            },
            {
                "goId": "GO:0008150",
                "goEvidence": "IEA",
                "reference": "GO_REF:0000024",
            },
        ]
        processed_keys = set()
        dedup_count = 0
        created_count = 0

        for ann in annotations:
            go_id = ann["goId"]
            evidence_code = ann["goEvidence"]
            pub_id = QuickGOAnnotationExtractor.extract_publication_id(
                ann["reference"]
            )
            key = (go_id, evidence_code, pub_id)
            if key in processed_keys:
                dedup_count += 1
                continue
            processed_keys.add(key)
            created_count += 1

        self.assertEqual(created_count, 1)
        self.assertEqual(dedup_count, 1)


class TestQuickGOPersistenceIsolatedSQLite(unittest.TestCase):
    """
    Isolated persistence tests using an in-memory SQLite database.
    Demonstrates actual ORM model instantiation, constraint enforcement,
    coexistence, and deduplication completely isolated from the working DB.
    """

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        # Create only the target annotation table with its constraints
        ProteinGOTermAnnotation.__table__.create(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        self.extractor = QuickGOAnnotationExtractor.__new__(
            QuickGOAnnotationExtractor
        )
        self.extractor.conf = {}
        self.extractor.logger = MagicMock()
        self.extractor.session = self.session
        self.extractor.allowed_evidences = None
        self.extractor.allowed_eco_codes = None

    def tearDown(self):
        self.session.close()
        ProteinGOTermAnnotation.__table__.drop(bind=self.engine)

    def test_persistence_coexistence_and_idempotency(self):
        # 1. Insert annotation with PMID
        status1 = self.extractor.get_or_create_association(
            protein_id="P04637",
            go_id="GO:0006915",
            annotation_data={
                "goEvidence": "IDA",
                "reference": "PMID:30514107",
            },
        )
        self.assertEqual(status1, "created")
        self.session.commit()

        # 2. Insert annotation with GO_REF for same protein, term, and evidence
        status2 = self.extractor.get_or_create_association(
            protein_id="P04637",
            go_id="GO:0006915",
            annotation_data={
                "goEvidence": "IDA",
                "reference": "GO_REF:0000024",
            },
        )
        self.assertEqual(status2, "created")
        self.session.commit()

        # 3. Insert annotation with distinct GO_REF:0000002
        status3 = self.extractor.get_or_create_association(
            protein_id="P04637",
            go_id="GO:0006915",
            annotation_data={
                "goEvidence": "IDA",
                "reference": "GO_REF:0000002",
            },
        )
        self.assertEqual(status3, "created")
        self.session.commit()

        # Query all records from SQLite
        records = (
            self.session.query(ProteinGOTermAnnotation)
            .filter_by(protein_id="P04637", go_id="GO:0006915")
            .all()
        )
        self.assertEqual(len(records), 3)
        pub_ids = {r.publication_id for r in records}
        self.assertEqual(
            pub_ids, {"30514107", "GO_REF:0000024", "GO_REF:0000002"}
        )

        # 4. Idempotency test: repeated run returns 'existing' and 0 new inserts
        status_repeat = self.extractor.get_or_create_association(
            protein_id="P04637",
            go_id="GO:0006915",
            annotation_data={
                "goEvidence": "IDA",
                "reference": "GO_REF:0000024",
            },
        )
        self.assertEqual(status_repeat, "existing")
        self.session.commit()

        records_after = (
            self.session.query(ProteinGOTermAnnotation)
            .filter_by(protein_id="P04637", go_id="GO:0006915")
            .all()
        )
        self.assertEqual(len(records_after), 3)


if __name__ == "__main__":
    unittest.main()
