"""
Database utilities for the Garmin data analysis framework.

This module provides utilities for working with DuckDB, including:
- Connection management
- Query execution with parameter binding
- SQL query loading from files
- Transaction management
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import duckdb
from loguru import logger


def execute_query(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    params: Optional[Union[Tuple[Any, ...], Dict[str, Any], List[Any]]] = None,
    commit: bool = False,
    fetch: bool = True,
) -> List[Dict[str, Any]]:
    """
    Execute a SQL query with parameters and return the results.

    Args:
        conn: DuckDB connection.
        query: SQL query string.
        params: Query parameters.
        commit: Whether to commit the transaction after execution.
        fetch: Whether to fetch and return results. Set to False for INSERT, UPDATE, etc.

    Returns:
        List of dictionaries with query results.
    """
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        if commit:
            conn.commit()

        if fetch:
            # Get column names
            column_names = [desc[0] for desc in cursor.description]

            # Convert rows to dictionaries
            result = []
            for row in cursor.fetchall():
                row_dict = {column_names[i]: row[i] for i in range(len(column_names))}
                result.append(row_dict)

            return result
        return []
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        logger.debug(f"Query: {query}")
        logger.debug(f"Params: {params}")
        raise


def load_sql_query(file_path: Union[str, Path]) -> str:
    """
    Load a SQL query from a file.

    Args:
        file_path: Path to the SQL file.

    Returns:
        SQL query string.
    """
    try:
        with open(file_path, "r") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error loading SQL query from {file_path}: {str(e)}")
        raise


def load_sql_query_from_module(module_name: str, query_name: str) -> str:
    """
    Load a SQL query from a module directory.

    Args:
        module_name: Name of the module (e.g., 'core_metrics', 'baselining').
        query_name: Name of the query file (e.g., 'sleep_quality.sql').

    Returns:
        SQL query string.
    """
    base_dir = Path(__file__).parent.parent
    query_path = base_dir / module_name / "queries" / query_name
    return load_sql_query(query_path)


def transaction(conn: duckdb.DuckDBPyConnection, auto_commit: bool = True) -> duckdb.DuckDBPyConnection:
    """
    Context manager for database transactions.

    Args:
        conn: DuckDB connection.
        auto_commit: Whether to automatically commit the transaction on exit.

    Returns:
        Connection object.

    Example:
        with transaction(conn) as txn:
            execute_query(txn, "INSERT INTO ...", params=(...))
            execute_query(txn, "UPDATE ...", params=(...))
    """

    class TransactionContextManager:
        def __init__(self, conn, auto_commit):
            self.conn = conn
            self.auto_commit = auto_commit

        def __enter__(self):
            self.conn.begin()
            return self.conn

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None and self.auto_commit:
                self.conn.commit()
            else:
                self.conn.rollback()
            return False  # Re-raise any exceptions

    return TransactionContextManager(conn, auto_commit)
