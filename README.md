---
title: Smart Hire AI
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Smart-Hire AI: AI-Powered Resume Screening & Assessment System

Smart-Hire AI is an intelligent resume screening and recruitment platform that automates candidate screening, evaluates resumes against job descriptions using BERT embeddings, calculates ATS match scores, generates PDF screening reports, and conducts AI-powered interview question assessments.

## Key Features
- **BERT Semantic Matching**: Evaluates resume-to-JD contextual fit using `sentence-transformers` (`all-MiniLM-L6-v2`).
- **ATS & Skills Analysis**: Extracts matched and missing skills with deterministic scoring.
- **AI Summary & Evaluation**: Generates concise executive summaries powered by Google Gemini.
- **AI Interview Assistant**: Answers specific recruiter questions grounded strictly in candidate resume evidence.
- **Multi-Tenant User Isolation**: Secure authentication with individual candidate and interview histories per recruiter.
- **PDF Report Generation**: Downloadable candidate screening reports.

## Local Setup
1. Clone the repository
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure `.env`:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   SECRET_KEY=your_secret_key_here
   DATABASE_URL=sqlite:///results.db  # Or your PostgreSQL connection string
   ```
5. Run the application:
   ```bash
   python main.py
   ```
