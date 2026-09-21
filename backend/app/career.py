from . import db


def ats_analyze(text: str, job_description: str, name: str = "Resume") -> dict:
    """Analyze resume for ATS compatibility."""
    text_lower = text.lower()
    jd_lower = job_description.lower()

    jd_keywords = set(jd_lower.split())
    text_keywords = set(text_lower.split())

    matched = jd_keywords & text_keywords
    score = min(100, int((len(matched) / max(len(jd_keywords), 1)) * 100) + 20)

    recommendations = []
    if "python" in jd_lower and "python" not in text_lower:
        recommendations.append("Add Python experience")
    if "api" in jd_lower and "api" not in text_lower:
        recommendations.append("Highlight API development")
    if "lead" in jd_lower and "led" not in text_lower and "lead" not in text_lower:
        recommendations.append("Emphasize leadership experience")
    if "test" in jd_lower and "test" not in text_lower:
        recommendations.append("Mention testing experience")

    if not recommendations:
        recommendations.append("Good keyword match")

    rid = db.run(
        "INSERT INTO resumes (user_id, name, content, job_description, ats_score, version) VALUES (1,?,?,?,?,1)",
        (name, text, job_description, score))

    return {"ats_score": score, "recommendations": recommendations, "matched_keywords": list(matched), "resume_id": rid}


def interview_questions(job_description: str, role: str = "Software Engineer") -> dict:
    """Generate interview questions based on job description."""
    questions = [
        f"Describe a challenging project you worked on as a {role}.",
        f"How do you approach debugging complex issues in {role.lower()}?",
        f"What's your experience with the technologies mentioned in the job description?",
    ]
    return {"questions": questions}