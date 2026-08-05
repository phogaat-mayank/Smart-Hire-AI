from urllib import response
import json
import time
from flask import Flask, render_template, request, redirect
import PyPDF2
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from google import genai
from dotenv import load_dotenv
import os

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


import time

def generate_resume_summary(resume_text):

    prompt = f"""
You are an HR Recruiter.

Read the resume and write a professional summary in 5 bullet points.

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

            score = round(similarity[0][0] * 100, 2)

            resume_text_lower = resume_texts[i].lower()

            matched_skills = [
                skill for skill in jd_skills
                if skill in resume_text_lower
            ]

            missing_skills = [
                skill for skill in jd_skills
                if skill not in matched_skills
            ]
            ats_score = round((score * 0.7) + (len(matched_skills) * 3), 2)
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
            print("Saved:", file_names[i])

        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)
        db.session.commit()
        print("Database committed successfully")
    return render_template("index.html", results=results)


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
            2
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
@app.route("/interview/<int:id>")
def interview(id):

    # Get candidate from database
    data = ResumeResult.query.get_or_404(id)

    # Get latest Job Description
    latest_jd = JobDescription.query.order_by(
        JobDescription.created_at.desc()
    ).first()

    # Load interview questions
    questions = load_interview_questions()

    # Check if AI answers are already saved
    if data.ai_interview:

        print("Loading AI answers from database...")

        ai_answers = json.loads(data.ai_interview)

    else:

        print("Generating AI answers from Gemini...")

        ai_answers = generate_ai_answers(
            data.resume_text,
            questions,
            latest_jd.job_description if latest_jd else ""
        )

        # Save AI answers in database
        data.ai_interview = json.dumps(ai_answers)
        db.session.commit()

    return render_template(
        "interview.html",
        data=data,
        questions=questions,
        ai_answers=ai_answers
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)