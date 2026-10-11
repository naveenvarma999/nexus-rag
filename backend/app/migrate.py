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
    exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": username}
    ).scalar()
    command = sql.SQL(
        ("ALTER" if exists else "CREATE")
        + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
    ).format(role, sql.Literal(password))
    try:
        connection.exec_driver_sql(command.as_string(raw))
    except SQLAlchemyError:
        raise RuntimeError(
            "Database role setup failed. Check migration permissions."
        ) from None
    statements = [
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(os.getenv("DB_NAME", "nexus")), role
        ),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role),
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role),
    ]
    for table in tables:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(
                sql.Identifier(table), role
            )
        )
    for statement in statements:
        connection.exec_driver_sql(statement.as_string(raw))
    return username


def install_rls(connection, index_role=None):
    for table in ("documents", "chunks", "search_history"):
        connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        connection.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        connection.execute(text(f"DROP POLICY IF EXISTS owner_isolation ON {table}"))
        connection.execute(
            text(
                f"CREATE POLICY owner_isolation ON {table} USING (user_id = current_setting('app.user_id', true)) WITH CHECK (user_id = current_setting('app.user_id', true))"
            )
        )
        if table != "search_history" and index_role:
            connection.execute(text(f"DROP POLICY IF EXISTS index_worker ON {table}"))
            statement = sql.SQL(
                "CREATE POLICY index_worker ON {} TO {} USING (true) WITH CHECK (true)"
            ).format(sql.Identifier(table), sql.Identifier(index_role))
            connection.exec_driver_sql(
                statement.as_string(connection.connection.driver_connection)
            )


def migrate():
    with engine.begin() as connection:
        pg = connection.dialect.name == "postgresql"
        if pg:
            connection.execute(text("SET LOCAL statement_timeout='0'"))
            connection.execute(text("SELECT pg_advisory_xact_lock(782314)"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)"
            )
        )
        Base.metadata.create_all(connection)
        if not connection.execute(
            text("SELECT 1 FROM schema_versions WHERE version=2")
        ).scalar():
            for table, columns in ADDITIONS.items():
                existing = {
                    col["name"] for col in inspect(connection).get_columns(table)
                }
                for name, definition in columns.items():
                    if name not in existing:
                        connection.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                        )
            # Version 1 had no key ID or idle policy: require an explicit new sign-in.
            connection.execute(text("UPDATE login_sessions SET revoked=true"))
            connection.execute(text("UPDATE access_tokens SET blacklisted=true"))
            connection.execute(text("INSERT INTO schema_versions (version) VALUES (2)"))
        if pg:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS chunk_vectors ON chunks USING hnsw (embedding vector_cosine_ops)"
                )
            )
            api_tables = [
                t for t in Base.metadata.tables if t not in ("provider_circuits",)
            ] + ["provider_circuits"]
            provision_role(connection, "APP_DB", "nexus_app", api_tables)
            index_role = provision_role(
                connection,
                "INDEX_DB",
                "nexus_indexer",
                ["documents", "chunks", "provider_circuits"],
            )
            provision_role(connection, "MAIL_DB", "nexus_mail", ["email_outbox"])
            install_rls(connection, index_role)


if __name__ == "__main__":
    migrate()
