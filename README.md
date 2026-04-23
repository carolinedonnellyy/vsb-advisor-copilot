# VSB Advisor Copilot

AI-powered student outreach tool for VSB academic advisors. Integrates
**Claude** (for segmentation + email drafting) with **HubSpot** (as the CRM
of record) and deploys to **Streamlit Community Cloud** for free.

---

## What this does

1. Advisor picks a quick-start campaign (or writes a custom one) like
   *"Find all sophomores who haven't declared a concentration"*.
2. Claude reads the advisor's real HubSpot contacts and returns the matching
   student IDs.
3. Claude drafts a personalized email for each matched student that references
   specific details from their record (year, concentration signals, courses
   completed).
4. Advisor reviews, edits, and approves each draft.
5. Approved emails are logged as real Email engagements on each student's
   HubSpot contact timeline.

If the Claude API is unreachable the app falls back to rule-based segmentation
and templated emails, so the demo never dies completely.

---

## File layout

```
vsb-advisor-copilot/
├── app.py              # the Streamlit app
├── hubspot_setup.py    # one-time seed script (run locally, once)
├── requirements.txt    # dependencies for Streamlit Cloud
└── README.md           # this file
```

---

## One-time setup (do this once as a team, ~25 minutes total)

### 1. Create a HubSpot Private App and grab the access token

1. Sign into your HubSpot account (a regular portal, not a developer account —
   URL should be `app.hubspot.com` or `app-naN.hubspot.com`, not
   `developers.hubspot.com`).
2. Go to **Settings (gear icon) → Integrations → Private Apps**. In newer
   portals this lives under **Legacy Apps** with a "Your private apps have
   moved" redirect — that's fine, follow it.
3. Click **Create a private app**.
4. Name it `VSB Advisor Copilot`.
5. On the **Scopes** tab, enable exactly these four:
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.schemas.contacts.read`
   - `crm.schemas.contacts.write`
6. Click **Create app** → **Continue creating** → then **Show token** and copy it.
   It looks like `pat-naN-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.

**Why only four scopes?** HubSpot free-tier portals don't expose email
engagement or notes write scopes. So instead of logging approved outreach
as a timeline engagement, this app writes the approved outreach (subject,
body, timestamp) directly back to the student's contact record as custom
properties (`vsb_last_outreach_*`). Same demo story, same CRM narrative —
opening any contact in HubSpot shows exactly what was sent and when.

### 2. Get a Claude API key

1. Sign into https://console.anthropic.com.
2. Go to **API Keys** in the left sidebar → **Create Key**.
3. Copy the key. It looks like `sk-ant-api03-xxxxxxxx`.

New accounts get free credits. This demo uses well under $1 of credits
for a full class presentation.

### 3. Seed HubSpot with the 24 VSB test contacts

Clone this repo locally, then from inside the project folder:

```bash
pip install -r requirements.txt
export HUBSPOT_TOKEN="pat-na1-xxxxxxxx"     # paste yours
python hubspot_setup.py
```

This creates 8 custom contact properties on your HubSpot Contact object
(`vsb_year`, `vsb_concentration`, `vsb_gpa`, `vsb_gpa_band`,
`vsb_honors_college`, `vsb_completed_courses`, `vsb_current_grades`,
`vsb_flags`) and inserts 24 mock VSB students.

Safe to re-run — existing properties are skipped, existing contacts
(matched by email) are updated.

**Verify:** open HubSpot → **Contacts**. You should see 24 new contacts.
Click one (e.g. Aisha Patel) → scroll to **About** → confirm the VSB
custom properties are populated.

### 4. Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repo (public is fine — no secrets in the code).
2. Sign into https://share.streamlit.io with your GitHub.
3. Click **New app** → pick the repo → set main file path to `app.py` → **Deploy**.
4. Once deploying, click the three-dots menu → **Settings** → **Secrets**, and paste:

    ```toml
    ANTHROPIC_API_KEY = "sk-ant-api03-xxxxxxxx"
    HUBSPOT_TOKEN     = "pat-na1-xxxxxxxx"
    ```

5. Wait ~60 seconds for the app to restart. You should see the advisor UI
   with "HubSpot connected" in green.

Your public URL will look like `https://<your-app>.streamlit.app` — share
that with the professor.

---

## Demo-day checklist

- [ ] App URL loads (test morning of)
- [ ] "HubSpot contacts: 24" is showing at the top
- [ ] Click **At-risk sophomores** button — should return 6 students
  including Aisha Patel and Lucas Fernandez
- [ ] Open one generated draft, edit a sentence, click **Approve & send**
- [ ] Switch over to HubSpot in another tab → open that student's contact →
  scroll to the **About** section and show the `VSB Last Outreach Subject`,
  `VSB Last Outreach Body`, and `VSB Last Outreach Sent At` fields populated
  with exactly what you just approved in the app
- [ ] Back in the app, click **Undeclared sophomores** — should return 6
  students with varying academic profiles (at-risk, honors college, mid-range)
- [ ] Type a custom query: *"undeclared honors college sophomores"* → should
  return just Liam and Priya

Total demo time: 4–5 minutes of clicking through, plenty of narration
breathing room for the full 7-minute presentation.

---

## Troubleshooting

**"Couldn't reach HubSpot"** at the top of the app
: Your `HUBSPOT_TOKEN` secret is either wrong or missing the scopes listed
  above. Re-check in App → Settings → Secrets.

**Claude API error shown**
: Either `ANTHROPIC_API_KEY` is wrong, or you're out of credits. The app
  will automatically fall back to rule-based segmentation and templated
  emails, so the demo keeps working.

**Contact I expect to match isn't showing up**
: Open the contact in HubSpot and check the `vsb_flags` custom property.
  If it's blank, re-run `hubspot_setup.py`.

**App shows 0 contacts**
: You probably forgot to run `hubspot_setup.py`, or it ran against a
  different HubSpot portal. The token and the seed script must target
  the same portal.

---

## Cost sanity check

- HubSpot free tier: 1,000 contacts allowed — we use 24. Free.
- Claude API: each campaign call is ~4k input tokens + ~1.5k output
  tokens ≈ $0.03. Ten campaigns during rehearsal + demo ≈ $0.30 total.
- Streamlit Community Cloud: free for public apps.

---

## What this would look like in production

- Banner (the student info system) would sync nightly to HubSpot via a
  scheduled Python job, replacing the manual `hubspot_setup.py` seed.
- Emails would send through HubSpot's Transactional Email API rather than
  just logging as engagements.
- Advisor authentication would use Villanova SSO, and each advisor would
  see only their assigned students via HubSpot's teams + list permissions.
- The rule-based fallback would become a proper second path triggered by
  circuit-breaker logic rather than a blanket try/except.
