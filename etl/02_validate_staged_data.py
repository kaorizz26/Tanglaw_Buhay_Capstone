"""ETL Step 2: validate staged Tanglaw-Buhay data without changing it."""

from collections import Counter
from pathlib import Path
import re
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGED_DIRECTORY = PROJECT_ROOT / "data" / "staged"
REFERENCE_DIRECTORY = PROJECT_ROOT / "data" / "reference"

FILES = {
    "households": STAGED_DIRECTORY / "households_staged.csv",
    "members": STAGED_DIRECTORY / "household_members_staged.csv",
    "health": STAGED_DIRECTORY / "member_health_staged.csv",
    "definitions": REFERENCE_DIRECTORY / "variable_definitions.csv",
    "codebook": REFERENCE_DIRECTORY / "codebook_values.csv",
}

GENERATED_COLUMNS = {"HOUSEHOLD_ID", "MEMBER_ID"}
SINGLE_CODE_TYPES = {"yes_no_code", "coded_category"}


class ValidationError(Exception):
    """Raised when required validation inputs cannot be loaded."""


def read_csv_as_strings(path: Path) -> pd.DataFrame:
    """Preserve leading zeros and skipped questions exactly as stored."""
    return pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        encoding="utf-8-sig",
    )


def check_required_files() -> None:
    missing_files = [path for path in FILES.values() if not path.is_file()]
    if missing_files:
        missing_list = "\n".join(f"- {path}" for path in missing_files)
        raise ValidationError(f"Required file(s) missing:\n{missing_list}")


def get_column_values(
    variable_name: str, dataframes: tuple[pd.DataFrame, ...]
) -> pd.Series:
    matching_columns = [
        dataframe[variable_name]
        for dataframe in dataframes
        if variable_name in dataframe.columns
    ]
    if not matching_columns:
        return pd.Series(dtype="string")
    return pd.concat(matching_columns, ignore_index=True)


def validate_identifiers(
    households: pd.DataFrame,
    members: pd.DataFrame,
    health: pd.DataFrame,
) -> tuple[dict[str, int], list[str]]:
    issues: list[str] = []
    required_columns = {
        "households_staged.csv": (households, {"HOUSEHOLD_ID"}),
        "household_members_staged.csv": (
            members,
            {"HOUSEHOLD_ID", "MEMBER_ID", "LINE_NUMBER"},
        ),
        "member_health_staged.csv": (
            health,
            {"HOUSEHOLD_ID", "MEMBER_ID", "SECTION_L_LINE_NUMBER"},
        ),
    }

    for file_name, (dataframe, expected_columns) in required_columns.items():
        missing = sorted(expected_columns - set(dataframe.columns))
        if missing:
            issues.append(f"{file_name} is missing column(s): {', '.join(missing)}")

    stats = {
        "households": len(households),
        "members": len(members),
        "health_rows": len(health),
        "duplicate_household_ids": 0,
        "duplicate_member_ids_members": 0,
        "duplicate_member_ids_health": 0,
        "unmatched_members": 0,
        "invalid_household_references": 0,
        "member_id_format_mismatches": 0,
        "line_number_mismatches": 0,
    }

    if issues:
        return stats, issues

    blank_household_ids = {
        "households_staged.csv": int(households["HOUSEHOLD_ID"].eq("").sum()),
        "household_members_staged.csv": int(members["HOUSEHOLD_ID"].eq("").sum()),
        "member_health_staged.csv": int(health["HOUSEHOLD_ID"].eq("").sum()),
    }
    for file_name, blank_count in blank_household_ids.items():
        if blank_count:
            issues.append(f"{file_name} has {blank_count} blank HOUSEHOLD_ID value(s).")

    blank_member_ids = {
        "household_members_staged.csv": int(members["MEMBER_ID"].eq("").sum()),
        "member_health_staged.csv": int(health["MEMBER_ID"].eq("").sum()),
    }
    for file_name, blank_count in blank_member_ids.items():
        if blank_count:
            issues.append(f"{file_name} has {blank_count} blank MEMBER_ID value(s).")

    stats["duplicate_household_ids"] = int(
        households["HOUSEHOLD_ID"].duplicated().sum()
    )
    stats["duplicate_member_ids_members"] = int(members["MEMBER_ID"].duplicated().sum())
    stats["duplicate_member_ids_health"] = int(health["MEMBER_ID"].duplicated().sum())

    if stats["duplicate_household_ids"]:
        issues.append(
            f"households_staged.csv has {stats['duplicate_household_ids']} duplicate "
            "HOUSEHOLD_ID value(s)."
        )
    if stats["duplicate_member_ids_members"]:
        issues.append(
            "household_members_staged.csv has "
            f"{stats['duplicate_member_ids_members']} duplicate MEMBER_ID value(s)."
        )
    if stats["duplicate_member_ids_health"]:
        issues.append(
            "member_health_staged.csv has "
            f"{stats['duplicate_member_ids_health']} duplicate MEMBER_ID value(s)."
        )

    household_id_set = set(households.loc[households["HOUSEHOLD_ID"] != "", "HOUSEHOLD_ID"])
    invalid_member_households = ~members["HOUSEHOLD_ID"].isin(household_id_set)
    invalid_health_households = ~health["HOUSEHOLD_ID"].isin(household_id_set)
    stats["invalid_household_references"] = int(
        invalid_member_households.sum() + invalid_health_households.sum()
    )
    if stats["invalid_household_references"]:
        issues.append(
            f"Member files contain {stats['invalid_household_references']} HOUSEHOLD_ID "
            "reference(s) not found in households_staged.csv."
        )

    member_id_set = set(members.loc[members["MEMBER_ID"] != "", "MEMBER_ID"])
    health_member_id_set = set(health.loc[health["MEMBER_ID"] != "", "MEMBER_ID"])
    members_without_health = member_id_set - health_member_id_set
    health_without_members = health_member_id_set - member_id_set
    stats["unmatched_members"] = len(members_without_health) + len(health_without_members)
    if members_without_health:
        issues.append(
            f"{len(members_without_health)} MEMBER_ID value(s) in A-E have no Section L match."
        )
    if health_without_members:
        issues.append(
            f"{len(health_without_members)} MEMBER_ID value(s) in Section L have no A-E match."
        )

    expected_member_ids = (
        members["HOUSEHOLD_ID"] + "-M" + members["LINE_NUMBER"]
    )
    expected_health_ids = (
        health["HOUSEHOLD_ID"] + "-M" + health["SECTION_L_LINE_NUMBER"]
    )
    member_format_mismatches = members["MEMBER_ID"] != expected_member_ids
    health_format_mismatches = health["MEMBER_ID"] != expected_health_ids
    stats["member_id_format_mismatches"] = int(
        member_format_mismatches.sum() + health_format_mismatches.sum()
    )
    if stats["member_id_format_mismatches"]:
        issues.append(
            f"Found {stats['member_id_format_mismatches']} MEMBER_ID value(s) that do not "
            "match HOUSEHOLD_ID + '-M' + the two-digit line number."
        )

    # Compare line numbers by MEMBER_ID instead of relying only on current row order.
    member_line_map = (
        members.drop_duplicates("MEMBER_ID", keep="first")
        .set_index("MEMBER_ID")["LINE_NUMBER"]
    )
    health_line_map = (
        health.drop_duplicates("MEMBER_ID", keep="first")
        .set_index("MEMBER_ID")["SECTION_L_LINE_NUMBER"]
    )
    common_member_ids = member_line_map.index.intersection(health_line_map.index)
    stats["line_number_mismatches"] = int(
        (
            member_line_map.loc[common_member_ids]
            != health_line_map.loc[common_member_ids]
        ).sum()
    )
    if stats["line_number_mismatches"]:
        issues.append(
            f"Found {stats['line_number_mismatches']} corresponding MEMBER_ID value(s) "
            "with different A-E and Section L line numbers."
        )

    return stats, issues


def validate_variable_coverage(
    dataframes: tuple[pd.DataFrame, ...], definitions: pd.DataFrame
) -> tuple[int, list[str]]:
    original_columns = set().union(*(set(dataframe.columns) for dataframe in dataframes))
    original_columns -= GENERATED_COLUMNS
    defined_variables = set(definitions["variable_name"])
    missing_definitions = sorted(original_columns - defined_variables)
    return len(original_columns), missing_definitions


def validate_single_codes(
    dataframes: tuple[pd.DataFrame, ...],
    definitions: pd.DataFrame,
    codebook: pd.DataFrame,
) -> tuple[int, int, list[tuple[str, str]]]:
    original_columns = set().union(*(set(dataframe.columns) for dataframe in dataframes))
    translation_definitions = definitions[
        definitions["needs_translation"].str.casefold().eq("yes")
        & definitions["practical_type"].isin(SINGLE_CODE_TYPES)
        & definitions["variable_name"].isin(original_columns)
    ]
    variables = sorted(set(translation_definitions["variable_name"]))
    valid_mappings = set(zip(codebook["variable_name"], codebook["code"]))

    observed_code_count = 0
    unmapped_codes: list[tuple[str, str]] = []
    for variable_name in variables:
        observed_codes = sorted(
            set(
                get_column_values(variable_name, dataframes)
                .loc[lambda values: values != ""]
                .tolist()
            )
        )
        observed_code_count += len(observed_codes)
        for code in observed_codes:
            if (variable_name, code) not in valid_mappings:
                unmapped_codes.append((variable_name, code))

    return len(variables), observed_code_count, unmapped_codes


def validate_multi_select_codes(
    dataframes: tuple[pd.DataFrame, ...],
    definitions: pd.DataFrame,
    codebook: pd.DataFrame,
) -> tuple[int, Counter[tuple[str, str]]]:
    original_columns = set().union(*(set(dataframe.columns) for dataframe in dataframes))
    variables = sorted(
        set(
            definitions.loc[
                definitions["practical_type"].eq("multi_select_code")
                & definitions["variable_name"].isin(original_columns),
                "variable_name",
            ]
        )
    )
    valid_mappings = set(zip(codebook["variable_name"], codebook["code"]))
    selections_checked = 0
    unknown_selections: Counter[tuple[str, str]] = Counter()

    for variable_name in variables:
        values = get_column_values(variable_name, dataframes)
        for raw_value in values[values != ""]:
            # Multi-select codes are stored as concatenated letters (for example AEH).
            # Each character is validated separately without changing the stored value.
            for selection in raw_value:
                selections_checked += 1
                if (variable_name, selection) not in valid_mappings:
                    unknown_selections[(variable_name, selection)] += 1

    return selections_checked, unknown_selections


def validate_member_references(
    dataframes: tuple[pd.DataFrame, ...],
    definitions: pd.DataFrame,
    valid_member_ids: set[str],
) -> tuple[int, Counter[tuple[str, str, str, str]]]:
    member_reference_variables = sorted(
        set(
            definitions.loc[
                definitions["practical_type"].eq("member_reference"),
                "variable_name",
            ]
        )
    )
    references_checked = 0
    invalid_references: Counter[tuple[str, str, str, str]] = Counter()

    for dataframe in dataframes:
        if "HOUSEHOLD_ID" not in dataframe.columns:
            continue
        for variable_name in member_reference_variables:
            if variable_name not in dataframe.columns:
                continue
            nonblank_rows = dataframe.loc[
                dataframe[variable_name] != "", ["HOUSEHOLD_ID", variable_name]
            ]
            for household_id, reference in nonblank_rows.itertuples(index=False, name=None):
                references_checked += 1
                expected_member_id = f"{household_id}-M{reference}"
                if expected_member_id not in valid_member_ids:
                    invalid_references[
                        (variable_name, household_id, reference, expected_member_id)
                    ] += 1

    return references_checked, invalid_references


def validate_formats(
    members: pd.DataFrame,
    health: pd.DataFrame,
    definitions: pd.DataFrame,
) -> Counter[tuple[str, str, str]]:
    suspicious_values: Counter[tuple[str, str, str]] = Counter()
    two_digit_pattern = re.compile(r"\d{2}")

    for variable_name, dataframe in (
        ("LINE_NUMBER", members),
        ("SECTION_L_LINE_NUMBER", health),
    ):
        if variable_name not in dataframe.columns:
            continue
        for value in dataframe[variable_name]:
            if two_digit_pattern.fullmatch(value) is None:
                suspicious_values[
                    (variable_name, repr(value), "expected exactly two digits")
                ] += 1

    education_variable = "C05_CURRENT_GRADE_LEVEL"
    matching_definition = definitions.loc[
        definitions["variable_name"].eq(education_variable), "metadata_length"
    ]
    if education_variable in members.columns and not matching_definition.empty:
        expected_length_text = matching_definition.iloc[0]
        try:
            expected_length = int(expected_length_text)
        except ValueError:
            suspicious_values[
                (
                    education_variable,
                    repr(expected_length_text),
                    "metadata_length is not an integer",
                )
            ] += 1
        else:
            for value in members.loc[members[education_variable] != "", education_variable]:
                if len(value) != expected_length:
                    suspicious_values[
                        (
                            education_variable,
                            repr(value),
                            f"expected length {expected_length}",
                        )
                    ] += 1

    return suspicious_values


def print_problem_details(
    identifier_issues: list[str],
    missing_definitions: list[str],
    unmapped_codes: list[tuple[str, str]],
    invalid_references: Counter[tuple[str, str, str, str]],
    unknown_selections: Counter[tuple[str, str]],
    suspicious_values: Counter[tuple[str, str, str]],
) -> None:
    print("\nValidation problems:")

    for issue in identifier_issues:
        print(f"- {issue}")
    for variable_name in missing_definitions:
        print(f"- Missing variable definition: {variable_name}")
    for variable_name, code in unmapped_codes:
        print(f"- Unmapped code: {variable_name} = {code!r}")
    for (variable_name, selection), count in sorted(unknown_selections.items()):
        print(
            f"- Unknown multi-select code: {variable_name} = {selection!r} "
            f"({count} occurrence(s))"
        )
    for (
        variable_name,
        household_id,
        reference,
        expected_member_id,
    ), count in sorted(invalid_references.items()):
        print(
            f"- Invalid member reference: {variable_name}, HOUSEHOLD_ID={household_id!r}, "
            f"value={reference!r}, expected MEMBER_ID={expected_member_id!r} "
            f"({count} occurrence(s))"
        )
    for (variable_name, value, reason), count in sorted(suspicious_values.items()):
        print(
            f"- Suspicious format: {variable_name} = {value}; {reason} "
            f"({count} occurrence(s))"
        )


def main() -> None:
    check_required_files()

    households = read_csv_as_strings(FILES["households"])
    members = read_csv_as_strings(FILES["members"])
    health = read_csv_as_strings(FILES["health"])
    definitions = read_csv_as_strings(FILES["definitions"])
    codebook = read_csv_as_strings(FILES["codebook"])
    staged_dataframes = (households, members, health)

    required_definition_columns = {
        "variable_name",
        "practical_type",
        "needs_translation",
        "metadata_length",
    }
    missing_definition_columns = required_definition_columns - set(definitions.columns)
    if missing_definition_columns:
        raise ValidationError(
            "variable_definitions.csv is missing required column(s): "
            + ", ".join(sorted(missing_definition_columns))
        )

    required_codebook_columns = {"variable_name", "code"}
    missing_codebook_columns = required_codebook_columns - set(codebook.columns)
    if missing_codebook_columns:
        raise ValidationError(
            "codebook_values.csv is missing required column(s): "
            + ", ".join(sorted(missing_codebook_columns))
        )

    identifier_stats, identifier_issues = validate_identifiers(
        households, members, health
    )
    original_variable_count, missing_definitions = validate_variable_coverage(
        staged_dataframes, definitions
    )
    (
        translated_variables_checked,
        observed_codes_checked,
        unmapped_codes,
    ) = validate_single_codes(staged_dataframes, definitions, codebook)
    selections_checked, unknown_selections = validate_multi_select_codes(
        staged_dataframes, definitions, codebook
    )

    valid_member_ids = (
        set(members.loc[members["MEMBER_ID"] != "", "MEMBER_ID"])
        if "MEMBER_ID" in members.columns
        else set()
    )
    references_checked, invalid_references = validate_member_references(
        staged_dataframes, definitions, valid_member_ids
    )
    suspicious_values = validate_formats(members, health, definitions)

    identifier_passed = not identifier_issues
    overall_passed = not any(
        (
            identifier_issues,
            missing_definitions,
            unmapped_codes,
            unknown_selections,
            invalid_references,
            suspicious_values,
        )
    )

    print("Tanglaw-Buhay ETL Step 2 Validation\n")
    print("Files loaded: PASS\n")

    print("Identifier checks:")
    print(f"Households: {identifier_stats['households']}")
    print(f"Members: {identifier_stats['members']}")
    print(f"Member health rows: {identifier_stats['health_rows']}")
    print(
        f"Duplicate HOUSEHOLD_ID: {identifier_stats['duplicate_household_ids']}"
    )
    print(
        "Duplicate MEMBER_ID (A-E): "
        f"{identifier_stats['duplicate_member_ids_members']}"
    )
    print(
        "Duplicate MEMBER_ID (L): "
        f"{identifier_stats['duplicate_member_ids_health']}"
    )
    print(f"Unmatched members between A-E/L: {identifier_stats['unmatched_members']}")
    print(
        "Invalid household references: "
        f"{identifier_stats['invalid_household_references']}"
    )
    print(f"Identifier validation: {'PASS' if identifier_passed else 'FAIL'}\n")

    print("Reference validation:")
    print(f"Original variables checked: {original_variable_count}")
    print(f"Missing variable definitions: {len(missing_definitions)}\n")

    print("Codebook validation:")
    print(f"Variables requiring translation checked: {translated_variables_checked}")
    print(f"Observed codes checked: {observed_codes_checked}")
    print(f"Unmapped codes: {len(unmapped_codes)}\n")

    print("Member-reference validation:")
    print(f"References checked: {references_checked}")
    print(f"Invalid references: {sum(invalid_references.values())}\n")

    print("Multi-select validation:")
    print(f"Selections checked: {selections_checked}")
    print(f"Unknown selections: {sum(unknown_selections.values())}\n")

    print("Format validation:")
    print(
        "Suspicious leading-zero/code-format values: "
        f"{sum(suspicious_values.values())}\n"
    )

    print(f"OVERALL RESULT: {'PASS' if overall_passed else 'FAIL'}")

    if not overall_passed:
        print_problem_details(
            identifier_issues,
            missing_definitions,
            unmapped_codes,
            invalid_references,
            unknown_selections,
            suspicious_values,
        )
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, OSError, pd.errors.ParserError) as error:
        print("Tanglaw-Buhay ETL Step 2 Validation", file=sys.stderr)
        print("Files loaded: FAIL", file=sys.stderr)
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
