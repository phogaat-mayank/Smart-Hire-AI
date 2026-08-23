import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from google import genai
import PyPDF2
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
import torch
from sqlalchemy import func, inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
import numpy as np

try:
    torch.set_num_threads(2)
except Exception:
    pass

try:
    import psycopg2.extensions
    psycopg2.extensions.register_adapter(np.float32, psycopg2.extensions.Float)
    psycopg2.extensions.register_adapter(np.float64, psycopg2.extensions.Float)
    psycopg2.extensions.register_adapter(np.int32, psycopg2.extensions.AsIs)
    psycopg2.extensions.register_adapter(np.int64, psycopg2.extensions.AsIs)
except Exception:
    pass

app = Flask(__name__)
load_dotenv()
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or "smart-hire-ai-secure-secret-key-2026"

gemini_key = os.getenv("GEMINI_API_KEY")
client = None
if gemini_key:
    try:
        client = genai.Client(api_key=gemini_key)
    except Exception as e:
        print("Gemini client initialization warning:", e)

# Load BERT Model
print("Loading BERT model...")
model = SentenceTransformer('all-MiniLM-L6-v2')
print("BERT model loaded successfully!")

# Database Config (Dynamic: PostgreSQL for Cloud, SQLite for Local)
database_url = os.getenv("DATABASE_URL", "sqlite:///results.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if database_url.startswith("postgresql"):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 5,
        'max_overflow': 10,
        'pool_pre_ping': True,
        'pool_recycle': 280,
    }

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resumes = db.relationship("ResumeResult", backref="owner", lazy=True, cascade="all, delete-orphan")
    job_descriptions = db.relationship("JobDescription", backref="owner", lazy=True, cascade="all, delete-orphan")
    interview_sessions = db.relationship("InterviewSession", backref="owner", lazy=True, cascade="all, delete-orphan")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Database Tables
class ResumeResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    candidate_name = db.Column(db.String(100))
    filename = db.Column(db.String(200))

    match_score = db.Column(db.Float)
    ats_score = db.Column(db.Float)

    matched_skills = db.Column(db.Text)
    missing_skills = db.Column(db.Text)

    resume_summary = db.Column(db.Text)
    recommendation = db.Column(db.String(50))
    resume_text = db.Column(db.Text)
    ai_interview = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class JobDescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    job_description = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class InterviewSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("resume_result.id"), nullable=False)
    questions = db.Column(db.Text, nullable=False)
    answers = db.Column(db.Text, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    candidate = db.relationship("ResumeResult", backref=db.backref("candidate_interview_sessions", cascade="all, delete-orphan"))


with app.app_context():
    try:
        db.create_all()
        inspector = inspect(db.engine)
        for table_name in ("resume_result", "job_description", "interview_session"):
            if inspector.has_table(table_name):
                columns = {col["name"] for col in inspector.get_columns(table_name)}
                if "owner_id" not in columns:
                    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN owner_id INTEGER"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Database startup notice:", e)


@app.teardown_appcontext
def shutdown_session(exception=None):
    if exception:
        db.session.rollback()
    db.session.remove()


# Helper function for safe redirect URLs
def is_safe_url(target):
    if not target:
        return False
    return target.startswith("/") and not target.startswith("//") and not target.startswith("/\\")


def get_reset_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])


def generate_reset_token(email):
    serializer = get_reset_serializer()
    return serializer.dumps(email, salt="smart-hire-password-reset")


def verify_reset_token(token, expiration=3600):
    serializer = get_reset_serializer()
    try:
        email = serializer.loads(token, salt="smart-hire-password-reset", max_age=expiration)
        return email
    except (SignatureExpired, BadSignature, Exception):
        return None


# Skills List
skills_list = [
    "python", "java", "c++", "c", "javascript", "html", "css",
    "react", "node.js", "flask", "django", "fastapi",
    "sql", "mysql", "postgresql", "mongodb",
    "machine learning", "deep learning", "data science",
    "artificial intelligence", "nlp", "computer vision",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch",
    "git", "github", "docker", "kubernetes",
    "aws", "azure", "gcp",
    "power bi", "excel", "tableau",
    "linux", "rest api"
]


# Extract required skills from Job Description
def extract_jd_skills(job_description):
    jd_text = job_description.lower()
    jd_skills = []

    for skill in skills_list:
        if skill.lower() in jd_text:
            jd_skills.append(skill)

    return jd_skills


# Function to Extract Text from PDF
def extract_text_from_pdf(file):
    try:
        reader = PyPDF2.PdfReader(file)
        text = ""
        for page in reader.pages[:4]:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        print("PDF extraction error:", e)
        return ""


def build_candidate_report(candidate):
    """Create a downloadable PDF screening report for one candidate."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=44, leftMargin=44, topMargin=44, bottomMargin=44
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontSize=24, leading=29,
        textColor=colors.HexColor("#1D4ED8"), spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="SectionTitle", parent=styles["Heading2"], fontSize=14, leading=18,
        textColor=colors.HexColor("#1E3A8A"), spaceBefore=16, spaceAfter=8
    ))
    story = [
        Paragraph("Smart-Hire AI", styles["ReportTitle"]),
        Paragraph("Candidate Screening Report", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph(f"<b>Candidate:</b> {escape(candidate.candidate_name)}", styles["BodyText"]),
        Paragraph(f"<b>Resume file:</b> {escape(candidate.filename)}", styles["BodyText"]),
        Paragraph(f"<b>Generated:</b> {candidate.created_at.strftime('%d %b %Y, %I:%M %p')}", styles["BodyText"]),
        Spacer(1, 14),
    ]
    score_table = Table([
        ["Match Score", "ATS Score", "Recommendation"],
        [f"{candidate.match_score:.3f}%", f"{candidate.ats_score:.3f}%", candidate.recommendation]
    ], colWidths=[1.65 * inch, 1.65 * inch, 2.1 * inch])
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1D4ED8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#EFF6FF")),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([score_table, Paragraph("AI Resume Summary", styles["SectionTitle"])])
    for line in (candidate.resume_summary or "Summary unavailable.").splitlines():
        cleaned_line = line.strip().lstrip("-• ")
        if cleaned_line:
            story.append(Paragraph(f"- {escape(cleaned_line)}", styles["BodyText"]))
    story.extend([
        Paragraph("Matched Skills", styles["SectionTitle"]),
        Paragraph(escape(candidate.matched_skills or "No matched skills found."), styles["BodyText"]),
        Paragraph("Missing Skills", styles["SectionTitle"]),
        Paragraph(escape(candidate.missing_skills or "No missing skills found."), styles["BodyText"]),
    ])
    document.build(story)
    buffer.seek(0)
    return buffer


def generate_resume_summary(resume_text):
    if not client:
        return "AI summary is temporarily unavailable (Gemini API key not configured)."

    prompt = f"""
You are an HR Recruiter.

Read the resume and write a professional summary in exactly 4 concise bullet points.

Resume:
{resume_text}
"""
    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print("Gemini summary error:", e)
        return "AI summary is temporarily unavailable."


def load_interview_questions():
    with open("questions/interview_questions.txt", "r", encoding="utf-8") as file:
        questions = [line.strip() for line in file if line.strip()]
    return questions


def generate_interview_answers(resume_text, questions, job_description=""):
    """Answer every submitted question, processing in small batches for reliability."""
    all_answers = []

    for start in range(0, len(questions), 5):
        batch = questions[start:start + 5]
        numbered_questions = "\n".join(
            f"{number}. {question}"
            for number, question in enumerate(batch, start=start + 1)
        )
        prompt = f"""
You are an AI recruitment assistant. Answer every recruiter question using the
candidate resume AND the job description. For evaluation questions such as "Is this
candidate suitable?", compare matched skills, missing requirements, relevant
experience, and the candidate's ATS score. Clearly state a recommendation and why.
For "missing skills" questions, identify requirements in the job description that
are absent from the resume. Do not invent facts; when evidence is absent, say
"Not mentioned in the resume." Keep answers concise, with at most 4 short bullet
points if a list is useful.

Job Description:
{job_description}

Candidate Resume:
{resume_text}

Recruiter Questions:
{numbered_questions}

Return ONLY valid JSON array. Every item must have these keys:
[{{"question":"...","answer":"...","evidence":"...","status":"matched|partial|missing"}}]
"""
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt
            )
            text_resp = response.text.strip().replace("```json", "").replace("```", "").strip()
            answers = json.loads(text_resp)
            if not isinstance(answers, list) or len(answers) != len(batch):
                raise ValueError("Expected one answer for every question")
            for question, answer in zip(batch, answers):
                all_answers.append({
                    "question": answer.get("question") or question,
                    "answer": answer.get("answer") or "Not mentioned in the resume.",
                    "evidence": answer.get("evidence") or "No supporting evidence found.",
                    "status": answer.get("status") or "missing"
                })
        except Exception as error:
            print("Batch interview answer error:", error)
            all_answers.extend({
                "question": question,
                "answer": "AI answer is temporarily unavailable for this question.",
                "evidence": "Please try again.",
                "status": "missing"
            } for question in batch)

    return all_answers


def is_valid_interview_question(text_q):
    """Require an actual interview-style question instead of arbitrary text."""
    normalized = re.sub(r"\s+", " ", text_q).strip()
    question_starters = (
        "what", "why", "when", "where", "who", "which", "how", "is ", "are ",
        "does", "do ", "can", "could", "would", "should", "will", "has", "have",
        "explain", "describe", "compare", "evaluate", "assess", "identify", "list",
        "kya", "kyu", "kaise", "batao", "samjhao"
    )
    return (
        len(normalized) >= 8
        and any(character.isalpha() for character in normalized)
        and ("?" in normalized or normalized.lower().startswith(question_starters))
    )


# ================= AUTHENTICATION ROUTES =================

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name:
            flash("Full name is required.", "danger")
            return render_template("register.html", name=name, email=email)

        if not email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            flash("Please enter a valid email address.", "danger")
            return render_template("register.html", name=name, email=email)

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template("register.html", name=name, email=email)

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html", name=name, email=email)

        existing_user = User.query.filter(func.lower(User.email) == email).first()
        if existing_user:
            flash("An account with this email already exists. Please log in.", "warning")
            return redirect(url_for("login"))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f"Welcome to Smart-Hire AI, {user.name}! Your account is ready.", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        if not email or not password:
            flash("Please provide both email and password.", "danger")
            return render_template("login.html", email=email)

        user = User.query.filter(func.lower(User.email) == email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            flash(f"Welcome back, {user.name}!", "success")
            next_url = request.args.get("next")
            if next_url and is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("index"))
        else:
            flash("Invalid email or password. Please try again.", "danger")
            return render_template("login.html", email=email)

    return render_template("login.html")


@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    reset_url = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            flash("Please enter a valid email address.", "danger")
            return render_template("forgot_password.html", email=email)

        user = User.query.filter(func.lower(User.email) == email).first()
        if user:
            token = generate_reset_token(user.email)
            reset_url = url_for("reset_password", token=token)
            flash("Password reset link has been generated! Use the link below to set a new password.", "success")
        else:
            flash("No account found with this email address. Please check your email or register.", "warning")

        return render_template("forgot_password.html", email=email, reset_url=reset_url)

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    email = verify_reset_token(token)
    if not email:
        flash("The password reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password"))

    user = User.query.filter(func.lower(User.email) == email.lower()).first()
    if not user:
        flash("User account not found. Please register or try again.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template("reset_password.html", token=token, email=email)

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("reset_password.html", token=token, email=email)

        user.password_hash = generate_password_hash(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Your password has been successfully reset! You are now signed in.", "success")
        return redirect(url_for("index"))

    return render_template("reset_password.html", token=token, email=email)


# ================= MAIN APPLICATION ROUTES =================

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    results = []

    if request.method == "POST":
        try:
            resume_files = request.files.getlist("resume")
            job_description = request.form.get("job_description", "").strip()

            if not job_description:
                flash("Please enter a job description to screen resumes against.", "danger")
                candidates = ResumeResult.query.filter_by(owner_id=current_user.id).order_by(ResumeResult.created_at.desc()).all()
                return render_template("index.html", results=results, candidates=candidates)

            jd = JobDescription(
                job_description=job_description,
                owner_id=current_user.id
            )
            db.session.add(jd)
            db.session.commit()
            jd_skills = extract_jd_skills(job_description)

            resume_texts = []
            file_names = []

            # Extract text from all resumes
            for file in resume_files:
                if not file or not file.filename:
                    continue
                resume_text = extract_text_from_pdf(file)
                if resume_text and resume_text.strip():
                    print(f"Processing: {file.filename}")
                    resume_texts.append(resume_text[:3000])
                    file_names.append(file.filename)

            if not resume_texts:
                flash("No readable text found in the uploaded resume(s). Please upload text-based PDFs.", "warning")
            else:
                # Fast parallel AI summary generation
                print(f"Generating AI Summaries in parallel for {len(resume_texts)} resumes...")
                with ThreadPoolExecutor(max_workers=min(len(resume_texts), 5)) as executor:
                    summaries = list(executor.map(generate_resume_summary, resume_texts))

                # Batch BERT Encoding with torch inference mode
                with torch.inference_mode():
                    resume_embeddings = model.encode(resume_texts, batch_size=8, show_progress_bar=False)
                    jd_embedding = model.encode(job_description, show_progress_bar=False)

                resume_objects = []
                scores = []
                ats_scores = []
                matched_skills_list = []
                missing_skills_list = []

                # Process each resume
                for i, resume_embedding in enumerate(resume_embeddings):
                    similarity = cosine_similarity(
                        [resume_embedding],
                        [jd_embedding]
                    )

                    score = float(round(float(similarity[0][0]) * 100, 3))
                    resume_text_lower = resume_texts[i].lower()

                    matched_skills = [
                        skill for skill in jd_skills
                        if skill in resume_text_lower
                    ]

                    missing_skills = [
                        skill for skill in jd_skills
                        if skill not in matched_skills
                    ]
                    ats_score = float(round((score * 0.7) + (len(matched_skills) * 3), 3))
                    if ats_score > 100.0:
                        ats_score = 100.0

                    scores.append(score)
                    ats_scores.append(ats_score)
                    matched_skills_list.append(matched_skills)
                    missing_skills_list.append(missing_skills)

                    resume_result = ResumeResult(
                        candidate_name=file_names[i].replace(".pdf", ""),
                        filename=file_names[i],
                        match_score=score,
                        ats_score=ats_score,
                        matched_skills=", ".join(matched_skills),
                        missing_skills=", ".join(missing_skills),
                        resume_summary=summaries[i],
                        resume_text=resume_texts[i],
                        recommendation="Selected" if score >= 75 else "Rejected",
                        owner_id=current_user.id
                    )

                    db.session.add(resume_result)
                    resume_objects.append(resume_result)

                # Single bulk database commit for maximum speed
                db.session.commit()

                for i, rr in enumerate(resume_objects):
                    results.append((
                        file_names[i],
                        scores[i],
                        ats_scores[i],
                        matched_skills_list[i],
                        missing_skills_list[i],
                        rr.id
                    ))

                # Sort by score descending
                results.sort(key=lambda x: x[1], reverse=True)
                print("Analysis completed successfully in batch!")

        except Exception as e:
            db.session.rollback()
            results = []
            print("Error in resume analysis POST handler:", e)
            flash(f"Error processing resumes: {e}", "danger")

    candidates = ResumeResult.query.filter_by(owner_id=current_user.id).order_by(ResumeResult.created_at.desc()).all()
    return render_template("index.html", results=results, candidates=candidates)


@app.route("/api/interview-answer", methods=["POST"])
@login_required
def interview_answer():
    payload = request.get_json(silent=True) or {}
    candidate_id = payload.get("candidate_id")
    raw_questions = payload.get("questions") or []

    if isinstance(raw_questions, str):
        raw_questions = raw_questions.splitlines()
    questions = [str(question).strip() for question in raw_questions if str(question).strip()]

    if not candidate_id or not questions:
        return jsonify({"error": "Please select a candidate and enter at least one question."}), 400

    invalid_questions = [question for question in questions if not is_valid_interview_question(question)]
    if invalid_questions:
        return jsonify({
            "error": "Only interview questions are allowed. Add a question mark or begin with words like What, Why, How, Explain, Evaluate, or Kya.",
            "invalid_questions": invalid_questions
        }), 400

    candidate = ResumeResult.query.filter_by(id=candidate_id, owner_id=current_user.id).first()
    if not candidate:
        return jsonify({"error": "Selected candidate was not found."}), 404

    latest_jd = JobDescription.query.filter_by(owner_id=current_user.id).order_by(JobDescription.created_at.desc()).first()
    job_context = latest_jd.job_description if latest_jd else ""
    job_context += (
        f"\n\nScreening Metrics:\nMatch Score: {candidate.match_score:.3f}%"
        f"\nATS Score: {candidate.ats_score:.3f}%"
        f"\nMatched Skills: {candidate.matched_skills or 'None'}"
        f"\nMissing Skills: {candidate.missing_skills or 'None'}"
    )
    answers = generate_interview_answers(
        candidate.resume_text,
        questions,
        job_context
    )

    if not answers:
        return jsonify({"error": "AI answer is temporarily unavailable. Please try again."}), 502

    interview_session = InterviewSession(
        candidate_id=candidate.id,
        questions=json.dumps(questions),
        answers=json.dumps(answers),
        owner_id=current_user.id
    )
    db.session.add(interview_session)
    db.session.commit()

    return jsonify({
        "candidate": candidate.candidate_name,
        "answers": answers,
        "history_id": interview_session.id
    })


@app.route("/history")
@login_required
def history():
    history_records = ResumeResult.query.filter_by(
        owner_id=current_user.id
    ).order_by(
        ResumeResult.created_at.desc()
    ).all()

    total_resumes = len(history_records)
    average_ats = 0
    highest_match = 0
    selected = 0

    if total_resumes > 0:
        average_ats = round(
            sum(item.ats_score for item in history_records) / total_resumes,
            3
        )
        highest_match = max(
            item.match_score for item in history_records
        )
        selected = len(
            [item for item in history_records if item.recommendation == "Selected"]
        )

    return render_template(
        "history.html",
        history=history_records,
        total_resumes=total_resumes,
        average_ats=average_ats,
        highest_match=highest_match,
        selected=selected
    )


@app.route("/interview-history")
@login_required
def interview_history():
    sessions = InterviewSession.query.filter_by(
        owner_id=current_user.id
    ).order_by(InterviewSession.created_at.desc()).all()

    for session in sessions:
        try:
            session.question_count = len(json.loads(session.questions))
        except Exception:
            session.question_count = 0

    return render_template("interview_history.html", sessions=sessions)


@app.route("/interview-history/<int:id>")
@login_required
def interview_history_detail(id):
    session = InterviewSession.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    try:
        questions = json.loads(session.questions)
    except Exception:
        questions = []
    try:
        answers = json.loads(session.answers)
    except Exception:
        answers = []

    return render_template(
        "interview_history_detail.html",
        session=session,
        questions=questions,
        answers=answers
    )


@app.route("/interview-history/<int:id>/delete", methods=["POST"])
@login_required
def delete_interview_history(id):
    session = InterviewSession.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    db.session.delete(session)
    db.session.commit()
    flash("Saved interview deleted successfully.", "info")
    return redirect("/interview-history")


@app.route("/delete/<int:id>", methods=["GET", "POST"])
@login_required
def delete(id):
    record = ResumeResult.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    InterviewSession.query.filter_by(candidate_id=record.id, owner_id=current_user.id).delete()
    db.session.delete(record)
    db.session.commit()
    flash("Candidate resume deleted successfully.", "info")
    return redirect("/history")


@app.route("/view/<int:id>")
@login_required
def view(id):
    data = ResumeResult.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    latest_jd = JobDescription.query.filter_by(
        owner_id=current_user.id
    ).order_by(
        JobDescription.created_at.desc()
    ).first()

    return render_template(
        "view.html",
        data=data,
        latest_jd=latest_jd
    )


@app.route("/report/<int:id>")
@login_required
def download_report(id):
    candidate = ResumeResult.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    pdf = build_candidate_report(candidate)
    safe_name = "".join(char if char.isalnum() else "_" for char in candidate.candidate_name)
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"smart_hire_report_{safe_name}.pdf"
    )


@app.route("/interview/<int:id>")
@login_required
def interview(id):
    ResumeResult.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    return redirect(f"/?candidate={id}#interview-assistant")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860 if os.getenv("SPACE_ID") else 5000))
    print("\n" + "=" * 55)
    print("  🚀 Smart-Hire AI Server is Running!")
    print(f"  👉 Open in your browser: http://127.0.0.1:{port}")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False)

