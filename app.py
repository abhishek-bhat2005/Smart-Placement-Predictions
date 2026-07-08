import os
import re
import sqlite3
try:
    from pymongo import MongoClient
except Exception:
    MongoClient = None
from functools import wraps
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")

DATA_PATH = "collegePlacement_cleanData.csv"
DB_PATH = "users.db"
MODEL = None
DATASET_ROWS = 0
STREAM_LABELS = {
    1: "Electronics",
    2: "Computer Science",
    3: "Information Technology",
    4: "Mechanical",
    5: "Electrical",
    6: "Civil",
}


def load_model():
    global MODEL, DATASET_ROWS
    df = pd.read_csv(DATA_PATH)
    features = ["Age", "Gender", "Stream", "Internships", "Hostel", "CGPA", "HistoryOfBacklogs"]
    target = "PlacedOrNot"
    X = df[features].values
    y = df[target].values
    model = DecisionTreeClassifier(random_state=42)
    model.fit(X, y)
    MODEL = model
    DATASET_ROWS = len(df)


class User:
    def __init__(self, username, email, password_hash, is_admin=False, last_login=None):
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.is_admin = bool(is_admin)
        self.last_login = last_login
        self.is_authenticated = True


def get_db_connection():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def use_mongo():
    return bool(os.environ.get("MONGO_URI")) and MongoClient is not None


def mongo_get_db():
    # return a database object; cache client in g
    if not use_mongo():
        return None
    if hasattr(g, "mongo_db") and getattr(g, "mongo_db") is not None:
        return g.mongo_db
    uri = os.environ.get("MONGO_URI")
    client = MongoClient(uri)
    # try to get default DB from URI, otherwise use 'placement_app'
    try:
        db = client.get_default_database()
        if db is None:
            db = client["placement_app"]
    except Exception:
        db = client["placement_app"]
    g.mongo_client = client
    g.mongo_db = db
    return db


def column_exists(conn, table_name, column_name):
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def create_default_admin(conn):
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@placementpro.com").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    row = conn.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    if not row:
        password_hash = generate_password_hash(admin_password)
        conn.execute(
            "INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, 1)",
            ("Administrator", admin_email, password_hash),
        )
        print(f"Created default admin: {admin_email}")


def create_default_admin_mongo():
    if not use_mongo():
        return
    db = mongo_get_db()
    users = db.users
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@placementpro.com").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    row = users.find_one({"email": admin_email})
    if not row:
        password_hash = generate_password_hash(admin_password)
        users.insert_one({"username": "Administrator", "email": admin_email, "password_hash": password_hash, "is_admin": True, "last_login": None})
        print(f"Created default admin in MongoDB: {admin_email}")


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
    # close mongo client if present
    mongo_client = g.pop("mongo_client", None)
    if mongo_client is not None:
        try:
            mongo_client.close()
        except Exception:
            pass


def init_db():
    # If MongoDB is configured, skip creating local SQLite schema
    if use_mongo():
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            last_login TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            name TEXT DEFAULT '',
            age INTEGER NOT NULL,
            gender INTEGER NOT NULL,
            stream INTEGER NOT NULL,
            internships INTEGER NOT NULL,
            hostel INTEGER NOT NULL,
            backlog INTEGER NOT NULL,
            cgpa REAL NOT NULL,
            prediction INTEGER NOT NULL,
            eligibility_notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor = conn.execute("PRAGMA table_info(predictions)")
    columns = [row[1] for row in cursor.fetchall()]
    if "name" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN name TEXT DEFAULT ''")
    if "eligibility_notes" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN eligibility_notes TEXT DEFAULT ''")

    cursor = conn.execute("PRAGMA table_info(users)")
    user_columns = [row[1] for row in cursor.fetchall()]
    if "is_admin" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if "last_login" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_login TIMESTAMP")
    conn.commit()
    create_default_admin(conn)
    conn.close()


# Initialize resources upon module import so Flask 3 compatibility is preserved.
init_db()
load_model()
# Do not create the default admin during module import — defer until an application
# context is available (avoids "Working outside of application context" errors).


@app.context_processor
def inject_user():
    user_email = session.get("user_email")
    if user_email:
        if use_mongo():
            mdb = mongo_get_db()
            row = mdb.users.find_one({"email": user_email})
            if row:
                return {"current_user": User(row.get("username"), row.get("email"), row.get("password_hash"), row.get("is_admin", False), row.get("last_login"))}
        else:
            db = get_db_connection()
            row = db.execute("SELECT username, email, password_hash, is_admin, last_login FROM users WHERE email = ?", (user_email,)).fetchone()
            if row:
                return {
                    "current_user": User(
                        row["username"], row["email"], row["password_hash"], row["is_admin"], row["last_login"]
                    )
                }
    return {"current_user": type("Anon", (), {"is_authenticated": False, "is_admin": False})()}


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_email"):
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def is_valid_email(email):
    email_regex = r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$"
    return re.match(email_regex, email) is not None


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user_email = session.get("user_email")
        if not user_email:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        if use_mongo():
            mdb = mongo_get_db()
            row = mdb.users.find_one({"email": user_email})
            if not row or not row.get("is_admin"):
                flash("Admin access required.", "danger")
                return redirect(url_for("dashboard"))
        else:
            db = get_db_connection()
            row = db.execute("SELECT is_admin FROM users WHERE email = ?", (user_email,)).fetchone()
            if not row or row["is_admin"] != 1:
                flash("Admin access required.", "danger")
                return redirect(url_for("dashboard"))
        return view_func(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
        elif not is_valid_email(email):
            flash("Please enter a valid email address.", "danger")
        elif password != confirm_password:
            flash("Passwords do not match.", "danger")
        else:
            if use_mongo():
                mdb = mongo_get_db()
                existing = mdb.users.find_one({"email": email})
                if existing:
                    flash("This email is already registered.", "danger")
                else:
                    password_hash = generate_password_hash(password)
                    mdb.users.insert_one({"username": username, "email": email, "password_hash": password_hash, "is_admin": False, "last_login": None})
                    session["user_email"] = email
                    flash("Registration successful. Welcome!", "success")
                    return redirect(url_for("dashboard"))
            else:
                db = get_db_connection()
                existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if existing:
                    flash("This email is already registered.", "danger")
                else:
                    password_hash = generate_password_hash(password)
                    db.execute(
                        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                        (username, email, password_hash),
                    )
                    db.commit()
                    session["user_email"] = email
                    flash("Registration successful. Welcome!", "success")
                    return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if use_mongo():
            mdb = mongo_get_db()
            row = mdb.users.find_one({"email": email})
            if not row or not check_password_hash(row.get("password_hash", ""), password):
                flash("Invalid email or password.", "danger")
            else:
                session["user_email"] = row["email"]
                mdb.users.update_one({"email": row["email"]}, {"$set": {"last_login": pd.Timestamp.now().to_pydatetime()}})
                flash("Login successful.", "success")
                return redirect(url_for("dashboard"))
        else:
            db = get_db_connection()
            row = db.execute(
                "SELECT username, email, password_hash FROM users WHERE email = ?",
                (email,),
            ).fetchone()

            if not row or not check_password_hash(row["password_hash"], password):
                flash("Invalid email or password.", "danger")
            else:
                session["user_email"] = row["email"]
                db.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE email = ?", (row["email"],))
                db.commit()
                flash("Login successful.", "success")
                return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_email", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


def get_user_predictions(user_email, limit=5):
    if use_mongo():
        mdb = mongo_get_db()
        cursor = mdb.predictions.find({"user_email": user_email}).sort("created_at", -1).limit(limit)
        # return list of dict-like objects
        return list(cursor)
    else:
        db = get_db_connection()
        rows = db.execute(
            "SELECT name, age, gender, stream, internships, hostel, backlog, cgpa, prediction, eligibility_notes, created_at "
            "FROM predictions WHERE user_email = ? ORDER BY created_at DESC LIMIT ?",
            (user_email, limit),
        ).fetchall()
        return rows


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    history = get_user_predictions(session["user_email"])
    return render_template(
        "dashboard.html",
        prediction=None,
        dataset_rows=DATASET_ROWS,
        history=history,
        stream_labels=STREAM_LABELS,
    )


@app.route("/predict-form", methods=["GET"])
@login_required
def predict_form():
    history = get_user_predictions(session["user_email"], limit=10)
    return render_template(
        "prediction_form.html",
        dataset_rows=DATASET_ROWS,
        stream_labels=STREAM_LABELS,
        history=history,
    )


def check_eligibility(age, cgpa, backlog):
    failures = []
    if age < 18 or age > 28:
        failures.append("Age should be between 18 and 28.")
    if cgpa < 6.0:
        failures.append("CGPA should be at least 6.0.")
    if backlog == 1:
        failures.append("No active backlogs are allowed.")
    return failures


@app.route("/predict", methods=["POST"])
@login_required
def predict():
    try:
        name = request.form.get("name", "").strip()
        age = int(request.form.get("age"))
        gender = int(request.form.get("gender"))
        stream = int(request.form.get("stream"))
        internships = int(request.form.get("internship"))
        hostel = int(request.form.get("hostel"))
        backlog = int(request.form.get("backlog"))
        cgpa = float(request.form.get("cgpa"))

        eligibility_failures = check_eligibility(age, cgpa, backlog)
        if eligibility_failures:
            prediction = 0
            eligibility_notes = "; ".join(eligibility_failures)
            display_message = "Not eligible for placements: " + eligibility_notes
        else:
            prediction = int(MODEL.predict([[age, gender, stream, internships, hostel, cgpa, backlog]])[0])
            eligibility_notes = "Standard eligibility met."
            display_message = "Eligible for placements" if prediction == 1 else "Not eligible for placements"

        if use_mongo():
            mdb = mongo_get_db()
            doc = {
                "user_email": session["user_email"],
                "name": name,
                "age": age,
                "gender": gender,
                "stream": stream,
                "internships": internships,
                "hostel": hostel,
                "backlog": backlog,
                "cgpa": cgpa,
                "prediction": int(prediction),
                "eligibility_notes": eligibility_notes,
                "created_at": pd.Timestamp.now().to_pydatetime(),
            }
            mdb.predictions.insert_one(doc)
        else:
            db = get_db_connection()
            db.execute(
                "INSERT INTO predictions (user_email, name, age, gender, stream, internships, hostel, backlog, cgpa, prediction, eligibility_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session["user_email"], name, age, gender, stream, internships, hostel, backlog, cgpa, prediction, eligibility_notes),
            )
            db.commit()

        history = get_user_predictions(session["user_email"])
        return render_template(
            "prediction_result.html",
            prediction=prediction,
            dataset_rows=DATASET_ROWS,
            history=history,
            display_message=display_message,
            eligibility_note=eligibility_notes,
            candidate_name=name,
            stream_labels=STREAM_LABELS,
        )
    except Exception:
        flash("Please provide valid input values.", "danger")
        return redirect(url_for("dashboard"))


@app.route("/admin")
@admin_required
def admin_panel():
    if use_mongo():
        mdb = mongo_get_db()
        users = list(mdb.users.find({}, {"password_hash": 0}).sort([("is_admin", -1), ("username", 1)]))
        stats_cursor = mdb.predictions.aggregate([
            {"$group": {"_id": "$user_email", "total_predictions": {"$sum": 1}, "last_prediction": {"$max": "$created_at"}}},
            {"$sort": {"last_prediction": -1}},
            {"$limit": 20},
        ])
        stats = list(stats_cursor)
        return render_template("admin.html", users=users, stats=stats)
    else:
        db = get_db_connection()
        users = db.execute(
            "SELECT username, email, is_admin, last_login FROM users ORDER BY is_admin DESC, username"
        ).fetchall()
        stats = db.execute(
            "SELECT user_email, COUNT(*) AS total_predictions, MAX(created_at) AS last_prediction "
            "FROM predictions GROUP BY user_email ORDER BY last_prediction DESC LIMIT 20"
        ).fetchall()
        return render_template("admin.html", users=users, stats=stats)


if __name__ == "__main__":
    load_model()
    # Ensure default admin in Mongo (if configured) runs inside app context
    with app.app_context():
        if use_mongo():
            create_default_admin_mongo()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
