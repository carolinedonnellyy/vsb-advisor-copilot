"""
VSB Advisor Assistant
=====================
Streamlit app that helps VSB academic advisors segment students in HubSpot
and draft personalized outreach emails with Claude, then log approved
emails as engagements on the contact timeline.

Secrets required (set in Streamlit Cloud -> App settings -> Secrets):
    ANTHROPIC_API_KEY = "sk-ant-..."
    HUBSPOT_TOKEN     = "pat-na1-..."
"""

import json
import time
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="VSB Advisor Assistant",
    page_icon="🎓",
    layout="wide",
)

ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", "")
HUBSPOT_TOKEN = st.secrets.get("HUBSPOT_TOKEN", "")
SMTP_EMAIL = st.secrets.get("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = st.secrets.get("SMTP_APP_PASSWORD", "")
SMTP_HOST = st.secrets.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(st.secrets.get("SMTP_PORT", 587))
ADVISOR_DISPLAY_NAME = st.secrets.get("ADVISOR_DISPLAY_NAME", "VSB Academic Advising")

CLAUDE_MODEL = "claude-sonnet-4-5"

HUBSPOT_BASE = "https://api.hubapi.com"
HUBSPOT_HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}

# Custom contact properties seeded by hubspot_setup.py
VSB_PROPERTIES = [
    "email", "firstname", "lastname",
    "vsb_year", "vsb_concentration", "vsb_gpa", "vsb_gpa_band",
    "vsb_transfer_student", "vsb_completed_courses",
    "vsb_current_grades", "vsb_flags",
]


# ---------------------------------------------------------------------------
# HubSpot helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_all_vsb_contacts() -> list[dict[str, Any]]:
    """
    Pull every HubSpot contact that has a vsb_year set. We paginate through
    the search endpoint; 24 records fit in one page but this is future-proof.
    """
    url = f"{HUBSPOT_BASE}/crm/v3/objects/contacts/search"
    results: list[dict[str, Any]] = []
    after = None
    for _ in range(10):  # safety cap on pagination
        body = {
            "filterGroups": [{
                "filters": [{"propertyName": "vsb_year", "operator": "HAS_PROPERTY"}]
            }],
            "properties": VSB_PROPERTIES,
            "limit": 100,
        }
        if after:
            body["after"] = after
        r = requests.post(url, headers=HUBSPOT_HEADERS, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        for row in data.get("results", []):
            p = row.get("properties", {})
            try:
                gpa = float(p.get("vsb_gpa") or 0)
            except (TypeError, ValueError):
                gpa = 0.0
            try:
                grades = json.loads(p.get("vsb_current_grades") or "{}")
            except json.JSONDecodeError:
                grades = {}
            completed = [c.strip() for c in (p.get("vsb_completed_courses") or "").split(",") if c.strip()]
            flags = [f.strip() for f in (p.get("vsb_flags") or "").split(",") if f.strip()]
            results.append({
                "id": row["id"],  # HubSpot contact ID
                "email": p.get("email", ""),
                "first": p.get("firstname", ""),
                "last": p.get("lastname", ""),
                "name": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
                "year": p.get("vsb_year", ""),
                "concentration": p.get("vsb_concentration") or None,
                "gpa": gpa,
                "gpa_band": p.get("vsb_gpa_band", ""),
                "transfer": (p.get("vsb_transfer_student") or "").lower() == "true",
                "completed": completed,
                "current_grades": grades,
                "flags": flags,
            })
        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after:
            break
    return results


def log_outreach_to_contact(contact_id: str, subject: str, body: str) -> bool:
    """
    Write the approved outreach back onto the student's contact record as a
    'last outreach' snapshot. This replaces the Engagements API approach
    because HubSpot free tier doesn't expose email/engagement/note write
    scopes, but contact-property writes work everywhere.

    The subject, body, and timestamp all live on the contact so the advisor
    (and the professor during the demo) can open any contact in HubSpot and
    see exactly what was sent and when.
    """
    url = f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}"
    sent_at_iso = datetime.now(tz=timezone.utc).isoformat()
    payload = {
        "properties": {
            "vsb_last_outreach_subject": subject,
            "vsb_last_outreach_body": body,
            "vsb_last_outreach_sent_at": sent_at_iso,
        }
    }
    r = requests.patch(url, headers=HUBSPOT_HEADERS, json=payload, timeout=30)
    return r.status_code in (200, 201)


def send_via_smtp(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Send the approved email via SMTP. Defaults to Gmail; the SMTP host is
    configurable via the SMTP_HOST secret so the same code works for any
    provider that supports app-password SMTP.

    Returns (ok, message). If SMTP_EMAIL or SMTP_APP_PASSWORD are not
    configured, returns (False, "not configured") so the caller can fall
    back to log-only mode without the demo dying.
    """
    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        return False, "SMTP send not configured"

    msg = EmailMessage()
    msg["From"] = f"{ADVISOR_DISPLAY_NAME} <{SMTP_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            # App passwords are 16 chars and may include spaces — strip them
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD.replace(" ", ""))
            server.send_message(msg)
        return True, "sent"
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP rejected the credentials. Re-check SMTP_EMAIL and SMTP_APP_PASSWORD."
    except Exception as e:
        return False, f"SMTP error: {e.__class__.__name__}: {e}"


# ---------------------------------------------------------------------------
# Claude helpers
# ---------------------------------------------------------------------------
_claude = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def _extract_json(text: str) -> Any:
    """Strip markdown fences and parse JSON defensively."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip fence line
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def claude_segment(query: str, contacts: list[dict]) -> list[str]:
    """Ask Claude to pick the matching HubSpot contact IDs."""
    system = (
        "You are an AI agent that segments HubSpot contacts for a Villanova "
        "School of Business academic advisor. Return ONLY a JSON object "
        '(no markdown): {"matched_ids": ["123", "456", ...]}\n\n'
        "Segmentation rules:\n"
        "- 'At-risk' = gpa below 2.7 OR any current_grades value is D+/D/D-/F.\n"
        "- 'Struggling in [course]' = that course code is a key in current_grades with a D+/D/D-/F/C-/C grade.\n"
        "- 'Transfer' / 'transfer student' / 'new to VSB' = transfer field is true.\n"
        "- 'Undeclared' / 'no concentration' / \"haven't declared\" = concentration is null or empty.\n"
        "- 'Missing [course]' = that course code is NOT in completed.\n"
        "- 'Senior missing capstone' = year is 'Senior' AND 'VSB 4002' not in completed.\n"
        "- Class year filtering: 'Freshman', 'Sophomore', 'Junior', 'Senior' filter to that year exactly. "
        "If the advisor doesn't name a year, do NOT restrict by year on your own.\n"
        "- Only filter by concentration if the advisor explicitly names one.\n"
        "- Return 3-10 matches.\n"
        "- The advisor only sees Banner data (transcript, registration, concentration, GPA, transfer status). "
        "Never invent fields like internship status or club membership."
    )
    slim = [
        {
            "id": c["id"],
            "name": c["name"],
            "year": c["year"],
            "concentration": c["concentration"],
            "gpa": c["gpa"],
            "transfer": c["transfer"],
            "completed": c["completed"],
            "current_grades": c["current_grades"],
            "flags": c["flags"],
        }
        for c in contacts
    ]
    msg = _claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": f'Advisor request: "{query}"\n\nContacts:\n{json.dumps(slim)}'}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    parsed = _extract_json(raw)
    return [str(x) for x in parsed.get("matched_ids", [])]


def claude_draft_emails(query: str, students: list[dict]) -> list[dict]:
    """Ask Claude for personalized drafts. Returns list of {id, subject, body}."""
    system = (
        "You draft personalized academic advising outreach emails for a VSB "
        "advisor. The advisor reviews and edits every email before sending.\n\n"
        "Return ONLY a JSON array (no markdown). Each entry: "
        '{"id": "<hubspot_contact_id>", "subject": "...", "body": "..."}\n\n'
        "VSB concentrations: Finance, Accounting, Marketing, Management, MIS, "
        "Business Analytics, Real Estate, International Business.\n\n"
        "Rules:\n"
        "- Tone: warm, professional, non-judgmental. Never shaming or alarmist.\n"
        "- Address the student by first name.\n"
        "- Reference 1-2 specific details from their record (year, concentration, a course). "
        "Do NOT state their exact GPA number.\n"
        "- For undeclared sophomores: acknowledge the declaration deadline is approaching, "
        "suggest 2-3 concentrations that plausibly fit signals in their record (e.g., "
        "strong VSB 2006/2008 => MIS or Business Analytics), and invite a 1:1 meeting.\n"
        "- For transfer students: acknowledge that they are new to VSB, point them to the "
        "transfer credit validation process, mention the New Student Orientation resources, "
        "and offer a 1:1 to map out their remaining VSB requirements based on what transferred in.\n"
        "- For freshmen: emphasize this is their foundation year, reference Business Dynamics I/II "
        "(VSB 1001/1002) when relevant, and orient them to the VSB advising calendar.\n"
        "- Never reference data the advisor doesn't have: internship status, clubs, careers.\n"
        "- Include ONE concrete next step.\n"
        "- Sign off exactly:\nDr. Alvarez\nVSB Academic Advising\n"
        "- 80-130 words, 3 short paragraphs.\n"
        "- Do NOT mention this was AI-generated."
    )
    slim = [
        {
            "id": s["id"],
            "name": s["name"],
            "first": s["first"],
            "year": s["year"],
            "concentration": s["concentration"],
            "gpa_band": s["gpa_band"],
            "transfer": s["transfer"],
            "completed": s["completed"],
            "current_grades": s["current_grades"],
            "flags": s["flags"],
        }
        for s in students
    ]
    msg = _claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": f'Campaign context: "{query}"\n\nStudents:\n{json.dumps(slim)}'}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    parsed = _extract_json(raw)
    drafts = []
    for d in parsed:
        drafts.append({"id": str(d["id"]), "subject": d["subject"], "body": d["body"]})
    return drafts


# ---------------------------------------------------------------------------
# Rule-based fallbacks (used if Claude API fails so demo never dies)
# ---------------------------------------------------------------------------
def rule_based_segment(query: str, contacts: list[dict]) -> list[str]:
    q = query.lower()
    matched = contacts[:]
    if any(k in q for k in ["at-risk", "at risk", "struggling", "below 2.7", "failing"]):
        matched = [c for c in matched if "at-risk" in c["flags"]]
    if "sophomore" in q: matched = [c for c in matched if c["year"] == "Sophomore"]
    if "junior"    in q: matched = [c for c in matched if c["year"] == "Junior"]
    if "senior"    in q: matched = [c for c in matched if c["year"] == "Senior"]
    if any(k in q for k in ["undeclared", "haven't declared", "have not declared",
                             "without a declared", "no concentration",
                             "not declared a concentration"]):
        matched = [c for c in matched if not c["concentration"]]
    for label, val in [("finance", "Finance"), ("accounting", "Accounting"),
                       ("marketing", "Marketing"), ("mis", "MIS"),
                       ("management", "Management")]:
        phrase = f"{label} concentration"
        if phrase in q or f"concentrating in {label}" in q:
            matched = [c for c in matched if c["concentration"] == val]
            break
    if "1003" in q or "bloomberg" in q:
        matched = [c for c in matched if "VSB 1003" not in c["completed"]]
    if "transfer" in q or "new to vsb" in q or "new student" in q:
        matched = [c for c in matched if c["transfer"]]
    if "capstone" in q or "4002" in q:
        matched = [c for c in matched if c["year"] == "Senior" and "VSB 4002" not in c["completed"]]
    return [c["id"] for c in matched[:10]]


def template_email(student: dict, query: str) -> dict:
    q = query.lower()
    first = student["first"] or student["name"].split(" ")[0]

    if "at-risk" in q or "struggling" in q or "2004" in q:
        subject = "Checking in on your VSB coursework"
        body = (
            f"Hi {first},\n\n"
            "I'm reaching out as your academic advisor to check in on how your semester is going. "
            "I noticed that Financial Accounting (VSB 2004) can be a challenging course for many sophomores, "
            "and I want to make sure you have the support you need to succeed.\n\n"
            "VSB offers free tutoring through the Center for Academic Achievement, and I'd love to set up "
            "a brief meeting to talk through your course plan and any adjustments we might make. "
            "There are also weekly office hours with the VSB 2004 instructors that many students find helpful.\n\n"
            "Please reply with a few times that work for you next week, or book directly via my advising calendar.\n\n"
            "Dr. Alvarez\nVSB Academic Advising"
        )
    elif "undeclared" in q or "concentration" in q or "declared" in q:
        subject = "Time to declare your VSB concentration"
        body = (
            f"Hi {first},\n\n"
            "As a sophomore, you're approaching the concentration declaration deadline, and my records "
            "show you haven't yet declared. I wanted to reach out personally before the window closes so "
            "we can make sure you pick a direction that fits you.\n\n"
            "VSB offers concentrations in Finance, Accounting, Marketing, Management, MIS, Business "
            "Analytics, Real Estate, and International Business. A short 1:1 conversation is usually "
            "the easiest way to narrow it down — we can look at the courses you've enjoyed, where "
            "your strengths are showing up, and what each concentration opens up.\n\n"
            "Could you book 15 minutes with me in the next two weeks? Reply with a few times, or use my "
            "advising calendar link.\n\n"
            "Dr. Alvarez\nVSB Academic Advising"
        )
    elif "1003" in q or "bloomberg" in q:
        subject = "Friendly reminder: Bloomberg Markets Concepts (VSB 1003)"
        body = (
            f"Hi {first},\n\n"
            "A quick note from your advisor: Bloomberg Markets Concepts (VSB 1003) is a VSB graduation "
            "requirement, and my records show it isn't yet complete on your transcript. Because it's "
            "self-paced, most students find it easiest to finish during a lighter semester rather than "
            "waiting until senior year.\n\n"
            "You can enroll through the Bloomberg terminals in Bartley, and it typically takes 8–10 hours "
            "total. It's 0 credits but must appear on your record to clear your degree audit.\n\n"
            "Let me know if you'd like help scheduling time on a terminal, or if you have questions about "
            "the requirement.\n\n"
            "Dr. Alvarez\nVSB Academic Advising"
        )
    elif "transfer" in q or "new to vsb" in q or "new student" in q:
        subject = "Welcome to VSB — let's set up a 1:1"
        body = (
            f"Hi {first},\n\n"
            "Welcome to the Villanova School of Business! As your academic advisor, I wanted to reach out "
            "now that you're settling into your first semester at VSB. Transfer students sometimes need a "
            "little extra support as we map your transferred credits onto the VSB curriculum and figure "
            "out which requirements you still need.\n\n"
            "I'd like to schedule a 1:1 with you in the next two weeks so we can review your degree audit "
            "together, talk through which VSB courses make sense for you next semester, and answer any "
            "questions about the transfer credit validation process.\n\n"
            "Reply with a few times that work, or use my advising calendar link.\n\n"
            "Dr. Alvarez\nVSB Academic Advising"
        )
    else:
        subject = "Following up on your VSB plan"
        body = (
            f"Hi {first},\n\n"
            "I wanted to reach out as your academic advisor to check in and make sure you have what you "
            f"need this semester. Based on where you are in the VSB curriculum as a {student['year'].lower()}, "
            "there are a few things worth discussing about your upcoming course choices and longer-term plan.\n\n"
            "If you have 15 minutes in the next two weeks, I'd love to connect. I can share some resources "
            "that other students in your situation have found useful and answer any questions you have.\n\n"
            "Reply with some times that work, or book directly through my advising calendar.\n\n"
            "Dr. Alvarez\nVSB Academic Advising"
        )
    return {"id": student["id"], "subject": subject, "body": body}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
HUBSPOT_ORANGE = "#FF7A59"

st.markdown(
    f"""
    <style>
      .vsb-header {{
        display: flex; align-items: center; justify-content: space-between;
        padding-bottom: 12px; border-bottom: 1px solid #eaeaea; margin-bottom: 24px;
      }}
      .vsb-brand {{
        display: flex; align-items: center; gap: 10px;
      }}
      .vsb-logo {{
        width: 32px; height: 32px; border-radius: 6px; background: #003366;
        display: flex; align-items: center; justify-content: center;
        color: white; font-weight: 600;
      }}
      .hs-chip {{
        display: inline-flex; align-items: center; gap: 6px;
        font-size: 12px; padding: 4px 10px; border-radius: 12px;
        background: #FFF1ED; color: {HUBSPOT_ORANGE};
        border: 1px solid #FFD4C2;
      }}
      .hs-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #22C55E; }}
      .pill {{
        display: inline-block; font-size: 11px; padding: 2px 8px;
        border-radius: 10px; margin-right: 4px;
      }}
      .pill-danger  {{ background: #FEE2E2; color: #991B1B; }}
      .pill-warn    {{ background: #FEF3C7; color: #92400E; }}
      .pill-purple  {{ background: #EDE9FE; color: #5B21B6; }}
      .pill-neutral {{ background: #F3F4F6; color: #374151; }}
    </style>
    <div class="vsb-header">
      <div class="vsb-brand">
        <div class="vsb-logo">V</div>
        <div>
          <div style="font-weight:600;">VSB Advisor Assistant</div>
          <div style="font-size:12px; color:#666;">AI-powered student outreach</div>
        </div>
      </div>
      <div class="hs-chip"><span class="hs-dot"></span>HubSpot connected</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Check credentials before anything else
missing = []
if not ANTHROPIC_API_KEY: missing.append("ANTHROPIC_API_KEY")
if not HUBSPOT_TOKEN:     missing.append("HUBSPOT_TOKEN")
if missing:
    st.error(
        "Missing Streamlit secrets: " + ", ".join(missing) +
        ". Add them in App settings → Secrets before using this app."
    )
    st.stop()

# SMTP is optional — if not configured the app still works, just doesn't deliver.
if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
    st.warning(
        "Email send is not configured — approvals will log to HubSpot but no email "
        "will actually be delivered. Add SMTP_EMAIL and SMTP_APP_PASSWORD in App "
        "settings → Secrets to enable real delivery."
    )

# Session state
if "segment" not in st.session_state: st.session_state.segment = []
if "drafts"  not in st.session_state: st.session_state.drafts  = []
if "activity" not in st.session_state: st.session_state.activity = []
if "last_query" not in st.session_state: st.session_state.last_query = ""


# Pull contacts (cached 60s)
try:
    contacts = fetch_all_vsb_contacts()
except Exception as e:
    st.error(f"Couldn't reach HubSpot: {e}")
    st.stop()

# Top metrics row
c1, c2, c3, c4 = st.columns(4)
c1.metric("HubSpot contacts",     len(contacts))
c2.metric("In active list",       len(st.session_state.segment))
c3.metric("Drafts pending",       sum(1 for d in st.session_state.drafts if not d.get("sent")))
c4.metric("Engagements logged",   len(st.session_state.activity))

st.markdown("### Quick-start campaigns")
QUICKSTARTS = [
    ("At-risk sophomores",
     "GPA < 2.7, struggling in VSB 2004",
     "Find all sophomores with GPA below 2.7 who are struggling in Financial Accounting (VSB 2004). "
     "Draft check-in emails offering tutoring resources and office hours."),
    ("Undeclared sophomores",
     "No concentration declared",
     "Find all sophomores who have not yet declared a concentration. Draft outreach emails about the "
     "upcoming concentration declaration deadline, the available VSB concentrations, and scheduling "
     "a 1:1 advising appointment to discuss options."),
    ("Missing Bloomberg cert",
     "VSB 1003 graduation requirement",
     "Find students who haven't completed Bloomberg Markets Concepts (VSB 1003) but need it for "
     "graduation. Draft reminder emails with enrollment steps."),
    ("Transfer student onboarding",
     "Transfer students, all years",
     "Find all transfer students who are new to VSB. Draft welcome emails offering a "
     "1:1 advising appointment to walk through their transferred credits, the VSB degree "
     "audit, and which requirements they still need to complete."),
]

qs_cols = st.columns(2)
for i, (title, desc, query) in enumerate(QUICKSTARTS):
    with qs_cols[i % 2]:
        if st.button(f"**{title}**\n\n*{desc}*", key=f"qs_{i}", use_container_width=True):
            st.session_state.last_query = query

st.markdown("#### Or describe a custom segment")
custom_col1, custom_col2 = st.columns([5, 1])
with custom_col1:
    custom_query = st.text_input(
        label="custom",
        value=st.session_state.last_query,
        placeholder="e.g., 'seniors missing Strategic Thinking'",
        label_visibility="collapsed",
        key="custom_query",
    )
with custom_col2:
    run_clicked = st.button("Run", use_container_width=True, type="primary")

if run_clicked and custom_query.strip():
    st.session_state.last_query = custom_query.strip()
elif st.session_state.last_query and not st.session_state.segment:
    # a quick-start was just clicked — run automatically
    pass

# Trigger segmentation whenever last_query changed and we have no matching segment yet
def run_campaign(query: str):
    with st.status("Running campaign...", expanded=False) as status:
        status.update(label="Querying HubSpot and segmenting with Claude...")
        try:
            ids = claude_segment(query, contacts)
            used_fallback_seg = False
        except Exception as e:
            st.warning(f"AI segmentation unavailable ({e.__class__.__name__}); using rule-based fallback.")
            ids = rule_based_segment(query, contacts)
            used_fallback_seg = True
        matched = [c for c in contacts if c["id"] in ids]
        st.session_state.segment = matched
        st.session_state.drafts = []
        if not matched:
            status.update(label="No contacts matched.", state="complete")
            return
        status.update(label=f"Drafting {len(matched)} personalized emails with Claude...")
        try:
            drafts = claude_draft_emails(query, matched)
        except Exception as e:
            st.warning(f"AI email drafting unavailable ({e.__class__.__name__}); using templates.")
            drafts = [template_email(s, query) for s in matched]
        # Build final draft objects
        by_id = {s["id"]: s for s in matched}
        st.session_state.drafts = [
            {
                "id": d["id"],
                "student": by_id.get(d["id"]),
                "subject": d["subject"],
                "body": d["body"],
                "sent": False,
            }
            for d in drafts if d["id"] in by_id
        ]
        status.update(label=f"Done. {len(st.session_state.drafts)} drafts ready for review.", state="complete")


# Run if query is set and nothing loaded yet, or if user just clicked Run
should_run = run_clicked and custom_query.strip()
should_run = should_run or (st.session_state.last_query and not st.session_state.segment and not run_clicked)
if should_run:
    query_to_run = custom_query.strip() if run_clicked and custom_query.strip() else st.session_state.last_query
    run_campaign(query_to_run)

# --- Segment panel --------------------------------------------------------
st.markdown("---")
st.markdown("### HubSpot active list")

if not st.session_state.segment:
    st.info("Pick a quick-start campaign above or describe a custom segment. "
            "The assistant will query HubSpot and return matching contacts.")
else:
    st.caption(f"{len(st.session_state.segment)} contacts matched — data pulled from your HubSpot portal")
    for s in st.session_state.segment:
        pill_map = {
            "at-risk":         ("pill-danger",  "At risk"),
            "undeclared":      ("pill-warn",    "Undeclared"),
            "missing-1003":    ("pill-warn",    "Missing VSB 1003"),
            "missing-capstone":("pill-warn",    "Missing capstone"),
            "transfer-student": ("pill-purple",  "Transfer student"),
        }
        flags_html = "".join(
            f'<span class="pill {pill_map.get(f, ("pill-neutral", f))[0]}">{pill_map.get(f, ("pill-neutral", f))[1]}</span>'
            for f in s["flags"]
        )
        concentration_display = s["concentration"] or "Undeclared"
        st.markdown(
            f"""
            <div style="padding:10px 0; border-bottom:1px solid #eee;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                  <strong>{s['name']}</strong><br>
                  <span style="font-size:12px; color:#666;">
                    {s['year']} • {concentration_display} • GPA {s['gpa']:.2f} • {s['email']}
                  </span>
                </div>
                <div>{flags_html}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# --- Drafts panel ---------------------------------------------------------
if st.session_state.drafts:
    st.markdown("---")
    st.markdown("### Email drafts")
    st.caption("Each draft is editable before sending. Approve logs the email to HubSpot as an engagement.")

    for i, d in enumerate(st.session_state.drafts):
        student = d["student"]
        if student is None:
            continue
        with st.container(border=True):
            st.markdown(
                f'<span class="hs-chip">HubSpot contact</span> '
                f'&nbsp;To: **{student["name"]}** &lt;{student["email"]}&gt; '
                f'<span style="color:#888;">• {student["concentration"] or "Undeclared"}</span>',
                unsafe_allow_html=True,
            )
            new_subject = st.text_input("Subject", value=d["subject"], key=f"subj_{i}")
            new_body = st.text_area("Body", value=d["body"], height=220, key=f"body_{i}")

            if d.get("sent"):
                st.success(f"✓ Logged to HubSpot at {d.get('sent_at','')}" + (f" • Email sent to {student['email']}" if d.get("email_sent") else ""))
            else:
                col_a, col_b = st.columns([1, 5])
                with col_a:
                    if st.button("Approve & send", key=f"send_{i}", type="primary"):
                        # 1. Always log to HubSpot first — the audit trail is non-negotiable
                        ok = log_outreach_to_contact(student["id"], new_subject, new_body)
                        if not ok:
                            st.error("HubSpot rejected the update. Check Private App scopes: "
                                     "crm.objects.contacts.read/write and "
                                     "crm.schemas.contacts.read/write must be enabled.")
                        else:
                            d["subject"] = new_subject
                            d["body"] = new_body
                            d["sent"] = True
                            d["sent_at"] = datetime.now().strftime("%I:%M %p")
                            # 2. Then attempt the actual Outlook send (best-effort)
                            sent_ok, send_msg = send_via_smtp(student["email"], new_subject, new_body)
                            d["email_sent"] = sent_ok
                            d["email_send_msg"] = send_msg
                            if sent_ok:
                                st.session_state.activity.append({
                                    "name": student["name"],
                                    "subject": new_subject,
                                    "time": d["sent_at"],
                                    "delivered": True,
                                })
                            else:
                                # Logged but not delivered — show why, don't block the demo
                                st.warning(f"Logged to HubSpot, but email not delivered: {send_msg}")
                                st.session_state.activity.append({
                                    "name": student["name"],
                                    "subject": new_subject,
                                    "time": d["sent_at"],
                                    "delivered": False,
                                })
                            st.rerun()
                with col_b:
                    if st.button("Discard", key=f"discard_{i}"):
                        st.session_state.drafts.pop(i)
                        st.rerun()

# --- Activity timeline ----------------------------------------------------
st.markdown("---")
st.markdown("### HubSpot engagement timeline")
if not st.session_state.activity:
    st.info("Approved emails appear on each contact's HubSpot timeline as an Email engagement.")
else:
    for a in reversed(st.session_state.activity):
        delivered = a.get("delivered", False)
        chip_label = "Sent" if delivered else "Logged"
        chip_style = "background:#DCFCE7;color:#166534;border:1px solid #BBF7D0;" if delivered else ""
        st.markdown(
            f'<span class="hs-chip" style="{chip_style}">{chip_label}</span> &nbsp;**{a["name"]}** — {a["subject"]} '
            f'<span style="color:#888; float:right;">{a["time"]}</span>',
            unsafe_allow_html=True,
        )

# --- Architecture footer --------------------------------------------------
with st.expander("▸ Architecture note"):
    st.markdown(
        """
        **Flow:** Advisor prompt → Claude API (segmentation reasoning) →
        HubSpot Contacts API `GET /crm/v3/objects/contacts/search` with
        custom properties (`vsb_year`, `vsb_concentration`, `vsb_gpa_band`,
        `vsb_transfer_student`, `vsb_completed_courses`, `vsb_current_grades`,
        `vsb_flags`) → Claude API (per-student email drafting) → Advisor
        review & edit → on approval, two things happen in parallel:
        (1) HubSpot Contacts API `PATCH /crm/v3/objects/contacts/{id}` writes
        the approved outreach back to the student's contact record as
        `vsb_last_outreach_*` properties for the audit trail, and
        (2) the email is delivered to the student via SMTP
        (defaults to `smtp.gmail.com:587`, configurable via the `SMTP_HOST` secret).

        All student data lives in HubSpot and originates from the student
        information system (Banner) in production. Advisors never see Career
        Services (Handshake) data. A rule-based segmentation + templated
        email fallback kicks in automatically if the Claude API is
        unreachable, and the HubSpot write is the source of truth — if the
        Outlook send fails, the advisor still has a logged record of what
        was approved. Production would swap the SMTP send for HubSpot's
        Transactional Email API, which adds bounce handling, open/click
        tracking, and unsubscribe management.
        """
    )
