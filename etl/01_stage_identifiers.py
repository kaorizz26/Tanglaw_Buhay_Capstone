"""ETL Step 1: add stable synthetic household and member identifiers."""

from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIRECTORY_CANDIDATES = (
    PROJECT_ROOT / "data" / "raw_synthetic_data",
    # The current project folder uses a space before "data".
    PROJECT_ROOT / "data" / "raw_synthetic data",
)
STAGED_DIRECTORY = PROJECT_ROOT / "data" / "staged"


class ValidationError(Exception):
    """Raised when a critical staging validation fails."""


def find_raw_directory() -> Path:
    existing_directories = [path for path in RAW_DIRECTORY_CANDIDATES if path.is_dir()]

    if not existing_directories:
        expected = " or ".join(str(path) for path in RAW_DIRECTORY_CANDIDATES)
        raise ValidationError(f"Raw data directory not found. Expected {expected}.")

    if len(existing_directories) > 1:
        found = ", ".join(str(path) for path in existing_directories)
        raise ValidationError(f"Multiple raw data directories found: {found}")

    return existing_directories[0]


def identify_raw_files(raw_directory: Path) -> tuple[Path, Path, Path]:
    csv_paths = sorted(raw_directory.glob("*.csv"))
    if len(csv_paths) != 3:
        raise ValidationError(
            f"Expected exactly 3 raw CSV files in {raw_directory}, found {len(csv_paths)}."
        )

    household_files: list[Path] = []
    member_files: list[Path] = []
    health_files: list[Path] = []

    for csv_path in csv_paths:
        headers = set(pd.read_csv(csv_path, nrows=0).columns)

        if "SECTION_L_LINE_NUMBER" in headers:
            health_files.append(csv_path)
        elif "LINE_NUMBER" in headers:
            member_files.append(csv_path)
        elif "J01_WORRIED" in headers and "SECTION_O_LINE_NUMBER" in headers:
            # SECTION_O_LINE_NUMBER identifies a survey response detail; it is not a join key.
            household_files.append(csv_path)
        else:
            raise ValidationError(
                f"Could not identify dataset type from headers in {csv_path.name}."
            )

    if not (
        len(household_files) == len(member_files) == len(health_files) == 1
    ):
        raise ValidationError(
            "Could not identify exactly one household, one Section A-E, and one Section L CSV."
        )

    return household_files[0], member_files[0], health_files[0]


def read_raw_csv(csv_path: Path) -> pd.DataFrame:
    # All raw values stay as strings so codes such as "03" and "00010011"
    # retain their leading zeros. Empty/skipped fields also remain empty strings.
    return pd.read_csv(
        csv_path,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        encoding="utf-8-sig",
    )


def household_group_numbers(line_numbers: pd.Series, column_name: str) -> pd.Series:
    if line_numbers.empty:
        raise ValidationError(f"{column_name} has no member rows.")

    if line_numbers.iloc[0] != "01":
        raise ValidationError(f"The first {column_name} value must be '01'.")

    invalid_lines = ~line_numbers.str.fullmatch(r"\d{2}")
    if invalid_lines.any():
        first_bad_row = int(invalid_lines.idxmax()) + 2
        raise ValidationError(
            f"{column_name} must contain two-digit line numbers; "
            f"invalid value found at CSV row {first_bad_row}."
        )

    # In these synthetic files, each household's member list restarts at line
    # number "01". Each reset therefore marks the beginning of a new household.
    return line_numbers.eq("01").cumsum()


def make_household_ids(count: int) -> list[str]:
    return [f"HH{number:06d}" for number in range(1, count + 1)]


def validate_and_stage(
    households: pd.DataFrame,
    members: pd.DataFrame,
    health: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if "LINE_NUMBER" not in members.columns:
        raise ValidationError("Section A-E is missing LINE_NUMBER.")
    if "SECTION_L_LINE_NUMBER" not in health.columns:
        raise ValidationError("Section L is missing SECTION_L_LINE_NUMBER.")

    member_groups = household_group_numbers(members["LINE_NUMBER"], "LINE_NUMBER")
    health_groups = household_group_numbers(
        health["SECTION_L_LINE_NUMBER"], "SECTION_L_LINE_NUMBER"
    )

    household_count = len(households)
    member_count = len(members)
    health_count = len(health)
    member_group_count = int(member_groups.max())
    health_group_count = int(health_groups.max())

    if household_count != member_group_count:
        raise ValidationError(
            "Household row count does not equal the number of Section A-E household "
            f"groups ({household_count} != {member_group_count})."
        )
    if member_count != health_count:
        raise ValidationError(
            f"Section A-E and Section L row counts differ ({member_count} != {health_count})."
        )
    if not members["LINE_NUMBER"].equals(health["SECTION_L_LINE_NUMBER"]):
        raise ValidationError(
            "Section A-E LINE_NUMBER and Section L SECTION_L_LINE_NUMBER are not "
            "aligned row-for-row."
        )
    if health_group_count != member_group_count:
        raise ValidationError(
            "Section A-E and Section L contain different numbers of household groups "
            f"({member_group_count} != {health_group_count})."
        )

    member_group_sizes = member_groups.value_counts(sort=False).sort_index()
    health_group_sizes = health_groups.value_counts(sort=False).sort_index()
    if not member_group_sizes.equals(health_group_sizes):
        raise ValidationError(
            "Household-group member counts do not match between Section A-E and Section L."
        )

    household_ids = make_household_ids(household_count)
    if not household_ids or household_ids[0] != "HH000001":
        raise ValidationError("The first generated household ID is not HH000001.")
    if len(set(household_ids)) != household_count:
        raise ValidationError("Generated household IDs are not unique.")
    if household_ids != make_household_ids(household_count):
        raise ValidationError("Generated household IDs are not sequential.")

    member_household_ids = member_groups.map(
        lambda group_number: household_ids[int(group_number) - 1]
    )
    health_household_ids = health_groups.map(
        lambda group_number: household_ids[int(group_number) - 1]
    )
    member_ids = member_household_ids + "-M" + members["LINE_NUMBER"]
    health_member_ids = (
        health_household_ids + "-M" + health["SECTION_L_LINE_NUMBER"]
    )

    duplicate_member_ids = int(member_ids.duplicated().sum())
    if duplicate_member_ids:
        raise ValidationError(
            f"Generated {duplicate_member_ids} duplicate MEMBER_ID values."
        )
    if not member_ids.equals(health_member_ids):
        raise ValidationError(
            "Generated MEMBER_ID values do not align between Section A-E and Section L."
        )
    if not all(
        member_id.startswith(f"{household_id}-M")
        for household_id, member_id in zip(member_household_ids, member_ids)
    ):
        raise ValidationError("A generated MEMBER_ID does not belong to its HOUSEHOLD_ID.")

    households_staged = households.copy()
    households_staged.insert(0, "HOUSEHOLD_ID", household_ids)

    members_staged = members.copy()
    members_staged.insert(0, "HOUSEHOLD_ID", member_household_ids.to_list())
    members_staged.insert(1, "MEMBER_ID", member_ids.to_list())

    health_staged = health.copy()
    health_staged.insert(0, "HOUSEHOLD_ID", health_household_ids.to_list())
    health_staged.insert(1, "MEMBER_ID", health_member_ids.to_list())

    report = {
        "households": household_count,
        "members": member_count,
        "health_rows": health_count,
        "household_groups": member_group_count,
        "unique_household_ids": len(set(household_ids)),
        "unique_member_ids": member_ids.nunique(),
        "duplicate_member_ids": duplicate_member_ids,
    }
    return households_staged, members_staged, health_staged, report


def main() -> None:
    raw_directory = find_raw_directory()
    household_path, member_path, health_path = identify_raw_files(raw_directory)

    households = read_raw_csv(household_path)
    members = read_raw_csv(member_path)
    health = read_raw_csv(health_path)

    households_staged, members_staged, health_staged, report = validate_and_stage(
        households, members, health
    )

    # Raw files are source evidence and must never be overwritten. Staged copies
    # are written to a separate directory only after every validation has passed.
    STAGED_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_paths = (
        STAGED_DIRECTORY / "households_staged.csv",
        STAGED_DIRECTORY / "household_members_staged.csv",
        STAGED_DIRECTORY / "member_health_staged.csv",
    )

    households_staged.to_csv(output_paths[0], index=False, encoding="utf-8")
    members_staged.to_csv(output_paths[1], index=False, encoding="utf-8")
    health_staged.to_csv(output_paths[2], index=False, encoding="utf-8")

    print("ETL Step 1 completed successfully.\n")
    print(f"Households: {report['households']}")
    print(f"Members (A-E): {report['members']}")
    print(f"Member health rows (L): {report['health_rows']}")
    print(f"Household groups found: {report['household_groups']}")
    print(f"Unique HOUSEHOLD_IDs: {report['unique_household_ids']}")
    print(f"Unique MEMBER_IDs: {report['unique_member_ids']}")
    print("A-E / L line-number alignment: PASS")
    print("Household-group alignment: PASS")
    print(f"Duplicate MEMBER_IDs: {report['duplicate_member_ids']}\n")
    print("Staged files written to:")
    for output_path in output_paths:
        print(output_path.relative_to(PROJECT_ROOT).as_posix())


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, FileNotFoundError, OSError, pd.errors.ParserError) as error:
        print("ETL Step 1 failed.", file=sys.stderr)
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
