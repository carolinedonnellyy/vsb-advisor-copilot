"""
hubspot_setup.py

ONE-TIME setup script.
Run this locally ONCE before deploying the Streamlit app. It:
  1. Creates the custom contact properties the advisor copilot needs
     (vsb_year, vsb_concentration, vsb_gpa, vsb_gpa_band, vsb_honors_college,
      vsb_completed_courses, vsb_current_grades, vsb_flags)
  2. Seeds 24 mock VSB students as HubSpot contacts for the demo.

Usage:
    export HUBSPOT_TOKEN="pat-na1-xxxxxxxx..."
    python hubspot_setup.py

If a property already exists it is skipped (safe to re-run).
If a contact email already exists it is updated (idempotent).
"""

import os
import sys
import json
import time
import requests

HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN")
if not HUBSPOT_TOKEN:
    print("ERROR: Set the HUBSPOT_TOKEN environment variable before running.")
    print('  Example:  export HUBSPOT_TOKEN="pat-na1-xxxxxxxx"')
    sys.exit(1)

BASE = "https://api.hubapi.com"
HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# 1. Custom properties to create on the Contact object
# ---------------------------------------------------------------------------
CUSTOM_PROPERTIES = [
    {
        "name": "vsb_year",
        "label": "VSB Year",
        "type": "enumeration",
        "fieldType": "select",
        "groupName": "contactinformation",
        "options": [
            {"label": "Freshman", "value": "Freshman"},
            {"label": "Sophomore", "value": "Sophomore"},
            {"label": "Junior", "value": "Junior"},
            {"label": "Senior", "value": "Senior"},
        ],
    },
    {
        "name": "vsb_concentration",
        "label": "VSB Concentration",
        "type": "string",
        "fieldType": "text",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_gpa",
        "label": "VSB GPA",
        "type": "number",
        "fieldType": "number",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_gpa_band",
        "label": "VSB GPA Band",
        "type": "string",
        "fieldType": "text",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_honors_college",
        "label": "VSB Honors College",
        "type": "bool",
        "fieldType": "booleancheckbox",
        "groupName": "contactinformation",
        "options": [
            {"label": "Yes", "value": "true"},
            {"label": "No", "value": "false"},
        ],
    },
    {
        "name": "vsb_completed_courses",
        "label": "VSB Completed Courses",
        "type": "string",
        "fieldType": "textarea",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_current_grades",
        "label": "VSB Current Grades (JSON)",
        "type": "string",
        "fieldType": "textarea",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_flags",
        "label": "VSB Flags",
        "type": "string",
        "fieldType": "text",
        "groupName": "contactinformation",
    },
    # Last-outreach tracking. Written back when the advisor approves a draft.
    {
        "name": "vsb_last_outreach_subject",
        "label": "VSB Last Outreach Subject",
        "type": "string",
        "fieldType": "text",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_last_outreach_body",
        "label": "VSB Last Outreach Body",
        "type": "string",
        "fieldType": "textarea",
        "groupName": "contactinformation",
    },
    {
        "name": "vsb_last_outreach_sent_at",
        "label": "VSB Last Outreach Sent At",
        "type": "datetime",
        "fieldType": "date",
        "groupName": "contactinformation",
    },
]


def create_property(prop):
    """Create one custom property; skip if it already exists."""
    url = f"{BASE}/crm/v3/properties/contacts"
    r = requests.post(url, headers=HEADERS, json=prop, timeout=30)
    if r.status_code in (200, 201):
        print(f"  created property: {prop['name']}")
    elif r.status_code == 409:
        print(f"  already exists:   {prop['name']}")
    else:
        print(f"  FAILED {prop['name']}: {r.status_code} {r.text[:200]}")


# ---------------------------------------------------------------------------
# 2. Seed data — 24 mock VSB students
# ---------------------------------------------------------------------------
STUDENTS = [
    # Sophomores - at-risk
    {"first": "Aisha",    "last": "Patel",     "email": "apatel@villanova.edu",     "year": "Sophomore", "concentration": "",             "gpa": 2.50, "honors": False, "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2005"],                         "grades": {"VSB 2004":"D+","VSB 2009":"C-"}, "flags": ["at-risk","undeclared"]},
    {"first": "Marcus",   "last": "Chen",      "email": "mchen@villanova.edu",      "year": "Sophomore", "concentration": "Accounting",   "gpa": 2.60, "honors": False, "completed": ["VSB 1001","VSB 1002","VSB 2004"],                                     "grades": {"VSB 2014":"D"},                  "flags": ["at-risk"]},
    {"first": "Sophia",   "last": "Ramirez",   "email": "sramirez@villanova.edu",   "year": "Sophomore", "concentration": "Marketing",    "gpa": 2.40, "honors": False, "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2005","VSB 2006"],               "grades": {"VSB 2004":"C-"},                 "flags": ["at-risk"]},
    {"first": "Lucas",    "last": "Fernandez", "email": "lfernandez@villanova.edu", "year": "Sophomore", "concentration": "",             "gpa": 2.65, "honors": False, "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2005"],                         "grades": {"VSB 2004":"D","VSB 2005":"C"},   "flags": ["at-risk","undeclared"]},
    {"first": "Alexander","last": "Kim",       "email": "akim@villanova.edu",       "year": "Sophomore", "concentration": "",             "gpa": 2.50, "honors": False, "completed": ["VSB 1001","VSB 1002","VSB 2004"],                                     "grades": {"VSB 2004":"D+","VSB 2009":"D"},  "flags": ["at-risk","undeclared"]},
    {"first": "Ryan",     "last": "Sullivan",  "email": "rsullivan@villanova.edu",  "year": "Sophomore", "concentration": "",             "gpa": 2.55, "honors": False, "completed": ["VSB 1001","VSB 1002","VSB 2004"],                                     "grades": {"VSB 2004":"C-","VSB 2005":"D+"}, "flags": ["at-risk","undeclared"]},

    # Sophomores - honors college
    {"first": "Olivia",   "last": "Brennan",   "email": "obrennan@villanova.edu",   "year": "Sophomore", "concentration": "MIS",          "gpa": 3.80, "honors": True,  "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2005","VSB 2006","VSB 1003"],   "grades": {},                                "flags": ["honors-college"]},
    {"first": "Liam",     "last": "O'Connor",  "email": "loconnor@villanova.edu",   "year": "Sophomore", "concentration": "",             "gpa": 3.50, "honors": True,  "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2005","VSB 1003"],              "grades": {},                                "flags": ["honors-college","undeclared"]},
    {"first": "Ava",      "last": "Thompson",  "email": "athompson@villanova.edu",  "year": "Sophomore", "concentration": "Marketing",    "gpa": 3.30, "honors": True,  "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2006","VSB 1003"],              "grades": {},                                "flags": ["honors-college"]},
    {"first": "Chloe",    "last": "Wright",    "email": "cwright@villanova.edu",    "year": "Sophomore", "concentration": "Accounting",   "gpa": 3.70, "honors": True,  "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2014","VSB 1003"],              "grades": {},                                "flags": ["honors-college"]},
    {"first": "Priya",    "last": "Desai",     "email": "pdesai@villanova.edu",     "year": "Sophomore", "concentration": "",             "gpa": 3.85, "honors": True,  "completed": ["VSB 1001","VSB 1002","VSB 2004","VSB 2006","VSB 2008","VSB 1003"],   "grades": {},                                "flags": ["honors-college","undeclared"]},

    # Juniors
    {"first": "Jordan",   "last": "Williams",  "email": "jwilliams@villanova.edu",  "year": "Junior",    "concentration": "Finance",      "gpa": 3.40, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 2020","VSB 1003"],              "grades": {},                                "flags": []},
    {"first": "Emily",    "last": "Nguyen",    "email": "enguyen@villanova.edu",    "year": "Junior",    "concentration": "Finance",      "gpa": 3.60, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 1003","VSB 3008"],              "grades": {},                                "flags": []},
    {"first": "David",    "last": "Park",      "email": "dpark@villanova.edu",      "year": "Junior",    "concentration": "Finance",      "gpa": 3.20, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010"],                                     "grades": {},                                "flags": ["missing-1003"]},
    {"first": "Ethan",    "last": "Kumar",     "email": "ekumar@villanova.edu",     "year": "Junior",    "concentration": "Finance",      "gpa": 3.30, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 2020"],                         "grades": {},                                "flags": ["missing-1003"]},
    {"first": "Grace",    "last": "Donovan",   "email": "gdonovan@villanova.edu",   "year": "Junior",    "concentration": "Marketing",    "gpa": 2.80, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2006","VSB 2020"],                         "grades": {},                                "flags": ["missing-1003"]},
    {"first": "Benjamin", "last": "Shah",      "email": "bshah@villanova.edu",      "year": "Junior",    "concentration": "MIS",          "gpa": 3.55, "honors": False, "completed": ["VSB 2006","VSB 2008","VSB 2004","VSB 2009","VSB 1003"],              "grades": {},                                "flags": []},
    {"first": "Mia",      "last": "Callahan",  "email": "mcallahan@villanova.edu",  "year": "Junior",    "concentration": "Finance",      "gpa": 3.40, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 1003","VSB 3008"],              "grades": {},                                "flags": []},
    {"first": "Henry",    "last": "Walsh",     "email": "hwalsh@villanova.edu",     "year": "Junior",    "concentration": "Accounting",   "gpa": 3.25, "honors": False, "completed": ["VSB 2004","VSB 2014","VSB 2009","VSB 2020"],                         "grades": {},                                "flags": ["missing-1003"]},
    {"first": "Natalie",  "last": "Cho",       "email": "ncho@villanova.edu",       "year": "Junior",    "concentration": "Finance",      "gpa": 3.45, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 1003"],                         "grades": {},                                "flags": []},

    # Seniors
    {"first": "Noah",     "last": "Bennett",   "email": "nbennett@villanova.edu",   "year": "Senior",    "concentration": "Management",   "gpa": 3.10, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 2020","VSB 3008","VSB 1003"],   "grades": {},                                "flags": ["missing-capstone"]},
    {"first": "Isabella", "last": "Rossi",     "email": "irossi@villanova.edu",     "year": "Senior",    "concentration": "Accounting",   "gpa": 3.50, "honors": False, "completed": ["VSB 2004","VSB 2014","VSB 2010","VSB 2020","VSB 1003","VSB 3008"],   "grades": {},                                "flags": ["missing-capstone"]},
    {"first": "Zoe",      "last": "Martinez",  "email": "zmartinez@villanova.edu",  "year": "Senior",    "concentration": "Marketing",    "gpa": 3.40, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2006","VSB 2020","VSB 1003","VSB 3008"],   "grades": {},                                "flags": ["missing-capstone"]},
    {"first": "Jason",    "last": "Pierce",    "email": "jpierce@villanova.edu",    "year": "Senior",    "concentration": "Finance",      "gpa": 3.60, "honors": False, "completed": ["VSB 2004","VSB 2009","VSB 2010","VSB 2020","VSB 1003","VSB 3008"],   "grades": {},                                "flags": ["missing-capstone"]},
]


def gpa_band(gpa: float) -> str:
    if gpa < 2.7: return "below 2.7"
    if gpa < 3.0: return "2.7-3.0"
    if gpa < 3.5: return "3.0-3.5"
    return "3.5+"


def upsert_contact(s: dict):
    """Create or update one contact (idempotent by email)."""
    properties = {
        "email": s["email"],
        "firstname": s["first"],
        "lastname": s["last"],
        "vsb_year": s["year"],
        "vsb_concentration": s["concentration"],
        "vsb_gpa": str(s["gpa"]),
        "vsb_gpa_band": gpa_band(s["gpa"]),
        "vsb_honors_college": "true" if s["honors"] else "false",
        "vsb_completed_courses": ",".join(s["completed"]),
        "vsb_current_grades": json.dumps(s["grades"]),
        "vsb_flags": ",".join(s["flags"]),
    }
    # Try CREATE first; on 409 (already exists) fall back to UPDATE by email
    url = f"{BASE}/crm/v3/objects/contacts"
    r = requests.post(url, headers=HEADERS, json={"properties": properties}, timeout=30)
    if r.status_code in (200, 201):
        print(f"  created:  {s['email']}")
        return
    if r.status_code == 409:
        # Conflict => contact already exists. Look up by email and PATCH.
        search_url = f"{BASE}/crm/v3/objects/contacts/search"
        search_body = {
            "filterGroups": [{
                "filters": [{"propertyName": "email", "operator": "EQ", "value": s["email"]}]
            }],
            "limit": 1,
        }
        sr = requests.post(search_url, headers=HEADERS, json=search_body, timeout=30)
        if sr.status_code == 200 and sr.json().get("results"):
            cid = sr.json()["results"][0]["id"]
            pr = requests.patch(f"{BASE}/crm/v3/objects/contacts/{cid}",
                                headers=HEADERS, json={"properties": properties}, timeout=30)
            if pr.status_code == 200:
                print(f"  updated:  {s['email']}")
            else:
                print(f"  UPDATE FAILED {s['email']}: {pr.status_code} {pr.text[:200]}")
        else:
            print(f"  SEARCH FAILED {s['email']}: {sr.status_code} {sr.text[:200]}")
    else:
        print(f"  CREATE FAILED {s['email']}: {r.status_code} {r.text[:200]}")


def main():
    print("=" * 60)
    print("VSB Advisor Copilot — HubSpot setup")
    print("=" * 60)

    print("\nStep 1/2  Creating custom properties on the Contact object...")
    for prop in CUSTOM_PROPERTIES:
        create_property(prop)
        time.sleep(0.2)  # polite throttle

    print("\nStep 2/2  Seeding 24 VSB test contacts...")
    for s in STUDENTS:
        upsert_contact(s)
        time.sleep(0.2)

    print("\nDone. Open HubSpot → Contacts to verify. You should see all 24 students")
    print("with populated VSB custom properties. You can now deploy the Streamlit app.")


if __name__ == "__main__":
    main()
