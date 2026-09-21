"""Seed data — gives a fresh install a lived-in, demonstrable state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import db
from .memory import memory_engine


def _days(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat()


def seed() -> dict:
    for _t in ("tasks", "memories", "clients"):
        if (db.qone(f"SELECT COUNT(*) c FROM {_t}") or {}).get("c", 0) > 0:
            return {"seeded": False, "reason": f"{_t} exist"}
    # clients
    c1 = db.run("INSERT INTO clients (user_id,name,org,email,health,notes,contract_value) VALUES (1,'Wanjiku Mwangi','NORERN','wanjiku@norern.co.ke','good','IPRS platform rollout. Prefers Friday demos.',450000)")
    c2 = db.run("INSERT INTO clients (user_id,name,org,email,health,notes,contract_value) VALUES (1,'Brian Otieno','Client X Retail','brian@clientx.com','watch','Mobile app redesign; slow feedback loop.',280000)")
    c3 = db.run("INSERT INTO clients (user_id,name,org,email,health,notes,contract_value) VALUES (1,'Amina Said','ShopLite','amina@shoplite.co.ke','good','E-commerce site, retainer for CRO.',120000)")
    # projects
    p1 = db.run("INSERT INTO projects (user_id,name,client_id,status,progress,deadline,description,health) VALUES (1,'NORERN IPRS Platform',?,'active',75,?, 'Integrated platform: registration, payments, reporting dashboards.','on_track')", (c1, _days(21)))
    p2 = db.run("INSERT INTO projects (user_id,name,client_id,status,progress,deadline,description,health) VALUES (1,'E-commerce Website',?,'completed',100,?, 'ShopLite storefront + M-Pesa checkout.','on_track')", (c3, _days(-6)))
    p3 = db.run("INSERT INTO projects (user_id,name,client_id,status,progress,deadline,description,health) VALUES (1,'Mobile App (Client X)',?,'review',60,?, 'Flutter app: catalogue, loyalty, push. Awaiting client review.','at_risk')", (c2, _days(9)))
    db.run_many("INSERT INTO milestones (project_id,title,status,due_at) VALUES (?,?,?,?)", [
        (p1, "Reporting dashboards", "open", _days(14)),
        (p1, "UAT & handover", "open", _days(21)),
        (p3, "Client review round 2", "open", _days(4)),
    ])
    # tasks
    db.run_many("INSERT INTO tasks (user_id,title,description,status,priority,due_at,project_id,client_id,domain) VALUES (1,?,?,?,?,?,?,?,?)", [
        ("Prepare NORERN demo for Friday", "Dashboards walkthrough + UAT checklist", "planned", "high", _days(2), p1, c1, "clients"),
        ("Follow up: Client X review feedback", "Chase Brian on round-2 comments", "in_progress", "urgent", _days(-2), p3, c2, "clients"),
        ("Deep Work: IPRS reporting module", "Finish export + charts", "planned", "high", _days(1), p1, c1, "clients"),
        ("Tailor resume for Senior Developer role", "Quantify ShopLite + NORERN impact", "inbox", "medium", _days(5), None, None, "career"),
        ("Mock interview practice (30 min)", "Behavioural + system design", "inbox", "medium", _days(3), None, None, "career"),
        ("Morning workout", "Zone-2 run, 30 min", "inbox", "low", _days(1), None, None, "personal"),
        ("Review monthly spending", "Check food + transport vs budget", "inbox", "medium", _days(4), None, None, "personal"),
        ("Pay hosting invoice", "", "completed", "medium", _days(-3), None, None, "general"),
    ])
    # career
    db.run("INSERT INTO resumes (user_id,name,version,content,ats_score) VALUES (1,'Antony Master Resume',3,?,78)",
           ("Antony Mureithi — Software Developer, Nairobi.\nBuilt NORERN IPRS platform serving 40k+ records. Led Flutter mobile app with 4.8 rating. Shipped e-commerce site processing KES 2M+/month via M-Pesa. Skilled in Python, FastAPI, React, Flutter, SQLite, Docker.",))
    db.run_many("INSERT INTO applications (user_id,company,role,stage,url,notes) VALUES (1,?,?,?,?,?)", [
        ("Safaricom", "Senior Backend Developer", "interview", "", "Panel interview Thursday"),
        ("Cellulant", "Full-Stack Engineer", "screen", "", "Hiring manager screen done"),
        ("Andela", "Senior Flutter Engineer", "applied", "", "Via referral"),
    ])
    # personal
    db.run_many("INSERT INTO goals (user_id,domain,title,target,progress) VALUES (1,?,?,?,?)", [
        ("personal", "Run 100 km this month", "100 km", 46),
        ("career", "Land senior role by Q1", "signed offer", 60),
        ("clients", "Ship NORERN UAT", "client sign-off", 75),
    ])
    db.run_many("INSERT INTO habits (user_id,name,streak,last_done) VALUES (1,?,?,?)", [
        ("Morning planning", 12, _days(-1)[:10]), ("Workout", 5, _days(-1)[:10]), ("Read 20 min", 8, _days(-2)[:10]),
    ])
    db.run_many("INSERT INTO expenses (user_id,category,amount,currency,note) VALUES (1,?,?,?,?)", [
        ("food", 2450, "KES", "Groceries"), ("transport", 1800, "KES", "Matatu + fuel"),
        ("airtime", 1000, "KES", "Safaricom"), ("rent", 35000, "KES", "September"),
        ("food", 3200, "KES", "Eating out"), ("health", 1500, "KES", "Gym"),
    ])
    db.run("INSERT INTO journal (user_id,title,body,mood) VALUES (1,'Evening reflection','Shipped the IPRS export feature. Feeling momentum — protecting deep-work mornings is compounding.','good')")
    # memories
    for m in [
        ("career", "semantic", "Antony is a full-stack developer in Nairobi", "Antony is a full-stack software developer based in Nairobi, Kenya, working with Python, FastAPI, React, Flutter and local AI systems.", 0.9, 0.8),
        ("clients", "semantic", "NORERN IPRS platform is the flagship project", "NORERN IPRS platform is Antony's flagship client project — registration, payments, reporting — currently ~75% complete with Friday demos.", 0.85, 0.85),
        ("clients", "episodic", "Client X feedback is slow", "Client X (Brian) is slow to return review feedback on the mobile app; follow-ups usually needed twice.", 0.7, 0.6),
        ("personal", "preference", "Prefers morning deep-work blocks", "Antony does his best focused work in the morning and wants meetings after 11:00.", 0.8, 0.7),
        ("career", "episodic", "Targeting senior developer roles", "Antony is targeting Senior Developer roles and tailoring his resume with quantified achievements.", 0.85, 0.75),
        ("personal", "preference", "Currency is KES", "Antony tracks money in Kenyan Shillings (KES) and uses M-Pesa heavily.", 0.9, 0.5),
    ]:
        memory_engine.store(m[2], m[3], m[0], m[1], "seed", m[4], m[5])
    # automations
    db.run_many("INSERT INTO automations (user_id,name,trigger_kind,trigger_config,action_kind,action_config,status,next_run,success_count) VALUES (1,?,?,?,?,?,?,?,?)", [
        ("Morning brief", "schedule", db.jdump({"every": "daily", "at": "07:30"}), "notify", db.jdump({"title": "☀️ Morning brief", "body": "Top priorities + overdue + today's blocks."}), "active", _days(1), 14),
        ("Weekly client digest", "schedule", db.jdump({"every": "weekly"}), "notify", db.jdump({"title": "📊 Weekly client digest", "body": "Progress, risks, overdue across projects."}), "active", _days(3), 6),
        ("Nightly backup", "schedule", db.jdump({"every": "daily", "at": "02:00"}), "backup", db.jdump({}), "active", _days(1), 30),
    ])
    # integrations start connected (local adapters) so gateway demo is alive
    for p, acc in [("telegram", "@aura_bot"), ("discord", "AURA#4821"), ("slack", "#aura-ops"), ("whatsapp", "+254 7•• ••• 210"), ("email", "antony@aura.os")]:
        db.run("UPDATE integrations SET status='connected', account=? WHERE user_id=1 AND platform=?", (acc, p))
    db.notify("Welcome to AURA OS", "Your sidekick is ready. Try “plan my day” or press Ctrl+K.", "info")
    db.notify("2 tasks overdue", "Client X review feedback needs a follow-up.", "warn")
    db.log_activity("system", "AURA OS initialized", "seed data loaded · sqlite + memory ready", "general", "success")
    return {"seeded": True}
