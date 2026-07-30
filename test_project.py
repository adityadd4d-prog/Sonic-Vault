import sqlite3
import logging
from project import db_schema, fill_tags_table, setup_loggers


def test_db_schema():
    """Test that db_schema creates all 5 required tables."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    db_schema(cursor)
    tables = [
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "main" in tables
    assert "details" in tables
    assert "measurements" in tables
    assert "tags" in tables
    assert "tag_relations" in tables
    conn.close()


def test_db_schema_columns():
    """Test that the details table has the correct columns."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    db_schema(cursor)
    columns = [
        row[1] for row in cursor.execute("PRAGMA table_info(details)").fetchall()
    ]
    assert "main_id" in columns
    assert "brand" in columns
    assert "name" in columns
    assert "driver" in columns
    assert "mrp" in columns
    assert "connector_type" in columns
    conn.close()


def test_db_schema_main_unique():
    """Test that the main table enforces UNIQUE on name."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    db_schema(cursor)
    cursor.execute("INSERT INTO main (name) VALUES ('Test IEM')")
    try:
        cursor.execute("INSERT INTO main (name) VALUES ('Test IEM')")
        assert False, "Should have raised IntegrityError"
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_fill_tags_table():
    """Test that fill_tags_table inserts all expected tags."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    db_schema(cursor)
    fill_tags_table(cursor)
    tags = cursor.execute("SELECT tag FROM tags").fetchall()
    tag_names = [t[0] for t in tags]
    assert "Dynamic Driver" in tag_names
    assert "ANC" in tag_names
    assert "Hexabrid" in tag_names
    assert "MMCX" in tag_names
    assert len(tags) >= 25
    conn.close()


def test_fill_tags_table_no_duplicates():
    """Test that calling fill_tags_table twice doesn't create duplicate tags."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    db_schema(cursor)
    fill_tags_table(cursor)
    count_first = cursor.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    fill_tags_table(cursor)
    count_second = cursor.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    assert count_first == count_second
    conn.close()


def test_setup_loggers():
    """Test that setup_loggers adds handlers to the root logger."""
    root_logger = logging.getLogger()
    initial_count = len(root_logger.handlers)
    setup_loggers()
    assert len(root_logger.handlers) > initial_count
    root_logger.handlers = root_logger.handlers[:initial_count]
