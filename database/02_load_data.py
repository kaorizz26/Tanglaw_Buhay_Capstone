"""D3: load validated CSV data into the existing Tanglaw-Buhay schema."""

from decimal import Decimal, InvalidOperation
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

SOURCE_FILES = {
    "variable_definitions": (
        PROJECT_ROOT / "data" / "reference" / "variable_definitions.csv"
    ),
    "codebook_values": PROJECT_ROOT / "data" / "reference" / "codebook_values.csv",
    "households": PROJECT_ROOT / "data" / "staged" / "households_staged.csv",
    "household_members": (
        PROJECT_ROOT / "data" / "staged" / "household_members_staged.csv"
    ),
    "member_health": PROJECT_ROOT / "data" / "staged" / "member_health_staged.csv",
}

# Parent tables are loaded before the tables that reference them.
LOAD_ORDER = (
    "variable_definitions",
    "codebook_values",
    "households",
    "household_members",
    "member_health",
)

EXPECTED_ROW_COUNTS = {
    "variable_definitions": 157,
    "codebook_values": 509,
    "households": 500,
    "household_members": 2043,
    "member_health": 2043,
}

PRIMARY_KEYS = {
    "variable_definitions": ("variable_name",),
    "codebook_values": ("variable_name", "code"),
    "households": ("household_id",),
    "household_members": ("member_id",),
    "member_health": ("member_id",),
}

INTEGER_TYPES = {"smallint", "integer", "bigint"}
DECIMAL_TYPES = {"numeric", "decimal", "real", "double precision"}


class PreflightError(Exception):
    """Raised before insertion when files, tables, rows, or columns are unsafe."""


class DataConversionError(Exception):
    """Raised when a CSV value cannot be converted to its existing database type."""


class TableLoadError(Exception):
    """Raised when PostgreSQL rejects an insertion for a specific table."""

    def __init__(self, table_name: str, original_error: Exception) -> None:
        self.table_name = table_name
        self.original_error = original_error
        super().__init__(f"{table_name}: {original_error}")


class PostLoadValidationError(Exception):
    """Raised when inserted data fails validation before commit."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def read_sources() -> dict[str, pd.DataFrame]:
    missing_files = [path for path in SOURCE_FILES.values() if not path.is_file()]
    if missing_files:
        missing_list = "\n".join(f"- {path}" for path in missing_files)
        raise PreflightError(f"Required source file(s) missing:\n{missing_list}")

    dataframes: dict[str, pd.DataFrame] = {}
    for table_name in LOAD_ORDER:
        dataframe = pd.read_csv(
            SOURCE_FILES[table_name],
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            encoding="utf-8-sig",
        )
        lowercase_columns = [column.lower() for column in dataframe.columns]
        if len(lowercase_columns) != len(set(lowercase_columns)):
            raise PreflightError(
                f"{SOURCE_FILES[table_name].name} contains duplicate lowercase columns."
            )
        dataframe.columns = lowercase_columns
        dataframes[table_name] = dataframe

    source_count_problems = [
        f"{table_name}: found {len(dataframes[table_name])}, "
        f"expected {EXPECTED_ROW_COUNTS[table_name]}"
        for table_name in LOAD_ORDER
        if len(dataframes[table_name]) != EXPECTED_ROW_COUNTS[table_name]
    ]
    if source_count_problems:
        raise PreflightError(
            "Unexpected source CSV row count(s):\n- "
            + "\n- ".join(source_count_problems)
        )

    return dataframes


def inspect_database_columns(
    cursor: psycopg.Cursor,
) -> dict[str, list[tuple[str, str]]]:
    cursor.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
        """,
        (list(LOAD_ORDER),),
    )

    columns_by_table: dict[str, list[tuple[str, str]]] = {
        table_name: [] for table_name in LOAD_ORDER
    }
    for table_name, column_name, data_type in cursor.fetchall():
        columns_by_table[table_name].append((column_name, data_type))
    return columns_by_table


def count_rows(cursor: psycopg.Cursor, table_name: str) -> int:
    cursor.execute(
        sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name))
    )
    return cursor.fetchone()[0]


def run_preflight(
    cursor: psycopg.Cursor,
    dataframes: dict[str, pd.DataFrame],
) -> dict[str, list[tuple[str, str]]]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_type = 'BASE TABLE'
          AND table_name = ANY(%s)
        """,
        (list(LOAD_ORDER),),
    )
    existing_tables = {row[0] for row in cursor.fetchall()}
    missing_tables = sorted(set(LOAD_ORDER) - existing_tables)
    if missing_tables:
        raise PreflightError(
            "Required PostgreSQL table(s) missing: " + ", ".join(missing_tables)
        )

    existing_row_counts = {
        table_name: count_rows(cursor, table_name) for table_name in LOAD_ORDER
    }
    nonempty_tables = {
        table_name: row_count
        for table_name, row_count in existing_row_counts.items()
        if row_count != 0
    }
    if nonempty_tables:
        details = "\n".join(
            f"- {table_name}: {row_count} row(s)"
            for table_name, row_count in nonempty_tables.items()
        )
        raise PreflightError(
            "Target table(s) already contain data. Nothing was inserted:\n" + details
        )

    database_columns = inspect_database_columns(cursor)
    column_problems: list[str] = []
    for table_name in LOAD_ORDER:
        csv_columns = set(dataframes[table_name].columns)
        table_columns = {name for name, _ in database_columns[table_name]}
        missing_in_database = sorted(csv_columns - table_columns)
        missing_in_csv = sorted(table_columns - csv_columns)
        if missing_in_database or missing_in_csv:
            details: list[str] = []
            if missing_in_database:
                details.append(
                    "CSV-only columns: " + ", ".join(missing_in_database)
                )
            if missing_in_csv:
                details.append(
                    "database-only columns: " + ", ".join(missing_in_csv)
                )
            column_problems.append(f"{table_name}: {'; '.join(details)}")

    if column_problems:
        raise PreflightError(
            "CSV/database column mismatch:\n- " + "\n- ".join(column_problems)
        )
    return database_columns


def convert_boolean(raw_value: str) -> bool:
    normalized = raw_value.casefold()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    raise ValueError("expected Yes, No, or blank")


def convert_value(raw_value: str, database_type: str) -> object:
    # A blank questionnaire/reference cell becomes SQL NULL. Legitimate codes
    # such as "0", "00", and "01" are nonblank and therefore remain values.
    if raw_value == "":
        return None
    if database_type in INTEGER_TYPES:
        return int(raw_value)
    if database_type in DECIMAL_TYPES:
        return Decimal(raw_value)
    if database_type == "boolean":
        return convert_boolean(raw_value)

    # TEXT, CHAR, and VARCHAR values stay exactly as read so leading-zero CBMS
    # codes are never converted to numbers or replaced with codebook labels.
    return raw_value


def converted_rows(
    table_name: str,
    dataframe: pd.DataFrame,
    database_columns: list[tuple[str, str]],
) -> list[tuple[object, ...]]:
    database_type_by_column = dict(database_columns)
    rows: list[tuple[object, ...]] = []

    for csv_row_number, row in enumerate(
        dataframe.itertuples(index=False, name=None), start=2
    ):
        converted_row: list[object] = []
        for column_name, raw_value in zip(dataframe.columns, row):
            try:
                converted_row.append(
                    convert_value(raw_value, database_type_by_column[column_name])
                )
            except (ValueError, InvalidOperation) as error:
                raise DataConversionError(
                    f"{table_name}, CSV row {csv_row_number}, column {column_name}, "
                    f"value {raw_value!r}: {error}"
                ) from error
        rows.append(tuple(converted_row))
    return rows


def insert_table(
    cursor: psycopg.Cursor,
    table_name: str,
    dataframe: pd.DataFrame,
    database_columns: list[tuple[str, str]],
) -> None:
    column_names = dataframe.columns.tolist()
    insert_statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(sql.Identifier(name) for name in column_names),
        sql.SQL(", ").join(sql.Placeholder() for _ in column_names),
    )
    rows = converted_rows(table_name, dataframe, database_columns)

    try:
        cursor.executemany(insert_statement, rows)
    except psycopg.Error as error:
        raise TableLoadError(table_name, error) from error


def duplicate_primary_key_groups(
    cursor: psycopg.Cursor, table_name: str, key_columns: tuple[str, ...]
) -> int:
    key_identifiers = sql.SQL(", ").join(
        sql.Identifier(column_name) for column_name in key_columns
    )
    query = sql.SQL(
        "SELECT COUNT(*) FROM ("
        "SELECT {keys} FROM {table} GROUP BY {keys} HAVING COUNT(*) > 1"
        ") AS duplicate_keys"
    ).format(keys=key_identifiers, table=sql.Identifier(table_name))
    cursor.execute(query)
    return cursor.fetchone()[0]


def validate_loaded_data(cursor: psycopg.Cursor) -> dict[str, object]:
    problems: list[str] = []
    row_counts = {
        table_name: count_rows(cursor, table_name) for table_name in LOAD_ORDER
    }
    for table_name, expected_count in EXPECTED_ROW_COUNTS.items():
        if row_counts[table_name] != expected_count:
            problems.append(
                f"{table_name} row count is {row_counts[table_name]}; "
                f"expected {expected_count}"
            )

    cursor.execute("SELECT COUNT(DISTINCT household_id) FROM households")
    unique_households = cursor.fetchone()[0]
    if unique_households != 500:
        problems.append(
            f"Unique household_id count is {unique_households}; expected 500"
        )

    cursor.execute("SELECT COUNT(DISTINCT member_id) FROM household_members")
    unique_members = cursor.fetchone()[0]
    if unique_members != 2043:
        problems.append(
            f"Unique household_members member_id count is {unique_members}; expected 2043"
        )

    cursor.execute("SELECT COUNT(DISTINCT member_id) FROM member_health")
    unique_health_members = cursor.fetchone()[0]
    if unique_health_members != 2043:
        problems.append(
            f"Unique member_health member_id count is {unique_health_members}; expected 2043"
        )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM household_members AS members
        LEFT JOIN households
          ON households.household_id = members.household_id
        WHERE households.household_id IS NULL
        """
    )
    missing_member_households = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM member_health AS health
        LEFT JOIN households
          ON households.household_id = health.household_id
        WHERE households.household_id IS NULL
        """
    )
    missing_health_households = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM member_health AS health
        LEFT JOIN household_members AS members
          ON members.member_id = health.member_id
        WHERE members.member_id IS NULL
        """
    )
    missing_health_members = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            (SELECT member_id FROM household_members
             EXCEPT
             SELECT member_id FROM member_health)
            UNION ALL
            (SELECT member_id FROM member_health
             EXCEPT
             SELECT member_id FROM household_members)
        ) AS unmatched_members
        """
    )
    unmatched_member_ids = cursor.fetchone()[0]

    if missing_member_households:
        problems.append(
            f"household_members has {missing_member_households} missing household reference(s)"
        )
    if missing_health_households:
        problems.append(
            f"member_health has {missing_health_households} missing household reference(s)"
        )
    if missing_health_members:
        problems.append(
            f"member_health has {missing_health_members} missing member reference(s)"
        )
    if unmatched_member_ids:
        problems.append(
            f"A-E and member_health differ by {unmatched_member_ids} MEMBER_ID value(s)"
        )

    duplicate_key_groups = {
        table_name: duplicate_primary_key_groups(
            cursor, table_name, PRIMARY_KEYS[table_name]
        )
        for table_name in LOAD_ORDER
    }
    total_duplicate_key_groups = sum(duplicate_key_groups.values())
    if total_duplicate_key_groups:
        duplicates = ", ".join(
            f"{table_name}={count}"
            for table_name, count in duplicate_key_groups.items()
            if count
        )
        problems.append(f"Duplicate primary-key groups found: {duplicates}")

    if problems:
        raise PostLoadValidationError(problems)

    return {
        "row_counts": row_counts,
        "unique_households": unique_households,
        "unique_members": unique_members,
        "unique_health_members": unique_health_members,
        "missing_member_households": missing_member_households,
        "missing_health_households": missing_health_households,
        "missing_health_members": missing_health_members,
        "unmatched_member_ids": unmatched_member_ids,
        "duplicate_key_groups": total_duplicate_key_groups,
    }


def print_success_report(validation: dict[str, object]) -> None:
    print("Tanglaw-Buhay D3 Data Load\n")
    print("Preflight:")
    print("Required files: PASS")
    print("Required tables: PASS")
    print("Target tables empty: PASS")
    print("Column compatibility: PASS\n")

    print("Rows loaded:")
    for table_name in LOAD_ORDER:
        print(f"{table_name}: {validation['row_counts'][table_name]}")

    household_references_pass = (
        validation["missing_member_households"] == 0
        and validation["missing_health_households"] == 0
    )
    member_references_pass = validation["missing_health_members"] == 0
    member_alignment_pass = validation["unmatched_member_ids"] == 0

    print("\nDatabase relationship validation:")
    print(
        f"Household references: {'PASS' if household_references_pass else 'FAIL'}"
    )
    print(f"Member references: {'PASS' if member_references_pass else 'FAIL'}")
    print(
        "A-E / health member alignment: "
        f"{'PASS' if member_alignment_pass else 'FAIL'}"
    )
    print(f"Duplicate primary keys: {validation['duplicate_key_groups']}\n")

    print("Transaction: COMMITTED\n")
    print("OVERALL RESULT: PASS")


def main() -> None:
    dataframes = read_sources()

    try:
        password = getpass("PostgreSQL password for tanglaw_system: ")
    except (EOFError, KeyboardInterrupt) as error:
        raise PreflightError("Password entry was cancelled.") from error

    connection: psycopg.Connection | None = None
    try:
        connection = psycopg.connect(**CONNECTION, password=password)
        with connection.cursor() as cursor:
            database_columns = run_preflight(cursor, dataframes)
            for table_name in LOAD_ORDER:
                insert_table(
                    cursor,
                    table_name,
                    dataframes[table_name],
                    database_columns[table_name],
                )
            validation = validate_loaded_data(cursor)
        connection.commit()
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()

    print_success_report(validation)


if __name__ == "__main__":
    try:
        main()
    except PreflightError as error:
        print("Tanglaw-Buhay D3 Data Load", file=sys.stderr)
        print("Preflight: FAIL", file=sys.stderr)
        print(f"ERROR: {error}", file=sys.stderr)
        print("No rows were inserted.", file=sys.stderr)
        sys.exit(1)
    except DataConversionError as error:
        print("Tanglaw-Buhay D3 Data Load", file=sys.stderr)
        print(f"Data conversion failed: {error}", file=sys.stderr)
        print("Transaction: ROLLED BACK", file=sys.stderr)
        sys.exit(1)
    except TableLoadError as error:
        print("Tanglaw-Buhay D3 Data Load", file=sys.stderr)
        print(f"Insert failed in table: {error.table_name}", file=sys.stderr)
        print(f"PostgreSQL error: {error.original_error}", file=sys.stderr)
        print("Transaction: ROLLED BACK", file=sys.stderr)
        sys.exit(1)
    except PostLoadValidationError as error:
        print("Tanglaw-Buhay D3 Data Load", file=sys.stderr)
        print("Post-load validation: FAIL", file=sys.stderr)
        for problem in error.problems:
            print(f"- {problem}", file=sys.stderr)
        print("Transaction: ROLLED BACK", file=sys.stderr)
        sys.exit(1)
    except (OSError, pd.errors.ParserError) as error:
        print("Tanglaw-Buhay D3 Data Load", file=sys.stderr)
        print(f"ERROR: {error}", file=sys.stderr)
        print("Transaction: ROLLED BACK", file=sys.stderr)
        sys.exit(1)
    except psycopg.Error as error:
        print("Tanglaw-Buhay D3 Data Load", file=sys.stderr)
        print(f"PostgreSQL error: {error}", file=sys.stderr)
        print("Transaction: ROLLED BACK", file=sys.stderr)
        sys.exit(1)
