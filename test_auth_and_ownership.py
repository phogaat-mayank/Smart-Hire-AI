import json
import unittest
from datetime import datetime
from werkzeug.security import generate_password_hash

# Import app, db, and models from main
from main import app, db, User, ResumeResult, JobDescription, InterviewSession


class AuthAndOwnershipTestCase(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app = app
        self.client = app.test_client()

        with app.app_context():
            db.create_all()

            # Create User 1: Alice
            self.alice = User(
                name="Alice Recruiter",
                email="alice@company.com",
                password_hash=generate_password_hash("password123")
            )
            # Create User 2: Bob
            self.bob = User(
                name="Bob Hiring",
                email="bob@company.com",
                password_hash=generate_password_hash("securepass456")
            )
            db.session.add_all([self.alice, self.bob])
            db.session.commit()

            # User 1 (Alice) records
            self.alice_jd = JobDescription(
                job_description="Senior Python & Flask Developer with SQL experience",
                owner_id=self.alice.id
            )
            self.alice_resume = ResumeResult(
                candidate_name="Alice Candidate",
                filename="alice_resume.pdf",
                match_score=88.5,
                ats_score=85.0,
                matched_skills="python, flask, sql",
                missing_skills="docker",
                resume_summary="Experienced Python engineer.",
                recommendation="Selected",
                resume_text="Senior Python Flask SQL engineer...",
                owner_id=self.alice.id
            )
            db.session.add_all([self.alice_jd, self.alice_resume])
            db.session.commit()

            self.alice_session = InterviewSession(
                candidate_id=self.alice_resume.id,
                questions=json.dumps(["What is candidate's Python background?"]),
                answers=json.dumps([{"question": "What is candidate's Python background?", "answer": "5 years Flask and SQL", "evidence": "Resume", "status": "matched"}]),
                owner_id=self.alice.id
            )
            db.session.add(self.alice_session)

            # User 2 (Bob) records
            self.bob_jd = JobDescription(
                job_description="React and Node.js Full Stack Engineer",
                owner_id=self.bob.id
            )
            self.bob_resume = ResumeResult(
                candidate_name="Bob Candidate",
                filename="bob_resume.pdf",
                match_score=72.0,
                ats_score=70.0,
                matched_skills="react, javascript",
                missing_skills="node.js",
                resume_summary="Frontend developer with React experience.",
                recommendation="Rejected",
                resume_text="React JavaScript frontend engineer...",
                owner_id=self.bob.id
            )
            db.session.add_all([self.bob_jd, self.bob_resume])
            db.session.commit()

            self.bob_session = InterviewSession(
                candidate_id=self.bob_resume.id,
                questions=json.dumps(["Does candidate know Node.js?"]),
                answers=json.dumps([{"question": "Does candidate know Node.js?", "answer": "Not mentioned in resume", "evidence": "None", "status": "missing"}]),
                owner_id=self.bob.id
            )
            db.session.add(self.bob_session)

            # Unowned legacy records (owner_id is NULL)
            self.legacy_resume = ResumeResult(
                candidate_name="Legacy Unowned Candidate",
                filename="legacy_resume.pdf",
                match_score=90.0,
                ats_score=90.0,
                matched_skills="python",
                missing_skills="",
                resume_summary="Old unowned resume record",
                recommendation="Selected",
                resume_text="Unowned resume from legacy system",
                owner_id=None
            )
            self.legacy_jd = JobDescription(
                job_description="Unowned legacy JD",
                owner_id=None
            )
            db.session.add_all([self.legacy_resume, self.legacy_jd])
            db.session.commit()

            self.legacy_session = InterviewSession(
                candidate_id=self.legacy_resume.id,
                questions=json.dumps(["Legacy question?"]),
                answers=json.dumps([{"question": "Legacy question?", "answer": "Old answer", "evidence": "Legacy", "status": "matched"}]),
                owner_id=None
            )
            db.session.add(self.legacy_session)
            db.session.commit()

            # Store IDs for assertion checks
            self.alice_id = self.alice.id
            self.bob_id = self.bob.id
            self.alice_resume_id = self.alice_resume.id
            self.bob_resume_id = self.bob_resume.id
            self.legacy_resume_id = self.legacy_resume.id
            self.alice_session_id = self.alice_session.id
            self.bob_session_id = self.bob_session.id
            self.legacy_session_id = self.legacy_session.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self, email, password):
        return self.client.post("/login", data={
            "email": email,
            "password": password
        }, follow_redirects=True)

    def logout(self):
        return self.client.get("/logout", follow_redirects=True)

    # -------------------------------------------------------------
    # 1. AUTHENTICATION PROTECTION (Unauthenticated Access)
    # -------------------------------------------------------------
    def test_unauthenticated_redirects(self):
        """Unauthenticated requests must be redirected to /login."""
        protected_urls = [
            "/",
            "/history",
            f"/view/{self.alice_resume_id}",
            f"/report/{self.alice_resume_id}",
            f"/interview/{self.alice_resume_id}",
            "/interview-history",
            f"/interview-history/{self.alice_session_id}",
        ]
        for url in protected_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"URL {url} should redirect unauthenticated requests")
            self.assertIn("/login", response.headers["Location"])

    def test_login_invalid_credentials(self):
        """Invalid credentials should show error message."""
        response = self.login("alice@company.com", "wrongpassword")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid email or password", response.data)

    def test_registration_flow(self):
        """New user can register, gets auto-authenticated, and accesses dashboard."""
        response = self.client.post("/register", data={
            "name": "Charlie Recruiter",
            "email": "charlie@company.com",
            "password": "password789",
            "confirm_password": "password789"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Charlie Recruiter", response.data)

        # Verify Charlie cannot see Alice or Bob or Legacy resumes
        history_resp = self.client.get("/history")
        self.assertNotIn(b"Alice Candidate", history_resp.data)
        self.assertNotIn(b"Bob Candidate", history_resp.data)
        self.assertNotIn(b"Legacy Unowned Candidate", history_resp.data)

    def test_registration_validation(self):
        """Duplicate email or password mismatch must fail registration."""
        # Duplicate email
        resp = self.client.post("/register", data={
            "name": "Duplicate Alice",
            "email": "alice@company.com",
            "password": "password123",
            "confirm_password": "password123"
        }, follow_redirects=True)
        self.assertIn(b"already exists", resp.data)

        # Mismatched password
        resp2 = self.client.post("/register", data={
            "name": "David",
            "email": "david@company.com",
            "password": "password123",
            "confirm_password": "mismatchpass"
        }, follow_redirects=True)
        self.assertIn(b"Passwords do not match", resp2.data)

    # -------------------------------------------------------------
    # 2. DATA OWNERSHIP & ISOLATION
    # -------------------------------------------------------------
    def test_history_data_isolation(self):
        """Each user only sees their own resumes and statistics in /history."""
        # Login as Alice
        self.login("alice@company.com", "password123")
        resp = self.client.get("/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Alice Candidate", resp.data)
        self.assertNotIn(b"Bob Candidate", resp.data)
        self.assertNotIn(b"Legacy Unowned Candidate", resp.data)
        self.logout()

        # Login as Bob
        self.login("bob@company.com", "securepass456")
        resp = self.client.get("/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Bob Candidate", resp.data)
        self.assertNotIn(b"Alice Candidate", resp.data)
        self.assertNotIn(b"Legacy Unowned Candidate", resp.data)

    def test_dashboard_candidate_dropdown_isolation(self):
        """Dashboard dropdown only lists candidates owned by current user."""
        self.login("alice@company.com", "password123")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Alice Candidate", resp.data)
        self.assertNotIn(b"Bob Candidate", resp.data)
        self.assertNotIn(b"Legacy Unowned Candidate", resp.data)
        self.logout()

    def test_view_detail_isolation(self):
        """Users can only view their own candidate resume details; others get 404."""
        self.login("alice@company.com", "password123")
        # Alice viewing her own resume -> 200 OK
        resp = self.client.get(f"/view/{self.alice_resume_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Alice Candidate", resp.data)

        # Alice trying to view Bob's resume -> 404
        resp = self.client.get(f"/view/{self.bob_resume_id}")
        self.assertEqual(resp.status_code, 404)

        # Alice trying to view Legacy unowned resume -> 404
        resp = self.client.get(f"/view/{self.legacy_resume_id}")
        self.assertEqual(resp.status_code, 404)
        self.logout()

    def test_download_report_isolation(self):
        """Users can only download PDF reports for their own candidates."""
        self.login("bob@company.com", "securepass456")
        # Bob downloading Alice's candidate report -> 404
        resp = self.client.get(f"/report/{self.alice_resume_id}")
        self.assertEqual(resp.status_code, 404)

        # Bob downloading Legacy unowned report -> 404
        resp = self.client.get(f"/report/{self.legacy_resume_id}")
        self.assertEqual(resp.status_code, 404)

        # Bob downloading his own report -> 200 and PDF mime type
        resp = self.client.get(f"/report/{self.bob_resume_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/pdf")
        self.assertTrue(len(resp.data) > 0)
        self.logout()

    def test_delete_candidate_isolation(self):
        """Users cannot delete other users' or unowned resumes."""
        self.login("bob@company.com", "securepass456")
        # Bob tries to delete Alice's resume -> 404
        resp = self.client.get(f"/delete/{self.alice_resume_id}")
        self.assertEqual(resp.status_code, 404)

        # Bob tries to delete Legacy unowned resume -> 404
        resp = self.client.get(f"/delete/{self.legacy_resume_id}")
        self.assertEqual(resp.status_code, 404)

        # Verify Alice's resume still exists in database
        with self.app.app_context():
            cand = db.session.get(ResumeResult, self.alice_resume_id)
            self.assertIsNotNone(cand)

        # Bob deletes his own resume -> 302 / success
        resp = self.client.get(f"/delete/{self.bob_resume_id}", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            cand = db.session.get(ResumeResult, self.bob_resume_id)
            self.assertIsNone(cand)
        self.logout()

    def test_interview_history_isolation(self):
        """Users can only access their own saved interview history sessions."""
        self.login("alice@company.com", "password123")
        # Alice viewing interview history list
        resp = self.client.get("/interview-history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Alice Candidate", resp.data)
        self.assertNotIn(b"Bob Candidate", resp.data)
        self.assertNotIn(b"Legacy Unowned Candidate", resp.data)

        # Alice viewing detail of her session -> 200
        resp = self.client.get(f"/interview-history/{self.alice_session_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"What is candidate", resp.data)

        # Alice viewing Bob's session -> 404
        resp = self.client.get(f"/interview-history/{self.bob_session_id}")
        self.assertEqual(resp.status_code, 404)

        # Alice viewing Legacy unowned session -> 404
        resp = self.client.get(f"/interview-history/{self.legacy_session_id}")
        self.assertEqual(resp.status_code, 404)

        # Alice tries to delete Bob's session -> 404
        resp = self.client.post(f"/interview-history/{self.bob_session_id}/delete")
        self.assertEqual(resp.status_code, 404)

        # Alice deletes her own session -> 302
        resp = self.client.post(f"/interview-history/{self.alice_session_id}/delete", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            sess = db.session.get(InterviewSession, self.alice_session_id)
            self.assertIsNone(sess)
        self.logout()

    def test_interview_api_cross_tenant_rejection(self):
        """POST /api/interview-answer rejects candidate IDs owned by other users or unowned."""
        self.login("bob@company.com", "securepass456")

        # Bob attempts to trigger AI interview on Alice's candidate
        resp = self.client.post("/api/interview-answer", json={
            "candidate_id": self.alice_resume_id,
            "questions": ["What is Python experience?"]
        })
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertIn("not found", data["error"].lower())

        # Bob attempts to trigger AI interview on unowned candidate
        resp2 = self.client.post("/api/interview-answer", json={
            "candidate_id": self.legacy_resume_id,
            "questions": ["What is Python experience?"]
        })
        self.assertEqual(resp2.status_code, 404)
        self.logout()


if __name__ == "__main__":
    unittest.main()
