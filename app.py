from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_from_directory, session
)
import sqlite3
import os
from pathlib import Path
from werkzeug.utils import secure_filename
from functools import wraps
from authlib.integrations.flask_client import OAuth
from community import community_bp, init_community_db


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "notes.db"

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt", "ppt", "pptx"}


# =========================
# FLASK APP
# =========================

app = Flask(__name__)
app.register_blueprint(community_bp)
init_community_db()
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1
)

# Change this before putting the website online
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

UPLOAD_DIR.mkdir(exist_ok=True)


# =========================
# GOOGLE OAUTH
# =========================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url=(
        "https://accounts.google.com/.well-known/"
        "openid-configuration"
    ),
    client_kwargs={
        "scope": "openid email profile"
    }
)


# =========================
# ADMIN LOGIN DETAILS
# =========================

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            class_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            topic TEXT,
            user_type TEXT NOT NULL,
            uploader_name TEXT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# =========================
# FILE CHECK
# =========================

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# =========================
# GOOGLE USER PROTECTION
# =========================

def user_required(view_function):

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):

        if not session.get("google_logged_in"):
            return redirect(url_for("user_login"))

        return view_function(*args, **kwargs)

    return wrapped_view


# =========================
# ADMIN PROTECTION
# =========================

def admin_required(view_function):

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):

        if not session.get("admin_logged_in"):
            flash("Please login as admin first.", "error")
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


# =========================
# HOME PAGE
# =========================

@app.route("/")
@user_required
def index():

    q = request.args.get("q", "").strip()
    class_name = request.args.get("class_name", "").strip()
    subject = request.args.get("subject", "").strip()
    user_type = request.args.get("user_type", "").strip()

    conn = get_db()

    query = "SELECT * FROM notes WHERE 1=1"
    params = []

    if q:

        query += """
            AND (
                title LIKE ?
                OR description LIKE ?
                OR topic LIKE ?
            )
        """

        like = f"%{q}%"

        params.extend([
            like,
            like,
            like
        ])

    if class_name:
        query += " AND class_name = ?"
        params.append(class_name)

    if subject:
        query += " AND subject = ?"
        params.append(subject)

    if user_type:
        query += " AND user_type = ?"
        params.append(user_type)

    query += " ORDER BY created_at DESC"

    notes = conn.execute(
        query,
        params
    ).fetchall()

    classes = [
        r["class_name"]
        for r in conn.execute(
            "SELECT DISTINCT class_name "
            "FROM notes ORDER BY class_name"
        ).fetchall()
    ]

    subjects = [
        r["subject"]
        for r in conn.execute(
            "SELECT DISTINCT subject "
            "FROM notes ORDER BY subject"
        ).fetchall()
    ]

    users = [
        r["user_type"]
        for r in conn.execute(
            "SELECT DISTINCT user_type "
            "FROM notes ORDER BY user_type"
        ).fetchall()
    ]

    conn.close()

    return render_template(
        "index.html",
        notes=notes,
        classes=classes,
        subjects=subjects,
        users=users,
        q=q,
        selected_class=class_name,
        selected_subject=subject,
        selected_user=user_type
    )

# =========================
# USER LOGIN PAGE
# =========================

@app.route("/user-login")
def user_login():
    return render_template("google_login.html")
# =========================
# GOOGLE LOGIN
# =========================

@app.route("/google-login")
def google_login():

    redirect_uri = url_for(
        "google_callback",
        _external=True
    )

    return google.authorize_redirect(
        redirect_uri,
        prompt="select_account"
    )


# =========================
# GOOGLE CALLBACK
# =========================

@app.route("/auth/google/callback")
def google_callback():

    try:

        token = google.authorize_access_token()

        user_info = token.get("userinfo")

        if not user_info:

            flash(
                "Could not get your Google account information.",
                "error"
            )

            return redirect(url_for("google_login"))

        session["google_logged_in"] = True

        session["google_user"] = {
            "name": user_info.get("name"),
            "email": user_info.get("email"),
            "picture": user_info.get("picture")
        }

        return redirect(url_for("index"))

    except Exception as e:

        print("Google login error:", e)

        flash(
            "Google login failed. Please try again.",
            "error"
        )

        return redirect(url_for("google_login"))


# =========================
# USER LOGOUT
# =========================

@app.route("/user-logout")
def user_logout():

    session.pop("google_logged_in", None)
    session.pop("google_user", None)

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("google_login"))


# =========================
# ADMIN LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if session.get("admin_logged_in"):
        return redirect(url_for("admin"))

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if (
            username == ADMIN_USERNAME
            and password == ADMIN_PASSWORD
        ):

            session["admin_logged_in"] = True
            session["admin_username"] = username

            flash(
                "Login successful!",
                "success"
            )

            return redirect(url_for("admin"))

        flash(
            "Invalid username or password.",
            "error"
        )

    return render_template("login.html")


# =========================
# ADMIN DASHBOARD
# =========================

@app.route("/admin")
@admin_required
def admin():

    conn = get_db()

    notes = conn.execute(
        "SELECT * FROM notes "
        "ORDER BY created_at DESC"
    ).fetchall()

    total_notes = conn.execute(
        "SELECT COUNT(*) FROM notes"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "admin.html",
        notes=notes,
        total_notes=total_notes
    )


# =========================
# ADMIN LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)

    flash(
        "Admin logged out.",
        "success"
    )

    return redirect(url_for("login"))


# =========================
# UPLOAD NOTE
# =========================

@app.route(
    "/upload",
    methods=["GET", "POST"]
)
@admin_required
def upload():

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        class_name = request.form.get(
            "class_name",
            ""
        ).strip()

        subject = request.form.get(
            "subject",
            ""
        ).strip()

        topic = request.form.get(
            "topic",
            ""
        ).strip()

        user_type = request.form.get(
            "user_type",
            ""
        ).strip()

        uploader_name = request.form.get(
            "uploader_name",
            ""
        ).strip()

        file = request.files.get("file")

        if not all([
            title,
            class_name,
            subject,
            user_type,
            file
        ]):

            flash(
                "Please fill all required fields "
                "and select a file.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        if not file.filename:

            flash(
                "Please select a file.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        if not allowed_file(
            file.filename
        ):

            flash(
                "Allowed files: PDF, DOC, DOCX, "
                "TXT, PPT and PPTX.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        original = secure_filename(
            file.filename
        )

        stored = (
            f"{title[:40].replace(' ', '_')}_"
            f"{original}"
        )

        stored = secure_filename(
            stored
        )

        file.save(
            UPLOAD_DIR / stored
        )

        conn = get_db()

        conn.execute("""
            INSERT INTO notes
            (
                title,
                description,
                class_name,
                subject,
                topic,
                user_type,
                uploader_name,
                filename,
                original_filename
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title,
            description,
            class_name,
            subject,
            topic,
            user_type,
            uploader_name,
            stored,
            original
        ))

        conn.commit()
        conn.close()

        flash(
            "Note uploaded successfully!",
            "success"
        )

        return redirect(
            url_for("admin")
        )

    return render_template(
        "upload.html"
    )


# =========================
# NOTE DETAILS
# =========================

@app.route(
    "/note/<int:note_id>"
)
@user_required
def note_detail(note_id):

    conn = get_db()

    note = conn.execute(
        "SELECT * FROM notes "
        "WHERE id = ?",
        (note_id,)
    ).fetchone()

    conn.close()

    if not note:
        return "Note not found", 404

    return render_template(
        "detail.html",
        note=note
    )


# =========================
# DOWNLOAD
# =========================

@app.route(
    "/download/<filename>"
)
@user_required
def download(filename):

    return send_from_directory(
        UPLOAD_DIR,
        filename,
        as_attachment=True
    )


# =========================
# DELETE NOTE
# =========================

@app.route(
    "/delete/<int:note_id>",
    methods=["POST"]
)
@admin_required
def delete(note_id):

    conn = get_db()

    note = conn.execute(
        "SELECT * FROM notes "
        "WHERE id = ?",
        (note_id,)
    ).fetchone()

    if note:

        path = (
            UPLOAD_DIR /
            note["filename"]
        )

        if path.exists():
            path.unlink()

        conn.execute(
            "DELETE FROM notes "
            "WHERE id = ?",
            (note_id,)
        )

        conn.commit()

        flash(
            "Note deleted.",
            "success"
        )

    conn.close()

    return redirect(
        url_for("admin")
    )


# =========================
# START APP
# =========================

init_db()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
