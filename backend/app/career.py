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
    """Generate a role-aware interview question set.

    Always returns a full set (>= 6) so it is useful on its own, and folds in
    terms lifted from the job description when one is supplied. Deterministic —
    no network, no LLM — so it is instant and works offline.
    """
    role = (role or "this role").strip() or "this role"
    jd = (job_description or "").strip()
    questions = [
        f"Walk me through a challenging project you delivered as a {role}. What was your specific contribution?",
        f"How do you prioritise competing deadlines in {role.lower()} work?",
        "Describe a time something went wrong. What did you do, and what changed afterwards?",
        f"How do you keep your {role.lower()} skills current — and how do you know what's worth learning?",
        "How do you handle disagreement with a colleague or manager about a technical or clinical judgement?",
        "What questions do you have for us about the role and the team?",
    ]

    # Fold in concrete terms from the posting so the set is specific, not generic.
    terms: list[str] = []
    stop = {
        "and", "the", "with", "for", "our", "you", "are", "will", "have", "this",
        "that", "from", "who", "job", "role", "team", "work", "years", "year",
        "experience", "strong", "good", "ability", "able", "must", "should",
    }
    for raw in jd.replace("/", " ").replace(",", " ").replace("(", " ").replace(")", " ").split():
        word = raw.strip(".-_").lower()
        if len(word) > 3 and word.isalpha() and word not in stop and word not in terms:
            terms.append(word)
        if len(terms) >= 4:
            break
    if terms:
        listed = ", ".join(terms)
        questions.insert(2, f"This role mentions {listed}. Where have you applied that, and what was the outcome?")
    else:
        questions.insert(2, f"What would you want to know about success in {role} after the first 90 days?")

    return {"questions": questions, "role": role, "count": len(questions)}