import os
import sqlite3
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "tasks.db")
SCHEMA   = os.path.join(BASE_DIR, "schema.sql")

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "dev-secret-key-change-this-in-production"
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Open a new database connection if there isn't one for the current context."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables from schema.sql if they don't already exist."""
    with app.app_context():
        db = get_db()
        with open(SCHEMA, "r") as f:
            db.executescript(f.read())
        db.commit()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.context_processor
def inject_globals():
    """Inject current_username and overdue_count into every template."""
    overdue_count = 0
    if session.get("user_id"):
        db = get_db()
        row = db.execute(
            "SELECT COUNT(*) AS c FROM tasks "
            "WHERE user_id = ? AND status != 'completed' "
            "AND due_date IS NOT NULL AND due_date < date('now')",
            (session["user_id"],),
        ).fetchone()
        overdue_count = row["c"] if row else 0
    return {
        "current_username": session.get("username"),
        "overdue_count": overdue_count,
    }


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/register", methods=("GET", "POST"))
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip()
        password = request.form["password"]
        confirm  = request.form["confirm_password"]

        error = None
        if not username:
            error = "Username is required."
        elif not email:
            error = "Email is required."
        elif not password:
            error = "Password is required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."

        if error is None:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, email, password_hash) "
                    "VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password)),
                )
                db.commit()
                flash("Account created! Please log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "Username or email already exists."

        flash(error, "error")

    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
@app.route("/", methods=("GET", "POST"))
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        db   = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        error = None
        if user is None:
            error = "Invalid username."
        elif not check_password_hash(user["password_hash"], password):
            error = "Invalid password."

        if error is None:
            session.clear()
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("dashboard"))

        flash(error, "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    db    = get_db()
    uid   = session["user_id"]
    today = date.today().isoformat()

    # ---- aggregate counts ----
    row = db.execute(
        """
        SELECT
            COUNT(*)                                                          AS total,
            SUM(CASE WHEN status = 'pending'     THEN 1 ELSE 0 END)          AS pending,
            SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END)          AS in_progress,
            SUM(CASE WHEN status = 'completed'   THEN 1 ELSE 0 END)          AS completed,
            SUM(CASE WHEN status != 'completed'
                      AND due_date IS NOT NULL
                      AND due_date < ? THEN 1 ELSE 0 END)                    AS overdue
        FROM tasks
        WHERE user_id = ?
        """,
        (today, uid),
    ).fetchone()
    counts = dict(row) if row else {}

    # ---- filters ----
    status_filter   = request.args.get("status",   "all")
    priority_filter = request.args.get("priority", "all")
    search_query    = request.args.get("q",        "").strip()
    sort_by         = request.args.get("sort",     "created_desc")

    query  = (
        "SELECT t.*, c.name AS category_name, c.color AS category_color "
        "FROM tasks t "
        "LEFT JOIN categories c ON t.category_id = c.id "
        "WHERE t.user_id = ?"
    )
    params = [uid]

    if status_filter != "all":
        query += " AND t.status = ?"
        params.append(status_filter)

    if priority_filter != "all":
        query += " AND t.priority = ?"
        params.append(priority_filter)

    if search_query:
        query += " AND (t.title LIKE ? OR t.description LIKE ?)"
        like = f"%{search_query}%"
        params.extend([like, like])

    sort_map = {
        "created_desc":  "t.created_at DESC",
        "created_asc":   "t.created_at ASC",
        "due_asc":       "CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END, t.due_date ASC",
        "due_desc":      "CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END, t.due_date DESC",
        "priority_desc": "CASE t.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END",
        "priority_asc":  "CASE t.priority WHEN 'low'  THEN 1 WHEN 'medium' THEN 2 ELSE 3 END",
    }
    query += " ORDER BY " + sort_map.get(sort_by, "t.created_at DESC")

    tasks = db.execute(query, params).fetchall()

    categories = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (uid,),
    ).fetchall()

    return render_template(
        "dashboard.html",
        tasks=tasks,
        counts=counts,
        categories=categories,
        status_filter=status_filter,
        priority_filter=priority_filter,
        search_query=search_query,
        sort_by=sort_by,
        today=today,
    )


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------

@app.route("/task/add", methods=("GET", "POST"))
@login_required
def add_task():
    db  = get_db()
    uid = session["user_id"]

    if request.method == "POST":
        title       = request.form["title"].strip()
        description = request.form.get("description", "").strip()
        priority    = request.form.get("priority", "medium")
        status      = request.form.get("status", "pending")
        due_date    = request.form.get("due_date") or None
        category_id = request.form.get("category_id") or None

        if not title:
            flash("Title is required.", "error")
        else:
            completed_at = (
                datetime.now().isoformat() if status == "completed" else None
            )
            db.execute(
                "INSERT INTO tasks "
                "(user_id, title, description, priority, status, due_date, "
                " category_id, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, title, description, priority, status,
                 due_date, category_id, completed_at),
            )
            db.commit()
            flash("Task created successfully!", "success")
            return redirect(url_for("dashboard"))

    categories = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (uid,),
    ).fetchall()
    return render_template("task_form.html", task=None, categories=categories)


@app.route("/task/<int:id>/edit", methods=("GET", "POST"))
@login_required
def edit_task(id):
    db  = get_db()
    uid = session["user_id"]
    task = db.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (id, uid)
    ).fetchone()

    if task is None:
        flash("Task not found.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title       = request.form["title"].strip()
        description = request.form.get("description", "").strip()
        priority    = request.form.get("priority", "medium")
        status      = request.form.get("status", "pending")
        due_date    = request.form.get("due_date") or None
        category_id = request.form.get("category_id") or None

        if not title:
            flash("Title is required.", "error")
        else:
            # Track completion timestamp
            completed_at = task["completed_at"]
            if status == "completed" and task["status"] != "completed":
                completed_at = datetime.now().isoformat()
            elif status != "completed":
                completed_at = None

            db.execute(
                "UPDATE tasks "
                "SET title=?, description=?, priority=?, status=?, "
                "    due_date=?, category_id=?, completed_at=? "
                "WHERE id=? AND user_id=?",
                (title, description, priority, status,
                 due_date, category_id, completed_at, id, uid),
            )
            db.commit()
            flash("Task updated successfully!", "success")
            return redirect(url_for("dashboard"))

    categories = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (uid,),
    ).fetchall()
    return render_template("task_form.html", task=task, categories=categories)


@app.route("/task/<int:id>/delete", methods=("POST",))
@login_required
def delete_task(id):
    db = get_db()
    db.execute(
        "DELETE FROM tasks WHERE id = ? AND user_id = ?",
        (id, session["user_id"]),
    )
    db.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/task/<int:id>/toggle", methods=("POST",))
@login_required
def toggle_task(id):
    """JSON endpoint — cycles pending → in_progress → completed → pending."""
    db  = get_db()
    uid = session["user_id"]
    task = db.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (id, uid)
    ).fetchone()

    if task is None:
        return jsonify({"error": "Task not found"}), 404

    cycle = {
        "pending":     "in_progress",
        "in_progress": "completed",
        "completed":   "pending",
    }
    new_status   = cycle.get(task["status"], "pending")
    completed_at = (
        datetime.now().isoformat() if new_status == "completed" else None
    )

    db.execute(
        "UPDATE tasks SET status = ?, completed_at = ? "
        "WHERE id = ? AND user_id = ?",
        (new_status, completed_at, id, uid),
    )
    db.commit()
    return jsonify({"status": new_status, "completed_at": completed_at})


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@app.route("/categories", methods=("GET", "POST"))
@login_required
def categories():
    db  = get_db()
    uid = session["user_id"]

    if request.method == "POST":
        name  = request.form["name"].strip()
        color = request.form.get("color", "#6366f1")

        if not name:
            flash("Category name is required.", "error")
        else:
            try:
                db.execute(
                    "INSERT INTO categories (user_id, name, color) "
                    "VALUES (?, ?, ?)",
                    (uid, name, color),
                )
                db.commit()
                flash("Category created!", "success")
            except sqlite3.IntegrityError:
                flash("A category with that name already exists.", "error")

        return redirect(url_for("categories"))

    cats = db.execute(
        """
        SELECT c.*, COUNT(t.id) AS task_count
        FROM categories c
        LEFT JOIN tasks t ON c.id = t.category_id
        WHERE c.user_id = ?
        GROUP BY c.id
        ORDER BY c.name
        """,
        (uid,),
    ).fetchall()

    return render_template("categories.html", categories=cats)


@app.route("/category/<int:id>/delete", methods=("POST",))
@login_required
def delete_category(id):
    db = get_db()
    db.execute(
        "DELETE FROM categories WHERE id = ? AND user_id = ?",
        (id, session["user_id"]),
    )
    db.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("categories"))


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@app.route("/profile", methods=("GET", "POST"))
@login_required
def profile():
    db  = get_db()
    uid = session["user_id"]

    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip()

        if not username or not email:
            flash("Username and email are required.", "error")
        else:
            try:
                db.execute(
                    "UPDATE users SET username = ?, email = ? WHERE id = ?",
                    (username, email, uid),
                )
                db.commit()
                session["username"] = username
                flash("Profile updated!", "success")
            except sqlite3.IntegrityError:
                flash("Username or email already taken.", "error")

        return redirect(url_for("profile"))

    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (uid,)
    ).fetchone()

    stats = db.execute(
        """
        SELECT
            COUNT(*)                                                   AS total_tasks,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)     AS completed_tasks,
            (SELECT COUNT(*) FROM categories WHERE user_id = ?)        AS categories_count
        FROM tasks
        WHERE user_id = ?
        """,
        (uid, uid),
    ).fetchone()

    stats_dict = dict(stats)
    total     = stats_dict.get("total_tasks", 0) or 0
    completed = stats_dict.get("completed_tasks", 0) or 0
    stats_dict["completion_rate"] = round(
        (completed / total * 100) if total > 0 else 0
    )

    return render_template("profile.html", user=user, stats=stats_dict)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
