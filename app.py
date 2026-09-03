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
