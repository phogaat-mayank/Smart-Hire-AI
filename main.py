from urllib import response
import json
import re
import time
from io import BytesIO
from xml.sax.saxutils import escape
from flask import Flask, render_template, request, redirect, jsonify, send_file
import PyPDF2
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from google import genai
from dotenv import load_dotenv
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

app = Flask(__name__)
load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# Load BERT Model
print("Loading BERT model...")
model = SentenceTransformer('all-MiniLM-L6-v2')
print("BERT model loaded successfully!")

# Database Config
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///results.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database Table
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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create Database
class JobDescription(db.Model):
    
    id = db.Column(db.Integer, primary_key=True)

    job_description = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class InterviewSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("resume_result.id"), nullable=False)
    questions = db.Column(db.Text, nullable=False)
    answers = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    candidate = db.relationship("ResumeResult", backref="interview_sessions")
with app.app_context():
    db.create_all()
    

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
    reader = PyPDF2.PdfReader(file)

    text = ""

    for page in reader.pages:
        page_text = page.extract_text()

        if page_text:
            text += page_text

    return text


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


import time

def generate_resume_summary(resume_text):

    prompt = f"""
You are an HR Recruiter.

Read the resume and write a professional summary in exactly 4 concise bullet points.

Resume:
{resume_text}
"""

    for attempt in range(3):

        try:

            response = client.models.generate_content(
               model="gemini-3.5-flash-lite",
                contents=prompt
            )

            return response.text

        except Exception as e:

            print("Gemini Error:", e)

            if attempt < 2:
                print("Retrying...")
                time.sleep(3)

    print("Gemini unavailable. Using fallback summary.")

    return "AI summary is temporarily unavailable."


def load_interview_questions():

    with open(
        "questions/interview_questions.txt",
        "r",
        encoding="utf-8"
    ) as file:

        questions = []

        for line in file:

            line = line.strip()

            if line:
                questions.append(line)

    return questions


def generate_ai_answers(resume_text, questions, job_description=""):

    # Convert questions list into numbered text
    questions_text = "\n".join(
        f"{index}. {question}"
        for index, question in enumerate(questions, start=1)
    )

    # Create the complete prompt
    prompt = f"""
You are an AI Recruitment Assistant.

Your task is to answer the recruiter's questions ONLY using the information available in the candidate's resume and the job description.

Rules:
1. Do NOT make up information.
2. If the answer is not found, write:
   "Not mentioned in the resume."
3. Quote evidence from the resume whenever possible.
4. Keep answers professional.

Job Description:
{job_description}

Resume:
{resume_text}

Interview Questions:
{questions_text}

Return ONLY valid JSON.

Return a JSON array.

Each object must have exactly these keys:

[
  {{
    "question": "...",
    "answer": "...",
    "evidence": "...",
    "status": "matched"
  }}
]

Status Rules:
- matched = Candidate fully satisfies the requirement.
- partial = Candidate has related knowledge but not complete.
- missing = Candidate does not satisfy the requirement.

Do not include markdown.
Do not include ```json.
Do not include explanations.
Only return valid JSON.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt
    )

    text = response.text.strip()

    # Remove markdown if Gemini returns it
    text = text.replace("```json", "")
    text = text.replace("```", "")
    text = text.strip()

    return json.loads(text)


def generate_interview_answer(resume_text, question, job_description=""):
    """Answer one recruiter question using only the selected candidate's data."""
    prompt = f"""
You are an AI recruitment assistant. Answer the recruiter's question using ONLY the
candidate resume and job description below. Do not invent facts. If the information
is absent, say exactly: "Not mentioned in the resume."

Job Description:
{job_description}

Candidate Resume:
{resume_text}

Recruiter Question:
{question}

Return only valid JSON with these keys:
{{"answer": "...", "evidence": "...", "status": "matched|partial|missing"}}
"""

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt
        )
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        answer = json.loads(text)
        return {
            "answer": answer.get("answer", "Not mentioned in the resume."),
            "evidence": answer.get("evidence", "No supporting evidence found."),
            "status": answer.get("status", "missing")
        }
    except Exception as error:
        print("Live interview answer error:", error)
        return None


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
            text = response.text.strip().replace("```json", "").replace("```", "").strip()
            answers = json.loads(text)
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


def is_valid_interview_question(text):
    """Require an actual interview-style question instead of arbitrary text."""
    normalized = re.sub(r"\s+", " ", text).strip()
    question_starters = (
        "what", "why", "when", "where", "who", "which", "how", "is ", "are ",
        "does", "do ", "can", "could", "would", "should", "will", "has", "have",
        "explain", "describe", "compare", "evaluate", "assess", "identify", "list",
        "kya", "kyu", "kaise", "batao", "samjhao", "evaluate"
    )
    return (
        len(normalized) >= 8
        and any(character.isalpha() for character in normalized)
        and ("?" in normalized or normalized.lower().startswith(question_starters))
    )


# Main Route
@app.route("/", methods=["GET", "POST"])
def index():

    results = []

    if request.method == "POST":

        resume_files = request.files.getlist("resume")
        job_description = request.form["job_description"]
        jd = JobDescription(job_description=job_description)

        db.session.add(jd)
        db.session.commit()
        jd_skills = extract_jd_skills(job_description)

        resume_texts = []
        file_names = []

        # Extract text from all resumes
        for file in resume_files:

            resume_text = extract_text_from_pdf(file)

            if resume_text and resume_text.strip():
                print(f"Processing: {file.filename}")
                resume_texts.append(resume_text[:3000])
                file_names.append(file.filename)

        # Batch BERT Encoding
        resume_embeddings = model.encode(resume_texts)
        jd_embedding = model.encode(job_description)

        # Process each resume
        for i, resume_embedding in enumerate(resume_embeddings):

            similarity = cosine_similarity(
                [resume_embedding],
                [jd_embedding]
            )

            score = round(similarity[0][0] * 100, 3)

            resume_text_lower = resume_texts[i].lower()

            matched_skills = [
                skill for skill in jd_skills
                if skill in resume_text_lower
            ]

            missing_skills = [
                skill for skill in jd_skills
                if skill not in matched_skills
            ]
            ats_score = round((score * 0.7) + (len(matched_skills) * 3), 3)
            if ats_score > 100:
                ats_score = 100

            results.append((
                file_names[i],
                score,
                ats_score,
                matched_skills,
                missing_skills
            ))
            print("Generating AI Summary...")
            summary = generate_resume_summary(resume_texts[i])
            print("Summary Generated Successfully!")

            resume_result = ResumeResult(
                candidate_name=file_names[i].replace(".pdf", ""),
                filename=file_names[i],

                match_score=score,
                ats_score=ats_score,

                matched_skills=", ".join(matched_skills),
                missing_skills=", ".join(missing_skills),
                resume_summary=summary,
                resume_text=resume_texts[i],

                recommendation="Selected" if score >= 75 else "Rejected"
            )

            db.session.add(resume_result)
            db.session.flush()
            results[-1] = (*results[-1], resume_result.id)
            print("Saved:", file_names[i])

        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)
        db.session.commit()
        print("Database committed successfully")
    candidates = ResumeResult.query.order_by(ResumeResult.created_at.desc()).all()
    return render_template("index.html", results=results, candidates=candidates)


@app.route("/api/interview-answer", methods=["POST"])
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

    candidate = db.session.get(ResumeResult, candidate_id)
    if not candidate:
        return jsonify({"error": "Selected candidate was not found."}), 404

    latest_jd = JobDescription.query.order_by(JobDescription.created_at.desc()).first()
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
        answers=json.dumps(answers)
    )
    db.session.add(interview_session)
    db.session.commit()

    return jsonify({
        "candidate": candidate.candidate_name,
        "answers": answers,
        "history_id": interview_session.id
    })


@app.route("/history")
def history():

    history = ResumeResult.query.order_by(
        ResumeResult.created_at.desc()
    ).all()

    total_resumes = len(history)

    average_ats = 0
    highest_match = 0
    selected = 0

    if total_resumes > 0:

        average_ats = round(
            sum(item.ats_score for item in history) / total_resumes,
            3
        )

        highest_match = max(
            item.match_score for item in history
        )

        selected = len(
            [item for item in history if item.recommendation == "Selected"]
        )

    return render_template(
        "history.html",
        history=history,
        total_resumes=total_resumes,
        average_ats=average_ats,
        highest_match=highest_match,
        selected=selected
    )


@app.route("/interview-history")
def interview_history():
    sessions = InterviewSession.query.order_by(InterviewSession.created_at.desc()).all()
    for session in sessions:
        session.question_count = len(json.loads(session.questions))
    return render_template("interview_history.html", sessions=sessions)


@app.route("/interview-history/<int:id>")
def interview_history_detail(id):
    session = InterviewSession.query.get_or_404(id)
    return render_template(
        "interview_history_detail.html",
        session=session,
        questions=json.loads(session.questions),
        answers=json.loads(session.answers)
    )


@app.route("/interview-history/<int:id>/delete", methods=["POST"])
def delete_interview_history(id):
    session = InterviewSession.query.get_or_404(id)
    db.session.delete(session)
    db.session.commit()
    return redirect("/interview-history")
@app.route("/delete/<int:id>")
def delete(id):

    record = ResumeResult.query.get_or_404(id)

    db.session.delete(record)

    db.session.commit()

    return redirect("/history")
@app.route("/view/<int:id>")
def view(id):

    data = ResumeResult.query.get_or_404(id)
    latest_jd = JobDescription.query.order_by(
    JobDescription.created_at.desc()
).first()

    return render_template(
        "view.html",
        data=data,
        latest_jd=latest_jd
    )


@app.route("/report/<int:id>")
def download_report(id):
    candidate = ResumeResult.query.get_or_404(id)
    pdf = build_candidate_report(candidate)
    safe_name = "".join(char if char.isalnum() else "_" for char in candidate.candidate_name)
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"smart_hire_report_{safe_name}.pdf"
    )
@app.route("/interview/<int:id>")
def interview(id):
    ResumeResult.query.get_or_404(id)
    return redirect(f"/?candidate={id}#interview-assistant")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
