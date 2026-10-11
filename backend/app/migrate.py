"""Forward-only schema versions. Use the administrator migration task, never an API role."""

import os
from psycopg import sql
from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError
from .db import Base, engine
from . import mail

ADDITIONS = {
    "login_sessions": {
        "last_seen": "FLOAT NOT NULL DEFAULT 0",
        "user_agent": "VARCHAR(200) NOT NULL DEFAULT ''",
    },
    "documents": {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "next_attempt": "FLOAT NOT NULL DEFAULT 0",
        "lease_until": "FLOAT NOT NULL DEFAULT 0",
        "claim_token": "VARCHAR(36) NOT NULL DEFAULT ''",
    },
    "email_outbox": {
        "lease_until": "FLOAT NOT NULL DEFAULT 0",
        "claim_token": "VARCHAR(36) NOT NULL DEFAULT ''",
    },
}

def provision_role(connection, prefix, allowed_prefix, tables):
    username = os.getenv(prefix + "_USER")
    password = os.getenv(prefix + "_PASSWORD")

    if not username:
        return None

    if not username.startswith(allowed_prefix) or not password or len(password) < 32:
        raise RuntimeError("Invalid application database credential configuration")

    raw = connection.connection.driver_connection
    role = sql.Identifier(username)

    # Use the database this connection actually accesses.
    database_name = connection.execute(
        text("SELECT current_database()")
    ).scalar_one()

    exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname=:name"),
        {"name": username},
    ).scalar()

    command = sql.SQL(
        ("ALTER" if exists else "CREATE")
        + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
    ).format(role, sql.Literal(password))

    try:
        connection.exec_driver_sql(command.as_string(raw))
    except SQLAlchemyError:
        raise RuntimeError(
            "Database role setup failed. Check migration permissions."
        ) from None

    statements = [
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database_name),
            role,
        ),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role),
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role),
    ]

    for table in tables:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(
                sql.Identifier(table),
                role,
            )
        )

    for statement in statements:
        connection.exec_driver_sql(statement.as_string(raw))

    return username