from functools import wraps
import hmac
import os

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


app = Flask(__name__)

database_url = os.getenv("DATABASE_URL")
secret_key = os.getenv("SECRET_KEY")
tanglaw_username = os.getenv("TANGLAW_USERNAME")
tanglaw_password = os.getenv("TANGLAW_PASSWORD")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Set the PostgreSQL connection string before running the application."
    )

missing_authentication_settings = [
    variable_name
    for variable_name, value in (
        ("SECRET_KEY", secret_key),
        ("TANGLAW_USERNAME", tanglaw_username),
        ("TANGLAW_PASSWORD", tanglaw_password),
    )
    if not value
]

if missing_authentication_settings:
    raise RuntimeError(
        "Missing required authentication environment variable(s): "
        + ", ".join(missing_authentication_settings)
    )

app.config["SECRET_KEY"] = secret_key
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)

HOUSEHOLDS_PER_PAGE = 15
HOUSEHOLD_FILTERS = {"all", "children", "seniors", "pwd"}

HOUSEHOLD_SUMMARY_CTE = """
    WITH member_summary AS (
        SELECT
            household_id,
            COUNT(member_id) AS member_count,
            COUNT(*) FILTER (WHERE a07_age BETWEEN 0 AND 17) AS children,
            COUNT(*) FILTER (WHERE a07_age BETWEEN 18 AND 59) AS adults,
            COUNT(*) FILTER (WHERE a07_age >= 60) AS seniors,
            MAX(
                CONCAT_WS(
                    ' ',
                    NULLIF(BTRIM(a01_first_name), ''),
                    NULLIF(BTRIM(a01_middle_name), ''),
                    NULLIF(BTRIM(a01_last_name), ''),
                    NULLIF(BTRIM(a01_suffix), '')
                )
            ) FILTER (WHERE a02_relation_to_hh_head = '01') AS household_head
        FROM household_members
        GROUP BY household_id
    )
"""

HOUSEHOLD_LIST_WHERE = """
    WHERE (
        :search = ''
        OR households.household_id ILIKE :search_pattern
        OR member_summary.household_head ILIKE :search_pattern
    )
    AND (
        :household_filter = 'all'
        OR (:household_filter = 'children' AND member_summary.children > 0)
        OR (:household_filter = 'seniors' AND member_summary.seniors > 0)
        OR (
            :household_filter = 'pwd'
            AND households.l15_with_pwd_member = '1'
        )
    )
"""


def login_required(view_function):
    """Redirect unauthenticated staff to the login page."""

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if session.get("authenticated") is not True:
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapped_view


@app.route("/")
def home():
    if session.get("authenticated") is True:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        submitted_username = request.form.get("username", "")
        submitted_password = request.form.get("password", "")

        valid_username = hmac.compare_digest(submitted_username, tanglaw_username)
        valid_password = hmac.compare_digest(submitted_password, tanglaw_password)

        if valid_username and valid_password:
            session.clear()
            session["authenticated"] = True
            return redirect(url_for("dashboard"))

        error = "Invalid username or password."

    return render_template("login.html", error=error), 401 if error else 200


def get_dashboard_data():
    """Return the approved dashboard aggregates using read-only SQL queries."""

    summary = db.session.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM households) AS total_households,
                (SELECT COUNT(*) FROM household_members) AS total_members,
                (
                    SELECT COUNT(DISTINCT household_id)
                    FROM household_members
                    WHERE a07_age BETWEEN 0 AND 17
                ) AS households_with_children,
                (
                    SELECT COUNT(DISTINCT household_id)
                    FROM household_members
                    WHERE a07_age >= 60
                ) AS households_with_seniors,
                (
                    SELECT COUNT(*)
                    FROM households
                    WHERE l15_with_pwd_member = '1'
                ) AS households_with_pwd_members
            """
        )
    ).mappings().one()

    age_counts = db.session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE a07_age BETWEEN 0 AND 17) AS children,
                COUNT(*) FILTER (WHERE a07_age BETWEEN 18 AND 59) AS adults,
                COUNT(*) FILTER (WHERE a07_age >= 60) AS seniors
            FROM household_members
            WHERE a07_age IS NOT NULL
            """
        )
    ).mappings().one()

    food_security_counts = db.session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE j01_worried = '1') AS worried,
                COUNT(*) FILTER (WHERE j04_skipped_meal = '1') AS skipped_meal,
                COUNT(*) FILTER (WHERE j06_ran_out_of_food = '1') AS ran_out_of_food,
                COUNT(*) FILTER (WHERE j07_hungry = '1') AS hungry
            FROM households
            """
        )
    ).mappings().one()

    summary_cards = [
        {"label": "Total Households", "value": summary["total_households"]},
        {"label": "Total Members", "value": summary["total_members"]},
        {
            "label": "Households with Children",
            "value": summary["households_with_children"],
        },
        {
            "label": "Households with Seniors",
            "value": summary["households_with_seniors"],
        },
        {
            "label": "Households with PWD Members",
            "value": summary["households_with_pwd_members"],
        },
    ]
    age_groups = [
        {"label": "Children", "value": age_counts["children"]},
        {"label": "Adults", "value": age_counts["adults"]},
        {"label": "Seniors", "value": age_counts["seniors"]},
    ]
    food_security = [
        {"label": "Worried about enough food", "value": food_security_counts["worried"]},
        {"label": "Skipped a meal", "value": food_security_counts["skipped_meal"]},
        {"label": "Ran out of food", "value": food_security_counts["ran_out_of_food"]},
        {"label": "Experienced hunger", "value": food_security_counts["hungry"]},
    ]
    return summary_cards, age_groups, food_security


def format_household_composition(children, adults, seniors):
    """Format only the non-zero age groups for one household."""

    groups = (
        (children, "Child", "Children"),
        (adults, "Adult", "Adults"),
        (seniors, "Senior", "Seniors"),
    )
    parts = [
        f"{count} {singular if count == 1 else plural}"
        for count, singular, plural in groups
        if count > 0
    ]
    return " · ".join(parts) if parts else "Age data unavailable"


def build_pagination_pages(current_page, total_pages):
    """Return a short page-number list with None representing an ellipsis."""

    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    visible_pages = sorted(
        {
            1,
            total_pages,
            max(1, current_page - 1),
            current_page,
            min(total_pages, current_page + 1),
        }
    )
    pagination_pages = []
    previous_page = None

    for page_number in visible_pages:
        if previous_page is not None and page_number - previous_page > 1:
            pagination_pages.append(None)
        pagination_pages.append(page_number)
        previous_page = page_number

    return pagination_pages


def get_household_records(search, household_filter, requested_page):
    """Return one page of household records using read-only SQL queries."""

    parameters = {
        "search": search,
        "search_pattern": f"%{search}%",
        "household_filter": household_filter,
    }

    total_households = db.session.execute(
        text(
            HOUSEHOLD_SUMMARY_CTE
            + """
            SELECT COUNT(*)
            FROM households
            JOIN member_summary
              ON member_summary.household_id = households.household_id
            """
            + HOUSEHOLD_LIST_WHERE
        ),
        parameters,
    ).scalar_one()

    total_pages = (
        (total_households + HOUSEHOLDS_PER_PAGE - 1) // HOUSEHOLDS_PER_PAGE
        if total_households
        else 0
    )
    current_page = min(requested_page, total_pages) if total_pages else 1
    offset = (current_page - 1) * HOUSEHOLDS_PER_PAGE

    result_rows = db.session.execute(
        text(
            HOUSEHOLD_SUMMARY_CTE
            + """
            SELECT
                households.household_id,
                member_summary.household_head,
                member_summary.member_count,
                member_summary.children,
                member_summary.adults,
                member_summary.seniors
            FROM households
            JOIN member_summary
              ON member_summary.household_id = households.household_id
            """
            + HOUSEHOLD_LIST_WHERE
            + """
            ORDER BY households.household_id ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            **parameters,
            "limit": HOUSEHOLDS_PER_PAGE,
            "offset": offset,
        },
    ).mappings()

    household_records = []
    for result_row in result_rows:
        household = dict(result_row)
        household["composition"] = format_household_composition(
            household["children"],
            household["adults"],
            household["seniors"],
        )
        household_records.append(household)

    return {
        "household_records": household_records,
        "total_households": total_households,
        "current_page": current_page,
        "total_pages": total_pages,
        "pagination_pages": build_pagination_pages(current_page, total_pages),
        "result_start": offset + 1 if household_records else 0,
        "result_end": offset + len(household_records),
    }


@app.route("/dashboard")
@login_required
def dashboard():
    try:
        summary_cards, age_groups, food_security = get_dashboard_data()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Dashboard data could not be retrieved.")
        return (
            render_template(
                "dashboard.html",
                dashboard_error=(
                    "Dashboard data could not be retrieved. Please try again later."
                ),
            ),
            503,
        )

    return render_template(
        "dashboard.html",
        summary_cards=summary_cards,
        age_groups=age_groups,
        food_security=food_security,
    )


@app.route("/households")
@login_required
def households():
    search = request.args.get("search", "").strip()
    household_filter = request.args.get("filter", "all").strip().lower()
    if household_filter not in HOUSEHOLD_FILTERS:
        household_filter = "all"

    requested_page = request.args.get("page", default=1, type=int)
    requested_page = max(requested_page or 1, 1)

    try:
        household_data = get_household_records(
            search,
            household_filter,
            requested_page,
        )
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Household records could not be retrieved.")
        return (
            render_template(
                "households.html",
                households_error=(
                    "Household records could not be retrieved. "
                    "Please try again later."
                ),
                search=search,
                household_filter=household_filter,
            ),
            503,
        )

    return render_template(
        "households.html",
        search=search,
        household_filter=household_filter,
        **household_data,
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/db-check")
def db_check():
    tables = [
        "households",
        "household_members",
        "member_health",
        "variable_definitions",
        "codebook_values",
    ]

    counts = {}

    for table in tables:
        count = db.session.execute(
            text(f"SELECT COUNT(*) FROM {table}")
        ).scalar()

        counts[table] = count

    return jsonify(counts)


if __name__ == "__main__":
    app.run(debug=True)
