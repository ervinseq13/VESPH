# VESPH Care — Virtual Engagement System for Patient Health

An intelligent, multi-agent post-discharge clinical coordination platform bridging the gap between hospital discharge and outpatient recovery. Powered by Streamlit, LangGraph, Groq LLM inference, and live Supabase PostgreSQL storage.

---

## What is Included

### 1. 👤 Patient Care Portal
- **Surgical Recovery Timeline:** Longitudinal trajectory of clinical events, surgical history (*Laparoscopic appendectomy*), and current milestones.
- **Mealtime Medication Tracking:** Active prescriptions grouped strictly by daily meals:
  - 🍳 **Breakfast (Morning):** e.g., *Pantocid 40 mg* (empty stomach before breakfast)
  - 🥗 **Lunch (Afternoon):** e.g., *Dolo 650 mg* (SOS for pain relief)
  - 🍲 **Dinner (Night):** e.g., *Budecort Inhaler 200 mcg*, *Shelcal 500 mg*
  - **Live Checkoff & Natural Language Intake Sync:** Patients can toggle the **✓ Taken** checkbox directly or message *"I took dolo"*, which automatically marks the dose as taken in Supabase and dismisses pending meal alerts from the Notification Centre.
- **Appointment Management & Auto-Accepted Rescheduling:**
  - View upcoming visits with attending physicians, room locations, and prep instructions.
  - Interactive self-service rescheduling with open slots based on the clinic's 15-minute cadence. Open slots are confirmed immediately.
- **Diagnostic Reports & Download Center:** Instant view of laboratory trends (Complete Blood Count, Histopathology) and branded PDF exports.
- **Interactive Patient Care Assistant:** Scoped, empathetic chat for answering recovery questions, discharge guidelines, dietary rules, and emergency escalations.

### 2. 🩺 Doctor Practice Portal (Dr. Rhea Mehta, Lead Laparoscopic Surgeon)
- **Weekly Clinic Agenda & Multi-Week Selector:**
  - Fast switching between **This Week (18–24 Oct)**, **Next Week (25–31 Oct)**, and **All Scheduled**.
  - Interactive day-of-week tabs (Sun through Sat) with appointment counts, patient demographics, visit types, and status badges.
- **Doctor Unavailability & Automated Patient Conflict Rebooking:**
  - Mark full clinic days or specific timeslots as blocked (e.g. *Emergency Surgery*, *Leave*).
  - Automatically detects all conflicting patient visits, computes the physician's next open fallback slots, updates the appointments to **`Pending`** status in Supabase, and dispatches priority notifications asking patients to confirm.
- **Patient Clinical Chart Modal:** In-depth modal dialog displaying a patient's historical vitals (BP, sugar, weight), surgical records, active prescriptions with pill badges, and previous consultations.
- **15-Minute Slot Generation with 5-Minute Buffers:** Dynamic scheduling across morning (**09:00–13:00**) and afternoon (**14:00–17:00**) OPD sessions.
- **RAG Consultation Document Ingestion Agent:**
  - Attending physicians can paste raw consultation notes or upload consultation PDFs.
  - The pipeline extracts primary diagnosis, recorded vitals, prescribed medications by mealtime, ordered lab tests, and follow-up appointments, presenting a structured preview for doctor confirmation before committing transactional updates to Supabase.

### 3. 🛡️ Deterministic Safety & Hybrid Intelligence
- **Dual Persona Prompts:** Strict system prompts preventing general medical advice or hallucinated bookings.
- **Deterministic Emergency Escalation:** Immediate emergency response (*call +91 22 4000 1122*) followed by patient action confirmation tickets.
- **PostgreSQL Enum Hardening:** Strict adherence to database enum constraints (`appointment_status_enum`), normalizing date adjustments to `"Pending"`.
- **Standardized Short IDs:** Clean, human-readable short identifiers across the application (`PID-8421`, `DOC-RHEA-01`, `MED-6661`, `APT-1001`, `CON-1001`, `LAB-1001`).

---

## Architecture at a Glance

```text
Streamlit Client Layer
   ├── 👤 Patient Portal (Timeline, Mealtime Meds, Labs, Care Chat)
   └── 🩺 Doctor Portal (Weekly Agenda, Unavailability Blocking, Clinical Charts, RAG Ingestion)
            │
            ▼
   Orchestration Layer
   ├── LangGraph StateGraph (Patient Multi-Agent Workflow)
   ├── Doctor Orchestrator (Schedule Checker, Availability Manager, Chart Review)
   └── RAG Consultation Ingestion Engine (pypdf + Groq Clinical NLP)
            │
            ▼
   Data & Intelligence Layer
   ├── Groq Cloud Inference (openai/gpt-oss-20b)
   └── Supabase Cloud PostgreSQL (10 Relational Tables)
```

---

## Live Cloud Database (Supabase PostgreSQL)

VESPH Care is backed by a live Supabase PostgreSQL database consisting of 10 normalized tables:

1. `patients` — Demographic baselines and longitudinal clinical summary.
2. `doctors` — Attending physician profiles, departments, and credentials.
3. `appointments` — OPD and follow-up schedules with strict `appointment_status_enum` constraints (`Confirmed`, `Pending`, `Completed`, `Cancelled`, `Rescheduled`).
4. `consultations` — Encounter records, recorded vitals (BP, sugar, weight), and diagnoses.
5. `medicines` — Master pharmaceutical catalog.
6. `prescription_details` — Patient prescriptions with meal timings (`breakfast`, `lunch`, `dinner`) and `is_taken` tracking.
7. `diagnostics` — Laboratory and pathology test orders.
8. `diagnostics_results` — Quantitative readings, reference ranges, and diagnostic summaries.
9. `doctor_unavailability` — Blocked clinic dates and leave records.
10. `escalation_agent_data` — Patient safety escalations, critical tickets, and resolution records.

> **Database Reset Mechanism:** Click **↺ Reset Database & State** in the top navigation bar at any time to re-seed all tables to canonical baseline demo state via `tools/seed_data.py`.

---

## Local Development Quickstart

### Prerequisites
- Python 3.11 or 3.12+
- Git

### 1. Clone & Set Up Virtual Environment

**Windows (PowerShell):**
```powershell
git clone https://github.com/ervinseq13/VESPH.git
cd VESPH
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux / macOS:**
```bash
git clone https://github.com/ervinseq13/VESPH.git
cd VESPH
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Local Secrets
Create `.streamlit/secrets.toml` in the repository root (this file is git-ignored):

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-supabase-publishable-key"

# Optional: Groq API key for generative medical extraction and open-ended queries
LLM_API_KEY = "gsk_your_groq_api_key_here"
GROQ_MODEL = "openai/gpt-oss-20b"
```

### 3. Run Locally
```bash
streamlit run app.py
```
Open `http://localhost:8501` in your browser.

---

## Automated Test Suite

Run the complete automated test suite (19 unit test scenarios covering patient routing, doctor scheduling, date parsing, medication intake, and PostgreSQL enum compliance):

```bash
python -m unittest discover tests -v
```

Expected output:
```text
Ran 19 tests in 0.40s
OK
```

---

## AWS EC2 Production Deployment Guide

Follow this guide to deploy VESPH Care on an **Amazon EC2** virtual machine (Ubuntu 22.04 LTS or 24.04 LTS recommended) as a persistent background service managed by `systemd` behind an Nginx reverse proxy.

### Step 1: Launch EC2 Instance & Configure Security Group
1. **Instance Type:** `t3.small` or `t3.medium` (2 vCPU, 2-4 GB RAM).
2. **Operating System:** Ubuntu Server 22.04 / 24.04 LTS.
3. **Security Group Inbound Rules:**
   - **Port 22 (SSH):** Your administrative IP.
   - **Port 80 (HTTP):** `0.0.0.0/0` (Web traffic).
   - **Port 443 (HTTPS):** `0.0.0.0/0` (Secure web traffic).
   - **Port 8501 (Streamlit, optional for direct test):** `0.0.0.0/0` or restricted.

---

### Step 2: Server Provisioning & Repository Setup
Connect to your EC2 instance via SSH and run:

```bash
# 1. Update system packages
sudo apt update && sudo apt upgrade -y

# 2. Install Python, pip, virtualenv, and Nginx
sudo apt install -y python3-pip python3-venv git nginx

# 3. Clone repository
cd /home/ubuntu
git clone https://github.com/ervinseq13/VESPH.git
cd VESPH

# 4. Set up Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

### Step 3: Configure Production Secrets
Create the `.streamlit/secrets.toml` configuration on the EC2 instance:

```bash
mkdir -p /home/ubuntu/VESPH/.streamlit
nano /home/ubuntu/VESPH/.streamlit/secrets.toml
```

Paste your configuration:
```toml
SUPABASE_URL = "https://zxnjjdohceumfeuqauwv.supabase.co"
SUPABASE_KEY = "your-supabase-publishable-key"
LLM_API_KEY = "your-groq-api-key"
GROQ_MODEL = "openai/gpt-oss-20b"
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`). Secure permissions:
```bash
chmod 600 /home/ubuntu/VESPH/.streamlit/secrets.toml
```

---

### Step 4: Configure `systemd` Service (24/7 Background Daemon)
Create a systemd unit file so the application starts automatically on boot and auto-restarts on failure:

```bash
sudo nano /etc/systemd/system/vesph.service
```

Paste the following service definition:

```ini
[Unit]
Description=VESPH Care Streamlit Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/VESPH
ExecStart=/home/ubuntu/VESPH/.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
Restart=always
RestartSec=5
Environment=PATH=/home/ubuntu/VESPH/.venv/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable vesph
sudo systemctl start vesph

# Check service status
sudo systemctl status vesph
```

---

### Step 5: Configure Nginx as Reverse Proxy with WebSocket Upgrades
Streamlit relies on WebSocket connections for live reactivity. Configure Nginx to proxy standard HTTP traffic (Port 80) to Streamlit (Port 8501) with WebSocket headers enabled:

```bash
sudo nano /etc/nginx/sites-available/vesph
```

Paste the configuration:

```nginx
server {
    listen 80;
    server_name your-ec2-domain-or-public-ip;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;

        # WebSocket support (Critical for Streamlit UI)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
```

Enable the configuration and reload Nginx:
```bash
sudo ln -sf /etc/nginx/sites-available/vesph /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

### Step 6: Set Up Free SSL with Let's Encrypt (Optional, Recommended)
If you have pointed a custom domain name (e.g. `care.yourhospital.com`) to your EC2 instance IP:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d care.yourhospital.com
```
Certbot will automatically configure HTTPS, redirect HTTP to HTTPS, and establish auto-renewing SSL certificates.

---

### Step 7: Continuous Deployment & Routine Maintenance

To pull updates deployed to GitHub:
```bash
cd /home/ubuntu/VESPH
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart vesph
```

To inspect application logs in real-time:
```bash
sudo journalctl -u vesph -f
```

---

## Security & Clinical Boundaries

- **Client-Side Secrets Policy:** Never place service-role keys or admin passwords in `secrets.toml`. Only standard Supabase publishable/anon keys are used.
- **Safety Boundaries:** The clinical assistant is bound strictly to the hospital's electronic health records and cannot generate diagnoses or treatment changes outside authorized doctor notes.
- **Human-in-the-Loop Approval:** Any clinical note ingestion, schedule blocking, or report discrepancy requires explicit practitioner or patient confirmation before writes are executed.
