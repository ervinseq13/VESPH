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

The following master architecture flow illustrates the symmetric multi-agent collaboration across the Doctor Practice Portal and Patient Care Portal, their specialized agents, interactive verification gates, the live Supabase PostgreSQL data layer, and real-time bidirectional synchronization:

```mermaid
graph TD
    %% CLIENT ENTRY POINTS & ROLE ROUTING
    InboundInteraction([Inbound User Interaction · Doctor or Patient]) --> PortalRouting{Portal Role Routing}

    %% =========================================================================
    %% 🩺 DOCTOR PRACTICE PORTAL FLOWS (Dr. Rhea Mehta)
    %% =========================================================================
    subgraph DoctorPortal["🩺 Doctor Portal Multi-Agent Ecosystem (Dr. Rhea Mehta)"]
        PortalRouting -->|Doctor Persona| DocUI[Doctor Portal Client UI<br/>• OPD Clinic Agenda with Day/Week Tabs<br/>• Doctor Clinical Assistant Chat<br/>• Consultation PDF/Text Uploader<br/>• Patient Clinical Chart Modal]
        
        DocUI --> DocOrch[Doctor Orchestrator · doctor_orchestrator.py]
        DocOrch --> DocClassifier{Intent Classifier & Entity Parser<br/>Regex & Groq NLP}

        %% Flow 1: Schedule & Appointment Count Flow
        DocClassifier -->|CHECK_SCHEDULE<br/>e.g., 'what is my schedule on 22nd'| DocSchedAgent[Doctor Schedule & Count Agent]
        DocSchedAgent --> DateParser[Safe Word-Boundary Date Parser<br/>regex: \b(2[0-9]|3[01]|1[0-9]|[1-9])(st|nd|rd|th)?\b<br/>Defaults to viewed week's month]
        DateParser --> SchedQuery[(Query appointments Table<br/>Filter by doctor_id & parsed date)]
        SchedQuery --> SchedFormat[Format Structured OPD Table<br/>Exact appointment count, patient names, short IDs,<br/>timeslot intervals, and status badges]

        %% Flow 2: Doctor Unavailability & Conflict Rebooking Flow
        DocClassifier -->|BLOCK_UNAVAILABILITY<br/>e.g., 'I am not available on 22nd'| DocAvailAgent[Doctor Availability & Rebooking Agent]
        DocAvailAgent --> ConflictDetector[(Detect Conflicting Appointments<br/>in appointments Table for target date)]
        ConflictDetector --> AvailProposal[Generate Verification Proposal<br/>Lists affected patients & computed fallback slots<br/>e.g., 26, 27, 28 Oct · Avoids blocked date!]
        AvailProposal --> DocAvailGate{Doctor Confirms?<br/>'yes' / 'confirm'}
        DocAvailGate -->|Rejects / Cancels| AvailCancel[Cancel Proposal & Retain Status]
        DocAvailGate -->|Doctor Confirms| ExecAvailCommit[(Execute Transaction in Supabase:<br/>1. INSERT doctor_unavailability<br/>2. UPDATE appointments SET appointment_datetime=fallback,<br/>   status='Pending'<br/>3. INSERT escalation_agent_data priority notice)]
        ExecAvailCommit --> AvailReceipt[Format Unavailability Receipt<br/>'Verified in Supabase · Patients notified of reschedule']

        %% Flow 3: Patient Record & Clinical Facet Lookup Flow
        DocClassifier -->|PATIENT_QUERY<br/>e.g., 'Tell me about Neha Kapoor' / 'what meds is Ananya taking'| DocPatientAgent[Patient Verification & Facet Agent]
        DocPatientAgent --> FuzzyRoster{Fuzzy Match in patients Table?<br/>Full Name / First / Last Name}
        FuzzyRoster -->|Not Found| RosterSample[Clarify with 5-Patient Roster Sample<br/>Show Names & Short IDs PID-XXXX]
        FuzzyRoster -->|Verified Patient: PID-8421| FacetBranch{Detect Inquired Clinical Facet}
        FacetBranch -->|Medications / Rx| FacetMedQuery[(Query prescription_details + medicines<br/>Deduplicate dosage & brand e.g. 'Dolo 650 mg')]
        FacetBranch -->|Appointments / Schedule| FacetApptQuery[(Query appointments Table<br/>Upcoming & past visits with short IDs APT-XXXX)]
        FacetBranch -->|Clinical Summary / General| FacetSumQuery[(Fetch longitudinal patient_summary<br/>Surgical history, vitals & demographics)]
        FacetMedQuery --> FormatChart[Format Rich Clinical Profile Card<br/>with Demographics, short IDs, active meds, and visits]
        FacetApptQuery --> FormatChart
        FacetSumQuery --> FormatChart

        %% Flow 4: RAG Consultation Document Ingestion Pipeline Flow
        DocClassifier -->|CLINICAL_NOTE<br/>Upload PDF or Paste Raw Consultation Note| DocIngestAgent[Clinical Document Ingestion Agent]
        DocIngestAgent --> InputTypeCheck{Input is PDF?}
        InputTypeCheck -->|Yes| PDFExtract[extract_text_from_pdf via pypdf<br/>Iterate page text streams]
        InputTypeCheck -->|No: Text| RawNoteText[Direct Text Stream]
        PDFExtract --> GroqNLP[Groq Clinical NLP Extraction<br/>Model: openai/gpt-oss-20b · Strict JSON Schema<br/>Extract: Diagnosis, Vitals, Mealtime Meds, Follow-up]
        RawNoteText --> GroqNLP
        GroqNLP --> IngestPreviewGate[Clinical Verification Preview Gate<br/>Display extracted entities with checkmarks<br/>Prompt: 'Confirm to update Supabase records?']
        IngestPreviewGate --> DocIngestConfirm{Doctor Confirms?<br/>'yes' / 'confirm'}
        DocIngestConfirm -->|Rejects| IngestAbort[Clear pending state & discard staging]
        DocIngestConfirm -->|Doctor Confirms| MultiTableCommit[(Transactional Commit across 5 Supabase Tables:<br/>1. UPDATE patients.patient_summary<br/>2. INSERT consultations CON-1001<br/>3. INSERT appointments APT-1001, status='Confirmed'<br/>4. INSERT prescription_details MED-6661<br/>5. INSERT diagnostics & diagnostics_results LAB-1001)]
        MultiTableCommit --> IngestReceipt[Format Ingestion Receipt<br/>Displays verified short IDs & prompts inspection in Patient View]

        %% Flow 5: Doctor Chit-Chat Deflection Flow
        DocClassifier -->|CHIT_CHAT / Off-Topic<br/>e.g., 'hello', 'what is the weather'| DocChitChat[Doctor Chit-Chat Deflection Agent]
        DocChitChat --> DocScopeHelp[Clarify Practice Management Capabilities<br/>Schedule checks, leave blocking, patient records, note ingestion]
    end

    %% =========================================================================
    %% 👤 PATIENT CARE PORTAL FLOWS (Ananya Iyer)
    %% =========================================================================
    subgraph PatientPortal["👤 Patient Portal Multi-Agent Ecosystem (Ananya Iyer)"]
        PortalRouting -->|Patient Persona| PatUI[Patient Portal Client UI<br/>• Recovery Timeline & Surgical Milestones<br/>• Mealtime Medication Cards Breakfast/Lunch/Dinner<br/>• Diagnostic Download Center & Histopathology<br/>• Patient Care Assistant Chat<br/>• 15m Cadence Reschedule Modal]
        
        PatUI --> PatOrch[Patient Orchestrator<br/>orchestrator/patient_orchestrator.py · LangGraph StateGraph]
        PatOrch --> PatClassifier{Intent & Safety Classifier<br/>Red-Flag Keyword & NLP Router}

        %% Flow 6: Deterministic Safety & Emergency Escalation Flow
        PatClassifier -->|Emergency / Wrong Report / Acute Symptoms<br/>e.g., 'severe chest pain', 'wrong blood report'| PatEscalationAgent[Safety & Escalation Agent]
        PatEscalationAgent --> EmergencyGuide[Immediate Deterministic Safety Advice<br/>'Call +91 22 4000 1122 or nearest emergency room']
        EmergencyGuide --> CreateEscalationTicket[(Insert escalation_agent_data<br/>status='Open', priority='Critical', escalated_at=NOW)]
        CreateEscalationTicket --> PromptResolutionActions[Display Interactive Action Buttons<br/>'Request report reissue' / 'Contact Clinical Coordinator']
        PromptResolutionActions --> PatResolutionChoice{Patient Clicks Action}
        PatResolutionChoice --> UpdateEscalationTicket[(UPDATE escalation_agent_data<br/>status='Resolved', resolved_at=NOW)]

        %% Flow 7: Natural Language Medication Intake Flow
        PatClassifier -->|Natural Intake Confirmation<br/>e.g., 'I took dolo' / 'took my pantocid'| PatIntakeParser[Natural Intake Handler]
        PatIntakeParser --> MatchActiveRx{Match Active Prescription in DB?<br/>Resolve Brand Name / Medicine ID}
        MatchActiveRx -->|Matched: Dolo 650 mg| ToggleMedDB[(Call toggle_prescription_taken_in_supabase<br/>UPDATE prescription_details SET is_taken=TRUE<br/>WHERE prescription_item_id = :id)]
        ToggleMedDB --> ReEvalNotif{Are all meal medications taken?}
        ReEvalNotif -->|All Taken| DismissMealCard[Dismiss Medication Check Alert Card<br/>from Notification Centre]
        ReEvalNotif -->|Pending Doses Remain| KeepRemainingCard[Retain Alert Card for Remaining Doses]
        DismissMealCard --> ConfirmIntakeReply[Post Warm Conversational Confirmation<br/>'Great job! Marked Dolo 650 mg taken in hospital records']
        KeepRemainingCard --> ConfirmIntakeReply

        %% Flow 8: Proactive Reminders & Reschedule Convergence Flow
        PatClassifier -->|Upcoming Visits / Dosing / Fasting<br/>e.g., 'when is my appointment', 'fasting rules'| PatReminderAgent[Reminder & Scheduling Agent]
        PatReminderAgent --> CheckApptStatus{Check Appointment Status in DB}
        CheckApptStatus -->|status == 'Pending' or 'Rescheduled'<br/>e.g. Doctor moved visit| RescheduleAlert[Render Action Required Banner<br/>'⚠️ Doctor schedule adjusted to 26 Oct. Confirm or rebook']
        RescheduleAlert --> PatReschedAction{Patient Chooses Action}
        PatReschedAction -->|Clicks 'Confirm'| ConfirmSlot[(UPDATE appointments SET status='Confirmed')]
        PatReschedAction -->|Clicks 'Reschedule'| OpenSlotPicker[Display 15m Cadence Slots<br/>Select alternative date & time with 5m buffers]
        OpenSlotPicker --> SaveNewSlot[(UPDATE appointments SET appointment_datetime=new_dt,<br/>status='Pending')]
        CheckApptStatus -->|status == 'Confirmed'| NormalReminder[Standard 1-Day Advance Reminder<br/>Preparation instructions & room location]
        NormalReminder --> FastingCheck{Diagnostic Test Requires Fasting?}
        FastingCheck -->|Yes: Lipid / Sugar| FastingAdvice[Deliver Fasting Protocol: 10-12 hr overnight fast]
        FastingCheck -->|No| RoutinePrep[Routine Clinic Arrival Instructions]

        %% Flow 9: Longitudinal Summary & Adherence Trends Flow
        PatClassifier -->|Summary / Biomarkers / Adherence<br/>e.g., 'how is my recovery', 'adherence'| PatSummaryAgent[Summary & Trends Agent]
        PatSummaryAgent --> QueryBiomarkers[(Query consultations + diagnostics_results)]
        QueryBiomarkers --> CalcAdherence[Calculate Prescribed vs Taken Ratio<br/>e.g., '1 of 3 taken · 33% adherence']
        CalcAdherence --> FormatRecoveryTrend[Format Clinical Recovery Summary<br/>WBC trend, surgical clearance, diet stage]

        %% Flow 10: Doctor Profile Lookup Flow
        PatClassifier -->|Doctor Inquiry<br/>e.g., 'Tell me about Dr. Rhea Mehta'| PatDocSummaryAgent[Doctor Profile Agent]
        PatDocSummaryAgent --> QueryDoctorProfile[(Query doctors Table<br/>Name, qualifications, department, room)]
        QueryDoctorProfile --> FormatDocProfile[Format Attending Physician Credentials Card]

        %% Flow 11: Scoped LLM Chit-Chat Fallback Flow
        PatClassifier -->|General Question / Off-Topic| GroqPatientFallback[Groq LLM Scoped Fallback]
        GroqPatientFallback --> ScopedPrompt[PATIENT_SYSTEM_PROMPT<br/>Hospital-Scoped Recovery · Refuse General Life Advice]
    end

    %% =========================================================================
    %% 🗄️ LIVE SUPABASE POSTGRESQL PERSISTENCE LAYER (10 Tables)
    %% =========================================================================
    subgraph DataPersistence["🗄️ Live Supabase Cloud PostgreSQL Data Layer (10 Relational Tables)"]
        T_Patients[(patients<br/>Demographics, Longitudinal Summary, Short ID PID-XXXX)]
        T_Doctors[(doctors<br/>Attending Physician Profiles, Room, Short ID DOC-XXXX)]
        T_Appointments[(appointments<br/>Strict appointment_status_enum: Confirmed, Pending, Rescheduled, Cancelled, Completed)]
        T_Unavailability[(doctor_unavailability<br/>Blocked Dates, Leave Records)]
        T_Consultations[(consultations<br/>Encounter Vitals, Diagnoses, Short ID CON-XXXX)]
        T_Medicines[(medicines<br/>Pharmaceutical Catalog)]
        T_Prescriptions[(prescription_details<br/>Meal Timings: breakfast/lunch/dinner, is_taken status)]
        T_Diagnostics[(diagnostics<br/>Laboratory Orders, Short ID LAB-XXXX)]
        T_DiagResults[(diagnostics_results<br/>Biomarker Readings, WBC, Reference Ranges)]
        T_Escalations[(escalation_agent_data<br/>Emergency Tickets, Priority Alerts, Resolution Records)]
    end

    %% DATABASE BINDINGS: DOCTOR
    SchedQuery -.-> T_Appointments
    ConflictDetector -.-> T_Appointments
    ExecAvailCommit -.-> T_Unavailability
    ExecAvailCommit -.-> T_Appointments
    ExecAvailCommit -.-> T_Escalations
    FuzzyRoster -.-> T_Patients
    FacetMedQuery -.-> T_Prescriptions
    FacetMedQuery -.-> T_Medicines
    FacetApptQuery -.-> T_Appointments
    FacetSumQuery -.-> T_Patients
    MultiTableCommit -.-> T_Patients
    MultiTableCommit -.-> T_Consultations
    MultiTableCommit -.-> T_Appointments
    MultiTableCommit -.-> T_Prescriptions
    MultiTableCommit -.-> T_Diagnostics
    MultiTableCommit -.-> T_DiagResults

    %% DATABASE BINDINGS: PATIENT
    CreateEscalationTicket -.-> T_Escalations
    UpdateEscalationTicket -.-> T_Escalations
    ToggleMedDB -.-> T_Prescriptions
    CheckApptStatus -.-> T_Appointments
    ConfirmSlot -.-> T_Appointments
    SaveNewSlot -.-> T_Appointments
    QueryBiomarkers -.-> T_Consultations
    QueryBiomarkers -.-> T_DiagResults
    QueryDoctorProfile -.-> T_Doctors

    %% UI OUTPUT BINDINGS
    SchedFormat --> DocUI
    AvailReceipt --> DocUI
    AvailCancel --> DocUI
    FormatChart --> DocUI
    RosterSample --> DocUI
    IngestReceipt --> DocUI
    IngestAbort --> DocUI
    DocScopeHelp --> DocUI

    EmergencyGuide --> PatUI
    UpdateEscalationTicket --> PatUI
    ConfirmIntakeReply --> PatUI
    ConfirmSlot --> PatUI
    SaveNewSlot --> PatUI
    FastingAdvice --> PatUI
    RoutinePrep --> PatUI
    FormatRecoveryTrend --> PatUI
    FormatDocProfile --> PatUI
    ScopedPrompt --> PatUI

    %% =========================================================================
    %% 🔄 BIDIRECTIONAL CROSS-PORTAL REACTIVE SYNCHRONIZATION
    %% =========================================================================
    ExecAvailCommit ==>|1. Doctor Blocks Date & Shifts Slot| RescheduleAlert
    MultiTableCommit ==>|2. Doctor Ingests Note: Updates Meds/Appts/Labs| PatUI
    ToggleMedDB ==>|3. Patient Takes Med: Live Checkoff Sync| FacetMedQuery
    SaveNewSlot ==>|4. Patient Reschedules Slot| DocUI
```

> **Detailed Sub-Flow Documentation:** For step-by-step sequence diagrams, state machines, and pipeline flowcharts for each individual flow, see [VESPH_Documentation.md](VESPH_Documentation.md).

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
