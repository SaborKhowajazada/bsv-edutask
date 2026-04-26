# coding=utf-8
"""
Integration tests for the DAO.create() method.

These tests verify that the communication between the DAO and a real MongoDB
instance works correctly with respect to the schema validator constraints.

Three validator criteria are tested (as stated in the DAO.create docstring):
  1. All required properties must be present.
  2. Every property must comply to its BSON data type constraint.
  3. Properties flagged with 'uniqueItems' must be unique across documents.

The 'todo' collection is used because its validator is simple and covers all
three cases: 'description' is required (string, uniqueItems), 'done' is
optional (bool).

Fixture design:
  A real MongoDB connection is used — this is intentional for integration
  testing. The fixture writes to a dedicated test database ('edutask_test')
  and a separate test collection ('test_todo') so that production data in
  'edutask' is never touched. The collection is dropped before and after
  each test to guarantee full isolation between test cases.
  Mocking is limited to bypassing the DAO.__init__ connection logic so we
  can inject our test collection directly; the MongoDB interaction itself
  is real and unpatched.
"""

import os
import pytest
import pymongo
from dotenv import dotenv_values

from src.util.dao import DAO
from src.util.validators import getValidator

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

TEST_DB_NAME = "edutask_test"
TEST_COLLECTION_NAME = "test_todo"


@pytest.fixture
def todo_dao():
    """Provide a DAO instance backed by a real but isolated MongoDB collection.

    The fixture:
      - Resolves the MongoDB URL from the environment (same as production DAO).
      - Creates a fresh 'test_todo' collection in the 'edutask_test' database
        using the real 'todo' validator so schema enforcement is authentic.
      - Injects that collection into a DAO instance without triggering the
        normal DAO.__init__ (which would attempt to connect to 'edutask').
      - Tears down (drops) the collection after each test.
    """
    # Resolve MongoDB URL the same way the production DAO does.
    local_url = dotenv_values(".env").get("MONGO_URL")
    mongo_url = os.environ.get("MONGO_URL", local_url)

    client = pymongo.MongoClient(mongo_url)
    test_db = client[TEST_DB_NAME]

    # Drop any leftover collection from a previous interrupted run.
    if TEST_COLLECTION_NAME in test_db.list_collection_names():
        test_db.drop_collection(TEST_COLLECTION_NAME)

    # Create the collection with the authentic 'todo' validator.
    validator = getValidator("todo")
    test_db.create_collection(TEST_COLLECTION_NAME, validator=validator)

    # Build a DAO instance whose collection points to our isolated collection.
    # We bypass __init__ to avoid connecting to the production database.
    dao = DAO.__new__(DAO)
    dao.collection = test_db[TEST_COLLECTION_NAME]

    yield dao

    # Teardown: remove the test collection and close the connection.
    test_db.drop_collection(TEST_COLLECTION_NAME)
    client.close()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
# Test design technique: Equivalence Partitioning
#
# The input space is partitioned along the three validation axes that
# DAO.create documents:
#
# Axis A – Required fields
#   A1 (valid):   all required fields provided
#   A2 (invalid): at least one required field is missing
#
# Axis B – BSON type compliance
#   B1 (valid):   every field carries the correct BSON type
#   B2 (invalid): a required field carries the wrong type
#   B3 (invalid): an optional field carries the wrong type
#
# Axis C – uniqueItems uniqueness
#   C1 (valid):   the uniqueItems field value is new (no duplicate)
#   C2 (invalid): the uniqueItems field value already exists in the collection
#
# Representative test cases:
#   TC1 – A1 ∩ B1 ∩ C1 : happy path, required fields only        → success
#   TC2 – A1 ∩ B1 ∩ C1 : happy path, all fields provided         → success
#   TC3 – A2            : missing required field                  → WriteError
#   TC4 – A1 ∩ B2       : required field has wrong BSON type      → WriteError
#   TC5 – A1 ∩ B3       : optional field has wrong BSON type      → WriteError
#   TC6 – A1 ∩ B1 ∩ C1 : second doc with different description   → success
#   TC7 – A1 ∩ B1 ∩ C2 : duplicate description (uniqueItems)     → WriteError
#   TC8 – A2 (empty)    : completely empty document               → WriteError
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDaoCreate:

    # -- TC1: Required fields only (happy path) ---------------------------

    def test_create_with_required_field_only_succeeds(self, todo_dao):
        """TC1 – A valid document with only the required 'description' field
        should be inserted successfully and returned with an '_id'."""
        data = {"description": "Buy groceries"}
        result = todo_dao.create(data)

        assert result is not None
        assert "_id" in result
        assert result["description"] == "Buy groceries"

    # -- TC2: All fields provided (happy path) ----------------------------

    def test_create_with_all_fields_succeeds(self, todo_dao):
        """TC2 – A valid document providing both 'description' (required, string)
        and 'done' (optional, bool) should be inserted and returned intact."""
        data = {"description": "Read chapter 5", "done": False}
        result = todo_dao.create(data)

        assert result is not None
        assert result["description"] == "Read chapter 5"
        assert result["done"] is False

    # -- TC3: Missing required field --------------------------------------

    def test_create_missing_required_field_raises_write_error(self, todo_dao):
        """TC3 – Omitting the required 'description' field must raise a
        WriteError because the validator rejects the document."""
        data = {"done": True}

        with pytest.raises(pymongo.errors.WriteError):
            todo_dao.create(data)

    # -- TC4: Wrong BSON type for required field --------------------------

    def test_create_wrong_type_for_required_field_raises_write_error(self, todo_dao):
        """TC4 – Providing 'description' as an integer instead of a string
        violates the bsonType constraint and must raise a WriteError."""
        data = {"description": 12345}

        with pytest.raises(pymongo.errors.WriteError):
            todo_dao.create(data)

    # -- TC5: Wrong BSON type for optional field --------------------------

    def test_create_wrong_type_for_optional_field_raises_write_error(self, todo_dao):
        """TC5 – Providing 'done' as a string instead of a boolean violates
        the bsonType constraint and must raise a WriteError."""
        data = {"description": "Finish report", "done": "yes"}

        with pytest.raises(pymongo.errors.WriteError):
            todo_dao.create(data)

    # -- TC6: Two documents with distinct 'description' values ------------

    def test_create_two_docs_with_different_descriptions_both_succeed(self, todo_dao):
        """TC6 – Two documents with different 'description' values should both
        be created without error (each satisfies the uniqueItems constraint)."""
        result1 = todo_dao.create({"description": "Task alpha"})
        result2 = todo_dao.create({"description": "Task beta"})

        assert result1["description"] == "Task alpha"
        assert result2["description"] == "Task beta"

    # -- TC7: Duplicate value for uniqueItems field -----------------------

    def test_create_duplicate_description_raises_write_error(self, todo_dao):
        """TC7 – Inserting a second document with the same 'description' value
        as an existing document should raise a WriteError, because 'description'
        is marked uniqueItems in the validator."""
        todo_dao.create({"description": "Unique task"})

        with pytest.raises(pymongo.errors.WriteError):
            todo_dao.create({"description": "Unique task"})

    # -- TC8: Completely empty document -----------------------------------

    def test_create_empty_document_raises_write_error(self, todo_dao):
        """TC8 – An empty document violates the 'required' constraint
        (description is missing) and must raise a WriteError."""
        with pytest.raises(pymongo.errors.WriteError):
            todo_dao.create({})
