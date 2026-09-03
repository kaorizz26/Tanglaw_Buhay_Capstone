"""D2: create the five approved Tanglaw-Buhay PostgreSQL tables."""

from getpass import getpass
from pathlib import Path
import sys

import pandas as pd
import psycopg
from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONNECTION = {
    "host": "localhost",
    "port": 5432,
    "dbname": "tanglaw_buhay",
    "user": "tanglaw_system",
}

CSV_PATHS = {
    "households": PROJECT_ROOT / "data" / "staged" / "households_staged.csv",
    "household_members": (
        PROJECT_ROOT / "data" / "staged" / "household_members_staged.csv"
    ),
    "member_health": PROJECT_ROOT / "data" / "staged" / "member_health_staged.csv",
    "variable_definitions": (
        PROJECT_ROOT / "data" / "reference" / "variable_definitions.csv"
    ),
    "codebook_values": PROJECT_ROOT / "data" / "reference" / "codebook_values.csv",
}

TABLE_NAMES = (
    "households",
    "household_members",
    "member_health",
    "variable_definitions",
    "codebook_values",
)

VARIABLE_DEFINITION_TYPES = {
    "variable_name": "TEXT",
    "display_name": "TEXT",
    "source_section": "TEXT",
    "source_record": "TEXT",
    "source_file": "TEXT",
    "cbms_item": "TEXT",
    "metadata_data_type": "TEXT",
    "metadata_length": "INTEGER",
    "metadata_decimal": "INTEGER",
    "metadata_scale": "TEXT",
    "practical_type": "TEXT",
    "needs_translation": "BOOLEAN",
    "needs_member_resolution": "BOOLEAN",
    "display_handling": "TEXT",
    "review_status": "TEXT",
    "notes": "TEXT",
}

CODEBOOK_VALUE_TYPES = {
    "variable_name": "TEXT",
    "display_name": "TEXT",
    "source_section": "TEXT",
    "cbms_item": "TEXT",
    "practical_type": "TEXT",
    "code": "TEXT",
    "label": "TEXT",
    "source_document": "TEXT",
    "source_page": "TEXT",
    "mapping_basis": "TEXT",
    "observed_in_current_raw": "BOOLEAN",
    "review_status": "TEXT",
    "notes": "TEXT",
}


class SchemaDefinitionError(Exception):
    """Raised when CSV metadata cannot safely define the approved schema."""


class ExistingTablesError(Exception):
    """Raised when one or more approved table names already exist."""

    def __init__(self, table_names: list[str]) -> None:
        self.table_names = table_names
        super().__init__(", ".join(table_names))


def read_headers(csv_path: Path) -> list[str]:
    if not csv_path.is_file():
        raise SchemaDefinitionError(f"Required CSV file not found: {csv_path}")
    return pd.read_csv(csv_path, nrows=0, encoding="utf-8-sig").columns.tolist()


def load_variable_definitions() -> pd.DataFrame:
    csv_path = CSV_PATHS["variable_definitions"]
    if not csv_path.is_file():
        raise SchemaDefinitionError(f"Required CSV file not found: {csv_path}")

    definitions = pd.read_csv(
        csv_path,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        encoding="utf-8-sig",
    )
    required_columns = {"variable_name", "practical_type", "metadata_decimal"}
    missing_columns = required_columns - set(definitions.columns)
    if missing_columns:
        raise SchemaDefinitionError(
            "variable_definitions.csv is missing required column(s): "
            + ", ".join(sorted(missing_columns))
        )
    if definitions["variable_name"].duplicated().any():
        duplicates = sorted(
            definitions.loc[
                definitions["variable_name"].duplicated(keep=False), "variable_name"
            ].unique()
        )
        raise SchemaDefinitionError(
            "Duplicate variable definitions found: " + ", ".join(duplicates)
        )
    return definitions.set_index("variable_name", drop=False)


def original_variable_type(variable_name: str, definitions: pd.DataFrame) -> str:
    if variable_name not in definitions.index:
        raise SchemaDefinitionError(
            f"No variable definition found for staged column {variable_name}."
        )

    definition = definitions.loc[variable_name]
    practical_type = definition["practical_type"]

    if practical_type == "number":
        decimal_text = definition["metadata_decimal"]
        if decimal_text == "":
            return "INTEGER"
        try:
            decimal_places = int(decimal_text)
        except ValueError as error:
            raise SchemaDefinitionError(
                f"Invalid metadata_decimal for {variable_name}: {decimal_text!r}"
            ) from error
        return "NUMERIC" if decimal_places > 0 else "INTEGER"

    type_mapping = {
        "text": "TEXT",
        "identifier": "TEXT",
        "yes_no_code": "TEXT",
        "coded_category": "TEXT",
        "member_reference": "CHAR(2)",
        "multi_select_code": "TEXT",
    }
    if practical_type not in type_mapping:
        raise SchemaDefinitionError(
            f"Unsupported practical_type for {variable_name}: {practical_type!r}"
        )
    return type_mapping[practical_type]


def staged_table_columns(
    csv_path: Path,
    definitions: pd.DataFrame,
    explicit_columns: dict[str, tuple[str, bool]],
) -> list[tuple[str, str, bool]]:
    columns: list[tuple[str, str, bool]] = []
    seen_database_names: set[str] = set()

    for csv_column in read_headers(csv_path):
        database_column = csv_column.lower()
        if database_column in seen_database_names:
            raise SchemaDefinitionError(
                f"Duplicate lowercase column name in {csv_path.name}: {database_column}"
            )
        seen_database_names.add(database_column)

        if csv_column in explicit_columns:
            postgres_type, not_null = explicit_columns[csv_column]
        else:
            postgres_type = original_variable_type(csv_column, definitions)
            # Original questionnaire fields stay nullable because blanks and skips are valid.
            not_null = False
        columns.append((database_column, postgres_type, not_null))

    missing_explicit_columns = set(explicit_columns) - {
        column.upper() for column, _, _ in columns
    }
    if missing_explicit_columns:
        raise SchemaDefinitionError(
            f"{csv_path.name} is missing required key column(s): "
            + ", ".join(sorted(missing_explicit_columns))
        )
    return columns


def reference_table_columns(
    csv_path: Path,
    approved_types: dict[str, str],
    not_null_columns: set[str],
) -> list[tuple[str, str, bool]]:
    headers = [header.lower() for header in read_headers(csv_path)]
    if set(headers) != set(approved_types) or len(headers) != len(approved_types):
        missing = sorted(set(approved_types) - set(headers))
        unexpected = sorted(set(headers) - set(approved_types))
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise SchemaDefinitionError(
            f"Unexpected columns in {csv_path.name} ({'; '.join(details)})."
        )
    return [
        (header, approved_types[header], header in not_null_columns)
        for header in headers
    ]


def build_table_specs() -> dict[str, dict[str, object]]:
    definitions = load_variable_definitions()

    specs: dict[str, dict[str, object]] = {
        "households": {
            "columns": staged_table_columns(
                CSV_PATHS["households"],
                definitions,
                {"HOUSEHOLD_ID": ("VARCHAR(8)", True)},
            ),
            "constraints": [
                sql.SQL("CONSTRAINT households_pkey PRIMARY KEY (household_id)")
            ],
        },
        "household_members": {
            "columns": staged_table_columns(
                CSV_PATHS["household_members"],
                definitions,
                {
                    "MEMBER_ID": ("VARCHAR(12)", True),
                    "HOUSEHOLD_ID": ("VARCHAR(8)", True),
                    "LINE_NUMBER": ("CHAR(2)", True),
                },
            ),
            "constraints": [
                sql.SQL("CONSTRAINT household_members_pkey PRIMARY KEY (member_id)"),
                sql.SQL(
                    "CONSTRAINT household_members_household_fk "
                    "FOREIGN KEY (household_id) REFERENCES households (household_id) "
                    "ON DELETE NO ACTION"
                ),
                sql.SQL(
                    "CONSTRAINT household_members_household_line_key "
                    "UNIQUE (household_id, line_number)"
                ),
            ],
        },
        "member_health": {
            "columns": staged_table_columns(
                CSV_PATHS["member_health"],
                definitions,
                {
                    "MEMBER_ID": ("VARCHAR(12)", True),
                    "HOUSEHOLD_ID": ("VARCHAR(8)", True),
                    "SECTION_L_LINE_NUMBER": ("CHAR(2)", True),
                },
            ),
            "constraints": [
                sql.SQL("CONSTRAINT member_health_pkey PRIMARY KEY (member_id)"),
                sql.SQL(
                    "CONSTRAINT member_health_member_fk "
                    "FOREIGN KEY (member_id) REFERENCES household_members (member_id) "
                    "ON DELETE NO ACTION"
                ),
                sql.SQL(
                    "CONSTRAINT member_health_household_fk "
                    "FOREIGN KEY (household_id) REFERENCES households (household_id) "
                    "ON DELETE NO ACTION"
                ),
                sql.SQL(
                    "CONSTRAINT member_health_household_line_key "
                    "UNIQUE (household_id, section_l_line_number)"
                ),
            ],
        },
        "variable_definitions": {
            "columns": reference_table_columns(
                CSV_PATHS["variable_definitions"],
                VARIABLE_DEFINITION_TYPES,
                {"variable_name"},
            ),
            "constraints": [
                sql.SQL(
                    "CONSTRAINT variable_definitions_pkey PRIMARY KEY (variable_name)"
                )
            ],
        },
        "codebook_values": {
            "columns": reference_table_columns(
                CSV_PATHS["codebook_values"],
                CODEBOOK_VALUE_TYPES,
                {"variable_name", "code"},
            ),
            "constraints": [
                sql.SQL(
                    "CONSTRAINT codebook_values_pkey PRIMARY KEY (variable_name, code)"
                ),
                sql.SQL(
                    "CONSTRAINT codebook_values_variable_fk "
                    "FOREIGN KEY (variable_name) "
                    "REFERENCES variable_definitions (variable_name) "
                    "ON DELETE NO ACTION"
                ),
            ],
        },
    }

    if tuple(specs) != TABLE_NAMES:
        raise SchemaDefinitionError("Internal table specification does not match D2 scope.")
    return specs


def create_table_statement(
    table_name: str, table_spec: dict[str, object]
) -> sql.Composed:
    column_definitions = []
    for column_name, postgres_type, not_null in table_spec["columns"]:
        column_definitions.append(
            sql.SQL("{} {}{}").format(
                sql.Identifier(column_name),
                sql.SQL(postgres_type),
                sql.SQL(" NOT NULL" if not_null else ""),
            )
        )

    table_items = column_definitions + table_spec["constraints"]
    return sql.SQL("CREATE TABLE {} ({})").format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(table_items),
    )


def current_base_tables(cursor: psycopg.Cursor) -> set[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_type = 'BASE TABLE'
        """
    )
    return {row[0] for row in cursor.fetchall()}


def existing_target_relations(cursor: psycopg.Cursor) -> list[str]:
    cursor.execute(
        """
        SELECT c.relname
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = ANY(%s)
        ORDER BY c.relname
        """,
        (list(TABLE_NAMES),),
    )
    return [row[0] for row in cursor.fetchall()]


def inspect_schema(
    cursor: psycopg.Cursor,
    specs: dict[str, dict[str, object]],
    tables_before: set[str],
) -> dict[str, dict[str, object]]:
    tables_after = current_base_tables(cursor)
    new_tables = tables_after - tables_before
    if new_tables != set(TABLE_NAMES):
        raise SchemaDefinitionError(
            "Schema verification found an unexpected set of new tables: "
            + ", ".join(sorted(new_tables))
        )

    cursor.execute(
        """
        SELECT table_name, COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        GROUP BY table_name
        """,
        (list(TABLE_NAMES),),
    )
    column_counts = {table_name: count for table_name, count in cursor.fetchall()}

    cursor.execute(
        """
        SELECT tc.table_name,
               tc.constraint_type,
               tc.constraint_name,
               string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position)
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_schema = kcu.constraint_schema
         AND tc.constraint_name = kcu.constraint_name
        WHERE tc.table_schema = current_schema()
          AND tc.table_name = ANY(%s)
          AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
        GROUP BY tc.table_name, tc.constraint_type, tc.constraint_name
        ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name
        """,
        (list(TABLE_NAMES),),
    )
    key_constraints = cursor.fetchall()

    cursor.execute(
        """
        SELECT tc.table_name,
               tc.constraint_name,
               kcu.column_name,
               ccu.table_name AS referenced_table,
               ccu.column_name AS referenced_column,
               rc.delete_rule
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_schema = kcu.constraint_schema
         AND tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
          ON tc.constraint_schema = ccu.constraint_schema
         AND tc.constraint_name = ccu.constraint_name
        JOIN information_schema.referential_constraints AS rc
          ON tc.constraint_schema = rc.constraint_schema
         AND tc.constraint_name = rc.constraint_name
        WHERE tc.table_schema = current_schema()
          AND tc.table_name = ANY(%s)
          AND tc.constraint_type = 'FOREIGN KEY'
        ORDER BY tc.table_name, tc.constraint_name
        """,
        (list(TABLE_NAMES),),
    )
    foreign_keys = cursor.fetchall()

    inspection: dict[str, dict[str, object]] = {}
    for table_name in TABLE_NAMES:
        expected_column_count = len(specs[table_name]["columns"])
        actual_column_count = column_counts.get(table_name, 0)
        if actual_column_count != expected_column_count:
            raise SchemaDefinitionError(
                f"{table_name} has {actual_column_count} columns; "
                f"expected {expected_column_count}."
            )

        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name))
        )
        row_count = cursor.fetchone()[0]
        if row_count != 0:
            raise SchemaDefinitionError(
                f"{table_name} contains {row_count} row(s); expected 0 after D2."
            )

        primary_keys = [
            columns
            for table, constraint_type, _, columns in key_constraints
            if table == table_name and constraint_type == "PRIMARY KEY"
        ]
        unique_constraints = [
            columns
            for table, constraint_type, _, columns in key_constraints
            if table == table_name and constraint_type == "UNIQUE"
        ]
        table_foreign_keys = [
            {
                "column": column,
                "referenced_table": referenced_table,
                "referenced_column": referenced_column,
                "delete_rule": delete_rule,
            }
            for table, _, column, referenced_table, referenced_column, delete_rule
            in foreign_keys
            if table == table_name
        ]
        if any(item["delete_rule"] != "NO ACTION" for item in table_foreign_keys):
            raise SchemaDefinitionError(
                f"{table_name} has a foreign key with unexpected delete behavior."
            )

        inspection[table_name] = {
            "column_count": actual_column_count,
            "row_count": row_count,
            "primary_keys": primary_keys,
            "foreign_keys": table_foreign_keys,
            "unique_constraints": unique_constraints,
        }

    return inspection


def print_inspection(inspection: dict[str, dict[str, object]]) -> None:
    print("D2 PostgreSQL Schema Creation\n")
    print("Connection: PASS")
    print("Existing target table check: PASS")
    print("Schema transaction: COMMITTED\n")
    print("Tables created and verified:")

    for table_name in TABLE_NAMES:
        details = inspection[table_name]
        primary_keys = details["primary_keys"]
        unique_constraints = details["unique_constraints"]
        foreign_keys = details["foreign_keys"]

        print(
            f"\n{table_name}: {details['column_count']} columns, "
            f"{details['row_count']} rows"
        )
        print(
            "  Primary key: "
            + ("; ".join(primary_keys) if primary_keys else "none")
        )
        if foreign_keys:
            formatted_foreign_keys = [
                f"{item['column']} -> "
                f"{item['referenced_table']}({item['referenced_column']}) "
                f"[ON DELETE {item['delete_rule']}]"
                for item in foreign_keys
            ]
            print("  Foreign keys: " + "; ".join(formatted_foreign_keys))
        else:
            print("  Foreign keys: none")
        print(
            "  Unique constraints: "
            + ("; ".join(unique_constraints) if unique_constraints else "none")
        )

    print("\nD2 schema creation complete. No data has been loaded.")


def main() -> None:
    specs = build_table_specs()

    try:
        password = getpass("PostgreSQL password for tanglaw_system: ")
    except (EOFError, KeyboardInterrupt) as error:
        raise SchemaDefinitionError("Password entry was cancelled.") from error

    connection: psycopg.Connection | None = None
    try:
        connection = psycopg.connect(**CONNECTION, password=password)
        with connection.cursor() as cursor:
            existing_tables = existing_target_relations(cursor)
            if existing_tables:
                raise ExistingTablesError(existing_tables)

            tables_before = current_base_tables(cursor)
            for table_name in TABLE_NAMES:
                cursor.execute(create_table_statement(table_name, specs[table_name]))

            inspection = inspect_schema(cursor, specs, tables_before)
        connection.commit()
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()

    print_inspection(inspection)


if __name__ == "__main__":
    try:
        main()
    except ExistingTablesError as error:
        print("D2 schema creation stopped.", file=sys.stderr)
        print("One or more approved tables already exist:", file=sys.stderr)
        for table_name in error.table_names:
            print(f"- {table_name}", file=sys.stderr)
        print("No tables were dropped or overwritten.", file=sys.stderr)
        sys.exit(1)
    except (SchemaDefinitionError, OSError, pd.errors.ParserError) as error:
        print("D2 schema creation failed.", file=sys.stderr)
        print(f"ERROR: {error}", file=sys.stderr)
        print("The transaction was rolled back; no partial schema was kept.", file=sys.stderr)
        sys.exit(1)
    except psycopg.Error as error:
        print("D2 schema creation failed.", file=sys.stderr)
        print(f"PostgreSQL error: {error}", file=sys.stderr)
        print("The transaction was rolled back; no partial schema was kept.", file=sys.stderr)
        sys.exit(1)
