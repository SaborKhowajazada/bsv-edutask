import os
import pytest
from pymongo.errors import WriteError

import src.util.dao as dao_file
from src.util.dao import DAO


TEST_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["name", "email", "active"],
        "properties": {
            "name": {
                "bsonType": "string"
            },
            "email": {
                "bsonType": "string"
            },
            "active": {
                "bsonType": "bool"
            }
        }
    }
}


@pytest.fixture
def dao(monkeypatch):
    # Use test MongoDB url if it exists
    test_mongo_url = os.getenv("TEST_MONGO_URL")

    if test_mongo_url:
        monkeypatch.setenv("MONGO_URL", test_mongo_url)

    # Use our test validator instead of the normal validator
    monkeypatch.setattr(
        dao_file,
        "getValidator",
        lambda collection_name: TEST_VALIDATOR
    )

    test_dao = DAO("test_dao_create_collection")

    test_dao.drop()
    test_dao = DAO("test_dao_create_collection")

    yield test_dao

    test_dao.drop()


def test_create_valid_document(dao):
    data = {
        "name": "Sabor",
        "email": "sabor@example.com",
        "active": True
    }

    result = dao.create(data)

    assert "_id" in result
    assert result["name"] == "Sabor"
    assert result["email"] == "sabor@example.com"
    assert result["active"] is True


def test_create_without_required_field(dao):
    data = {
        "name": "Sabor",
        "active": True
    }

    with pytest.raises(WriteError):
        dao.create(data)


def test_create_with_wrong_type(dao):
    data = {
        "name": "Sabor",
        "email": "sabor@example.com",
        "active": "yes"
    }

    with pytest.raises(WriteError):
        dao.create(data)


def test_create_second_valid_document(dao):
    first_user = {
        "name": "Sabor",
        "email": "sabor@example.com",
        "active": True
    }

    second_user = {
        "name": "Baraa",
        "email": "baraa@example.com",
        "active": False
    }

    first_result = dao.create(first_user)
    second_result = dao.create(second_user)

    assert "_id" in first_result
    assert "_id" in second_result
    assert first_result["email"] == "sabor@example.com"
    assert second_result["email"] == "baraa@example.com"