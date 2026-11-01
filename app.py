from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
import time
import smtplib
import secrets

from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "online_exam_secret_key_2026"

DATABASE = os.path.join(os.path.dirname(__file__), "database.db")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

EXAM_DURATION = 600

# GMAIL CONFIGURATION
SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")


# DATABASE CONNECTION
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# CREATE DATABASE TABLES
def create_tables():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            option1 TEXT NOT NULL,
            option2 TEXT NOT NULL,
            option3 TEXT NOT NULL,
            option4 TEXT NOT NULL,
            answer TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT 'General'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            score INTEGER,
            total INTEGER,
            subject TEXT NOT NULL DEFAULT 'General'
        )
    """)

    columns = [
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(results)"
        ).fetchall()
    ]

    if "student_id" not in columns:
        cursor.execute(
            "ALTER TABLE results ADD COLUMN student_id INTEGER"
        )

    if "score" not in columns:
        cursor.execute(
            "ALTER TABLE results ADD COLUMN score INTEGER DEFAULT 0"
        )

    if "total" not in columns:
        cursor.execute(
            "ALTER TABLE results ADD COLUMN total INTEGER DEFAULT 0"
        )

    if "created_at" not in columns:
        cursor.execute(
            "ALTER TABLE results ADD COLUMN created_at TEXT"
        )

    question_columns = [row["name"] for row in cursor.execute("PRAGMA table_info(questions)").fetchall()]
    if "subject" not in question_columns:
        cursor.execute("ALTER TABLE questions ADD COLUMN subject TEXT NOT NULL DEFAULT 'General'")

    result_columns = [row["name"] for row in cursor.execute("PRAGMA table_info(results)").fetchall()]
    if "subject" not in result_columns:
        cursor.execute("ALTER TABLE results ADD COLUMN subject TEXT NOT NULL DEFAULT 'General'")

    conn.commit()
    conn.close()


create_tables()


# HOME PAGE
@app.route("/")
def home():
    return render_template("index.html")


# STUDENT REGISTRATION
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"].strip()
        email = request.form["email"].strip()
        password = generate_password_hash(
            request.form["password"]
        )

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO students (name, email, password)
                VALUES (?, ?, ?)
            """, (name, email, password))

            conn.commit()
            conn.close()

            return redirect("/login")

        except sqlite3.IntegrityError:
            conn.close()
            return "Email already registered!"

    return render_template("register.html")


# STUDENT LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"].strip()
        password = request.form["password"]

        conn = get_db()

        student = conn.execute(
            "SELECT * FROM students WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if student:

            stored_password = student["password"]

            try:
                valid = check_password_hash(
                    stored_password, password
                )
            except (ValueError, TypeError):
                valid = False

            # SUPPORT OLD PLAIN-TEXT PASSWORDS
            if not valid and stored_password == password:
                valid = True

            if valid:

                session.clear()

                session["student_id"] = student["id"]
                session["student_name"] = student["name"]
                session["student_email"] = student["email"]

                return redirect("/dashboard")

        return "Invalid email or password!"

    return render_template("login.html")


# STUDENT DASHBOARD
@app.route("/dashboard")
def dashboard():

    if "student_id" not in session:
        return redirect("/login")

    conn = get_db()

    results = conn.execute("""
        SELECT score, total, subject
        FROM results
        WHERE student_id = ?
        ORDER BY id DESC
    """, (session["student_id"],)).fetchall()
    subjects = conn.execute("SELECT DISTINCT subject FROM questions ORDER BY subject").fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        name=session["student_name"],
        results=results,
        subjects=subjects
    )


# STUDENT EXAM HISTORY
@app.route("/history")
def history():

    if "student_id" not in session:
        return redirect("/login")

    conn = get_db()

    results = conn.execute("""
        SELECT score, total, subject
        FROM results
        WHERE student_id = ?
        ORDER BY id DESC
    """, (session["student_id"],)).fetchall()

    conn.close()

    return render_template(
        "history.html",
        results=results
    )


# EXAMINATION PAGE
@app.route("/exam")
def exam():

    if "student_id" not in session:
        return redirect("/login")

    if session.get("result_saved"):
        session.pop("result_saved", None)
        session.pop("exam_start", None)
        session.pop("exam_subject", None)

    selected_subject = request.args.get("subject") or session.get("exam_subject")
    if not selected_subject:
        return redirect("/dashboard")
    session["exam_subject"] = selected_subject

    if "exam_start" not in session:
        session["exam_start"] = time.time()

    elapsed = time.time() - session["exam_start"]

    remaining = max(
        0,
        EXAM_DURATION - int(elapsed)
    )

    if remaining <= 0:
        return redirect("/exam_timeout")

    conn = get_db()

    questions = conn.execute(
        "SELECT * FROM questions WHERE subject = ? ORDER BY id",
        (selected_subject,)
    ).fetchall()

    conn.close()

    return render_template(
        "exam.html",
        questions=questions,
        name=session["student_name"],
        remaining=remaining,
        subject=selected_subject
    )


# SAVE RESULT
def save_result(score):

    conn = get_db()

    subject = session.get("exam_subject", "General")
    total = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE subject = ?", (subject,)
    ).fetchone()[0]

    conn.execute("""
        INSERT INTO results (student_id, score, total, subject)
        VALUES (?, ?, ?, ?)
    """, (
        session["student_id"], score, total, subject
    ))

    conn.commit()
    conn.close()

    return total


# SUBMIT EXAM
@app.route("/submit", methods=["POST"])
def submit():

    if "student_id" not in session:
        return redirect("/login")

    if session.get("result_saved"):
        return redirect("/history")

    start = session.get("exam_start")

    if start is None:
        return redirect("/exam")

    if time.time() - start >= EXAM_DURATION:
        return redirect("/exam_timeout")

    conn = get_db()

    questions = conn.execute(
        "SELECT * FROM questions WHERE subject = ?",
        (session.get("exam_subject", "General"),)
    ).fetchall()

    conn.close()

    score = 0

    for q in questions:

        selected = request.form.get(str(q["id"]))

        if selected == q["answer"]:
            score += 1

    total = save_result(score)

    session["result_saved"] = True
    session.pop("exam_start", None)

    return render_template(
        "result.html",
        score=score,
        total=total
    )


# EXAM TIMEOUT
@app.route("/exam_timeout")
def exam_timeout():

    if "student_id" not in session:
        return redirect("/login")

    if not session.get("result_saved"):

        total = save_result(0)
        session["result_saved"] = True

    else:
        conn = get_db()

        total = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE subject = ?",
            (session.get("exam_subject", "General"),)
        ).fetchone()[0]

        conn.close()

    session.pop("exam_start", None)

    return render_template(
        "result.html",
        score=0,
        total=total
    )


# ADMIN LOGIN
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:

            session.clear()
            session["admin"] = True

            return redirect("/admin")

        return "Invalid admin username or password!"

    return render_template("admin_login.html")


# ADMIN DASHBOARD
@app.route("/admin")
def admin():

    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db()

    questions = conn.execute(
        "SELECT * FROM questions ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return render_template(
        "admin.html",
        questions=questions
    )


# ADD QUESTION
@app.route("/add_question", methods=["POST"])
def add_question():

    if not session.get("admin"):
        return redirect("/admin_login")

    question = request.form["question"]
    option1 = request.form["option1"]
    option2 = request.form["option2"]
    option3 = request.form["option3"]
    option4 = request.form["option4"]
    answer = request.form["answer"]
    subject = request.form.get("subject", "General").strip() or "General"

    conn = get_db()

    conn.execute("""
        INSERT INTO questions
        (question, option1, option2, option3, option4, answer, subject)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        question, option1, option2, option3, option4, answer, subject
    ))

    conn.commit()
    conn.close()

    return redirect("/admin")


# DELETE QUESTION
@app.route("/delete_question/<int:id>")
def delete_question(id):

    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db()

    conn.execute(
        "DELETE FROM questions WHERE id = ?",
        (id,)
    )

    conn.commit()
    conn.close()

    return redirect("/admin")


# ADMIN RESULTS
@app.route("/admin_results")
def admin_results():

    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db()

    results = conn.execute("""
        SELECT
            results.id,
            students.name AS name,
            students.email AS email,
            results.score AS score,
            results.total AS total,
            results.subject AS subject
        FROM results
        LEFT JOIN students
        ON results.student_id = students.id
        ORDER BY results.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_results.html",
        results=results
    )


# FORGOT PASSWORD
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form["email"].strip()

        conn = get_db()

        student = conn.execute(
            "SELECT * FROM students WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if not student:
            return "Email not registered!"

        if not SMTP_EMAIL or not SMTP_PASSWORD:
            return "Email service is not configured!"

        otp = str(secrets.randbelow(900000) + 100000)

        msg = EmailMessage()

        msg["Subject"] = "Online Examination System - Password Reset"
        msg["From"] = SMTP_EMAIL
        msg["To"] = email

        msg.set_content(
            f"""
Hello {student['name']},

Your password reset OTP is: {otp}

This OTP is valid for 5 minutes.

Do not share this OTP with anyone.
"""
        )

        try:

            with smtplib.SMTP_SSL(
                "smtp.gmail.com", 465
            ) as server:

                server.login(
                    SMTP_EMAIL,
                    SMTP_PASSWORD
                )

                server.send_message(msg)

            session["reset_email"] = email
            session["reset_otp"] = otp
            session["otp_expiry"] = time.time() + 300
            session["otp_attempts"] = 0

            return redirect("/reset_password")

        except Exception as e:

            print("Email error:", e)
            return "Unable to send OTP. Please try again."

    return render_template("forgot_password.html")


# RESET PASSWORD
@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():

    if "reset_email" not in session:
        return redirect("/forgot_password")

    if request.method == "POST":

        entered_otp = request.form["otp"]
        new_password = request.form["password"]

        if time.time() > session.get("otp_expiry", 0):

            session.pop("reset_email", None)
            session.pop("reset_otp", None)
            session.pop("otp_expiry", None)

            return redirect("/forgot_password")

        if session.get("otp_attempts", 0) >= 5:
            session.pop("reset_email", None)
            session.pop("reset_otp", None)
            session.pop("otp_expiry", None)

            return "Too many incorrect attempts. Request a new OTP."

        if entered_otp != session.get("reset_otp"):

            session["otp_attempts"] = session.get("otp_attempts", 0) + 1

            return "Invalid OTP! Please try again."

        if len(new_password) < 8:
            return "Password must contain at least 8 characters."

        hashed_password = generate_password_hash(new_password)

        conn = get_db()

        conn.execute("""
            UPDATE students
            SET password = ?
            WHERE email = ?
        """, (
            hashed_password,
            session["reset_email"]
        ))

        conn.commit()
        conn.close()

        session.pop("reset_email", None)
        session.pop("reset_otp", None)
        session.pop("otp_expiry", None)
        session.pop("otp_attempts", None)

        return redirect("/login")

    return render_template("reset_password.html")


# LOGOUT
@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# START APPLICATION
if __name__ == "__main__":
    app.run(debug=True)