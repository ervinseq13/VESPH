# VESPH Care — Virtual Engagement System for Patient Health
## Comprehensive Technical System Documentation & Architectural Specification

---

## Executive Summary

**VESPH Care** (Virtual Engagement System for Patient Health) is an intelligent, multi-agent post-discharge clinical coordination platform. It bridges the critical communication and compliance gap between inpatient hospital discharge and outpatient recovery by delivering:

1. **An Empathetic Patient Portal:** Features structured recovery timelines, diagnostic reports, discharge instructions, mealtime-grouped medication tracking (Breakfast, Lunch, Dinner with live checkoff), appointment management with auto-accepted slot rescheduling, and an interactive Care Assistant.
2. **A High-Efficiency Doctor Portal:** Tailored for attending physicians (modeled around Lead Laparoscopic Surgeon **Dr. Rhea Mehta**), featuring a weekly clinic agenda across active patients, schedule blocking with automated conflict rebooking, patient clinical chart reviews, and a **RAG Consultation Document Ingestion Agent** that reads doctor consultation notes/PDFs and synchronizes updates directly into the live clinical database.
3. **A Hybrid Agent Architecture:** Powered by LangGraph, Groq LLM (`openai/gpt-oss-20b`), and live Supabase PostgreSQL storage, combining deterministic clinical safety guards with scoped generative intelligence.
4. **Production-Ready AWS EC2 Infrastructure:** Packaged for persistent 24/7 background operation via `systemd` and Nginx reverse proxying with WebSocket upgrade support.

---

## 1. System Architecture & Dual-Portal Topology

VESPH Care unifies patient recovery and physician practice workflows around a single live database source of truth:

```mermaid
flowchart TB
    subgraph ClientTier["Client Tier · Streamlit Reactive UI (app.py)"]
        Nav["Persistent Role Switcher<br/>(👤 Patient View · 🩺 Doctor View)"]
        PV["👤 Patient Portal<br/>• Longitudinal Timeline<br/>• Mealtime Meds (Breakfast/Lunch/Dinner)<br/>• Appointments & Diagnostics<br/>• Interactive Care Assistant"]
        DV["🩺 Doctor Portal<br/>• Multi-Week Agenda (Dr. Rhea Mehta)<br/>• Unavailability / Leave Blocking<br/>• Patient Clinical Charts Modal<br/>• RAG Consultation Note Ingestion"]
        Nav --> PV
        Nav --> DV
    end

    subgraph ServiceTier["Orchestration & Agent Service Tier"]
        PO["Patient Orchestrator (LangGraph StateGraph)<br/>• Safety Escalation Agent<br/>• Reminder & Scheduling Agent<br/>• Patient Health Summary Agent<br/>• Natural Intake Parser ('I took dolo')"]
        DO["Doctor Orchestrator (doctor_orchestrator.py)<br/>• Schedule & Agenda Agent<br/>• Leave & Escalation Agent<br/>• Patient Clinical Records Agent<br/>• Chit-Chat & Capability Agent"]
        RAG["RAG Ingestion Engine (consultation_ingestion.py)<br/>• pypdf Text Extractor<br/>• Groq Clinical NLP Entity Parser<br/>• Transactional DB Committer"]
        Hub["Integration Hub (integrations.py)<br/>• Scoped System Prompts<br/>• Connection Readiness Probes"]
        
        PV <--> PO
        PO <--> Hub
        DV <--> DO
        DV <--> RAG
        DO <--> Hub
        RAG <--> Hub
    end

    subgraph DataTier["Data & Intelligence Storage Tier"]
        Groq["Groq Cloud Inference (LPU)<br/>Model: openai/gpt-oss-20b<br/>• Patient Persona: Empathetic, Plain-Language<br/>• Doctor Persona: Clinical-Grade, Concise"]
        Supa["Supabase Cloud PostgreSQL (10 Tables)<br/>• patients · doctors · appointments<br/>• consultations · medicines · prescription_details<br/>• diagnostics · diagnostics_results<br/>• doctor_unavailability · escalation_agent_data"]
        
        Hub <--> Groq
        Hub <--> Supa
        RAG <--> Groq
        RAG <--> Supa
    end
```

---

## 2. Multi-Agent Conversational Routing Architecture

VESPH Care deploys separate, specialized multi-agent graphs for the Patient and Doctor portals, guaranteeing deterministic safety and preventing cross-domain hallucinations.

```mermaid
stateDiagram-v2
    [*] --> InboundMessage

    state "Role Detection" as RoleGate {
        InboundMessage --> PatientRouter : Persona == Patient
        InboundMessage --> DoctorRouter : Persona == Doctor
    }

    state "Patient Multi-Agent Graph (LangGraph)" as P_Graph {
        PatientRouter --> EscalationAgent : Emergency (Chest Pain, Breathlessness)<br/>or Wrong Report Flag
        PatientRouter --> ReminderAgent : Appointment Time, Next Med Dose,<br/>or Diagnostic Date Inquiry
        PatientRouter --> SummaryAgent : Medical Diagnosis, Biomarkers,<br/>or Lab Value Interpretation
        PatientRouter --> MedicationIntake : 'I took dolo' / 'taken meds'
        PatientRouter --> GroqPatientFallback : General Hospital Record Query

        EscalationAgent --> HumanActionTicket : Dispatch Priority Ticket
        HumanActionTicket --> PatientResponse
        ReminderAgent --> PatientResponse
        SummaryAgent --> PatientResponse
        MedicationIntake --> PatientResponse : Sync DB & Dismiss Notification
        GroqPatientFallback --> PatientResponse
    }

    state "Doctor Clinical Assistant Graph" as D_Graph {
        DoctorRouter --> ConfirmAction : Pending Action in Session ('yes' / 'confirm')
        DoctorRouter --> ClinicalNoteIngest : Raw Consultation Text / Ingestion Request
        DoctorRouter --> UnavailabilityBlock : Leave / Off Day / Block Schedule
        DoctorRouter --> PatientQuery : 'Tell me about Ananya' / 'what meds is Neha taking'
        DoctorRouter --> ScheduleCheck : 'what is my schedule on 22nd' / Appointment Count
        DoctorRouter --> DoctorChitChat : Greeting / Off-Topic / Capabilities

        ConfirmAction --> DoctorResponse : Execute Block or Commit Ingestion
        ClinicalNoteIngest --> DoctorResponse : Generate Extraction Preview
        UnavailabilityBlock --> DoctorResponse : Propose Rebooking Plan
        PatientQuery --> DoctorResponse : Fetch Roster & Clinical Chart
        ScheduleCheck --> DoctorResponse : Format Markdown OPD Table
        DoctorChitChat --> DoctorResponse : Explain Clinical Capabilities
    }

    PatientResponse --> [*]
    DoctorResponse --> [*]
```

---

## 3. Doctor Unavailability & Automated Conflict Rebooking Flowchart

When an attending physician blocks leave or an emergency surgery occurs, VESPH Care automatically evaluates conflicting appointments, calculates open fallback slots, updates database statuses, and dispatches patient escalations.

```mermaid
sequenceDiagram
    autonumber
    actor Doc as Dr. Rhea Mehta
    participant UI as Doctor Portal UI
    participant Orch as Doctor Orchestrator
    participant DB as Supabase PostgreSQL
    participant PatUI as Patient Portal (Ananya Iyer)

    Doc->>UI: Types: "I'm not available on 22nd oct, block this day and reschedule patients"
    UI->>Orch: Classify Intent -> BLOCK_UNAVAILABILITY (target_date = 2026-10-22)
    Orch->>DB: Query appointments for doctor_id on 2026-10-22
    DB-->>Orch: Returns 2 conflicting visits (Ananya Iyer @ 11:00 AM, Sandeep Mehra @ 2:30 PM)
    Orch-->>UI: Displays Verification Proposal with conflicting appointments & asks confirmation
    Doc->>UI: Types: "yes" / "confirm"
    UI->>Orch: Intent -> CONFIRM_ACTION (pending_action = block_unavailability)
    
    rect rgb(240, 248, 255)
        Note over Orch,DB: Execution of Block & Rebooking
        Orch->>DB: Insert into doctor_unavailability (2026-10-22, full_day)
        Orch->>Orch: Compute next available fallback slots (e.g. 26 Oct 10:00 AM)
        loop For each conflicting appointment
            Orch->>DB: Update appointments SET appointment_datetime = new_slot, status = 'Pending'
        end
        Orch->>DB: Insert priority rebooking notice in escalation_agent_data
    end

    DB-->>Orch: Write confirmed
    Orch-->>UI: Displays Confirmation Receipt (Verified in Supabase, 2 appointments moved to Pending)
    
    rect rgb(255, 250, 240)
        Note over PatUI: Patient Portal Reactivity
        Doc->>PatUI: Switch to 👤 Patient View
        PatUI->>DB: Fetch patient appointments
        DB-->>PatUI: Appointment reflects Date: 26 Oct 2026, Status: Pending
        PatUI-->>Doc: Notification Banner: "Action Required – Appointment Rescheduled to 26 Oct. Please confirm or rebook."
    end
```

---

## 4. Appointment State Transition Machine & PostgreSQL Enum Hardening

In the live Supabase PostgreSQL database, the `appointments.status` column is strictly constrained to the custom enum `appointment_status_enum`. Any unmapped text representation throws error `22P02`. VESPH Care implements canonical normalization to enforce deterministic state transitions:

```mermaid
stateDiagram-v2
    [*] --> Pending : 1. New Booking Created<br/>OR Date/Time Rescheduled in place

    Pending --> Confirmed : Patient Confirms Proposed Slot<br/>(via Chat or Appt Card)
    Confirmed --> Completed : Visit Conducted by Physician
    Confirmed --> Cancelled : Patient or Doctor Cancels Visit

    state "Reschedule with New Record" as SplitReschedule {
        Confirmed --> Old_Rescheduled : Reschedule Requested
        Old_Rescheduled --> [*] : Old Record Archived
        Confirmed --> New_Pending : New Slot Created
    }

    New_Pending --> Confirmed : Patient Confirms New Slot

    Completed --> [*]
    Cancelled --> [*]

    note right of Pending
        Database Value: 'Pending'
        Triggered when:
        • New booking created
        • Doctor unavail blocks day & shifts date
        • Patient requests alternate slot
    end note

    note right of Old_Rescheduled
        Database Value: 'Rescheduled'
        Triggered when:
        • Existing appointment is superseded
          by a newly generated booking row
    end note
```

### PostgreSQL Status Normalization Mapping (`tools/db_tools.py`)

```python
VALID_APPOINTMENT_STATUSES = {
    "Confirmed",
    "Pending",
    "Completed",
    "Cancelled",
    "Rescheduled",
}

STATUS_NORMALIZATION_MAP = {
    "reschedule pending": "Pending",  # Date is changing, awaiting confirmation
    "rescheduled": "Rescheduled",
    "reschedule": "Pending",
    "pending confirmation": "Pending",
    "pending": "Pending",
    "confirmed": "Confirmed",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
    "completed": "Completed",
    "doctor unavailable (reschedule required)": "Cancelled",
    "doctor unavailable": "Cancelled",
    "unavailable": "Cancelled",
}
```

---

## 5. Patient Medication Adherence & Notification Dismissal Flow

VESPH Care connects patient conversational chat with electronic medication administration records (eMAR). When patients mention taking medicine in colloquial language, the system identifies the dose, mutates the database, and dismisses pending alerts.

```mermaid
flowchart TD
    Start["Patient enters chat message<br/>(e.g., 'I took dolo' / 'took my morning pantocid')"]
    
    Detect{"Regex & Keyword Intake Matcher<br/>contains 'took', 'taken', or 'had my'<br/>AND matches active prescription name"}
    
    Start --> Detect
    
    Detect -- No --> StandardRoute["Route to Normal LangGraph Orchestrator<br/>(Summary, Reminder, or Escalation)"]
    
    Detect -- Yes --> FindMed["Identify target prescription_item_id<br/>in patient's active medication list"]
    
    FindMed --> DBUpdate["Call toggle_prescription_taken_in_supabase()<br/>UPDATE prescription_details SET is_taken = TRUE<br/>WHERE prescription_item_id = :id"]
    
    DBUpdate --> StateUpdate["Update local session state DATA['medications']<br/>is_taken = True & record_activity_update()"]
    
    StateUpdate --> ReEval{"Notification Centre Evaluation<br/>has_pending_meal_meds?<br/>Check if any untaken meds remain for meal"}
    
    ReEval -- All taken for meal --> DismissCard["Dismiss Medication Check Alert Card<br/>from Notification Centre"]
    ReEval -- Other meds pending --> KeepCard["Keep alert card active<br/>for remaining untaken medications"]
    
    DismissCard --> Reply["Post conversational confirmation:<br/>'Great job! I've marked your Dolo 650 mg as taken in your hospital record.<br/>Your medication card and notification centre have been updated.'"]
    KeepCard --> Reply
```

---

## 6. RAG Consultation Document Ingestion Pipeline

The Doctor Portal provides an autonomous document ingestion pipeline that extracts unstructured consultation notes into normalized multi-table database records:

```mermaid
flowchart TB
    Doc["Physician Input<br/>• Uploads PDF Consultation Note<br/>OR<br/>• Pastes raw clinical note text into chat"]
    
    PDFParse["pypdf Text Extraction<br/>extract_text_from_pdf() reads raw byte stream"]
    
    Doc --> PDFParse
    
    GroqNLP["Groq Clinical NLP Extraction<br/>Model: openai/gpt-oss-20b<br/>System Prompt: Strict Clinical Entity Schema<br/>Extracts: diagnosis, symptoms, vitals (BP/sugar/wt),<br/>medications by mealtime, follow-up date, diagnostic lab orders"]
    
    PDFParse --> GroqNLP
    
    Preview["Clinical Verification Preview Gate<br/>Displays structured extraction card in chat with extracted vitals,<br/>prescriptions, and follow-ups. Awaits doctor confirmation."]
    
    GroqNLP --> Preview
    
    Gate{"Doctor Confirmation<br/>'yes' / 'confirm'"}
    
    Preview --> Gate
    
    Gate -- Doctor Rejects --> Cancel["Cancel ingestion & clear pending action"]
    
    Gate -- Doctor Confirms --> Transact["Execute ingest_consultation_to_supabase()"]
    
    subgraph MultiTableWrites["Transactional Supabase Writes (5 Tables)"]
        T1["1. UPDATE patients<br/>SET patient_summary = :new_summary"]
        T2["2. INSERT INTO consultations<br/>(consultation_id, diagnosis, bp, sugar, weight, summary)"]
        T3["3. INSERT INTO appointments<br/>(appointment_id, date, time, type = 'FollowUp', status = 'Confirmed')"]
        T4["4. INSERT INTO prescription_details<br/>(prescription_item_id, medicine_id, meal_timing, dosage, instructions)"]
        T5["5. INSERT INTO diagnostics & diagnostics_results<br/>(order_id, test_name, category, order_status)"]
    end
    
    Transact --> T1
    Transact --> T2
    Transact --> T3
    Transact --> T4
    Transact --> T5
    
    MultiTableWrites --> Receipt["Generate Synchronized Receipt Report<br/>Displays formatted short IDs: PID-8421, CON-1001, MED-6661, APT-1001<br/>Directs doctor to switch to 👤 Patient View to inspect live updates"]
```

---

## 7. Standardized Short Identifier (ID) System Specification

To prevent raw 36-character UUID strings from cluttering the clinical user interface and conversational chat, VESPH Care implements a centralized short ID system:

| Entity Type | Raw Database Type | Short ID Format | Example | Source Generator |
|---|---|---|---|---|
| **Patient** | UUID v4 | `PID-XXXX` | `PID-8421` | `short_patient_id(pid)` |
| **Doctor** | UUID v4 | `DOC-XXXX` | `DOC-RHEA-01` | `short_doctor_id(did)` |
| **Medicine** | UUID v4 | `MED-XXXX` | `MED-6661` | `short_medicine_id(mid)` |
| **Appointment** | UUID v4 | `APT-XXXX` | `APT-1001` | `short_appointment_id(aid)` |
| **Consultation** | UUID v4 | `CON-XXXX` | `CON-1001` | `short_consultation_id(cid)` |
| **Diagnostic Lab** | UUID v4 | `LAB-XXXX` | `LAB-1001` | `short_diagnostic_id(did)` |

### Formatting Logic (`tools/db_tools.py`)
- Strips hyphens and extracts trailing uppercase alphanumeric characters.
- Overrides canonical demo fixtures (e.g. `22222222-...` maps to `PID-8421`, `11111111-...` maps to `DOC-RHEA-01`).
- Applied universally across timeline cards, detail popups, download filenames (e.g. `medication-MED-6661.txt`), clinical chart modals, and doctor chat responses.

---

## 8. Relational Database Schema & Data Dictionary

VESPH Care operates on 10 interconnected tables hosted on a live Supabase PostgreSQL instance:

```mermaid
erDiagram
    PATIENTS ||--o{ APPOINTMENTS : "schedules"
    PATIENTS ||--o{ CONSULTATIONS : "undergoes"
    PATIENTS ||--o{ PRESCRIPTION_DETAILS : "prescribed"
    PATIENTS ||--o{ DIAGNOSTICS : "ordered_for"
    PATIENTS ||--o{ ESCALATION_AGENT_DATA : "triggers"
    DOCTORS ||--o{ APPOINTMENTS : "attends"
    DOCTORS ||--o{ CONSULTATIONS : "conducts"
    DOCTORS ||--o{ DOCTOR_UNAVAILABILITY : "logs_leave"
    CONSULTATIONS ||--o{ PRESCRIPTION_DETAILS : "contains"
    MEDICINES ||--o{ PRESCRIPTION_DETAILS : "cataloged_in"
    DIAGNOSTICS ||--o{ DIAGNOSTICS_RESULTS : "produces"

    PATIENTS {
        uuid patient_id PK
        string first_name
        string last_name
        date date_of_birth
        string gender
        string blood_type
        string contact_phone
        uuid primary_doctor_id FK
        text patient_summary
    }

    DOCTORS {
        uuid doctor_id PK
        string doctor_name
        string qualifications
        string department
        string room_no
        boolean is_active
    }

    APPOINTMENTS {
        uuid appointment_id PK
        uuid patient_id FK
        uuid doctor_id FK
        string appointment_type
        timestamp appointment_datetime
        appointment_status_enum status
        string location
        text appointment_summary
    }

    CONSULTATIONS {
        uuid consultation_id PK
        uuid patient_id FK
        uuid doctor_id FK
        text symptoms
        text diagnosis
        string bp_systolic
        string bp_diastolic
        string sugar_reading
        string weight_kg
    }

    MEDICINES {
        uuid medicine_id PK
        string brand_name
        string generic_name
        string dosage_form
    }

    PRESCRIPTION_DETAILS {
        uuid prescription_item_id PK
        uuid consultation_id FK
        uuid patient_id FK
        uuid medicine_id FK
        string dosage
        meal_timing_enum meal_timing
        boolean is_taken
        text instructions
    }
```

---

## 9. AWS EC2 Production Deployment & Cloud Architecture

```mermaid
flowchart TD
    subgraph Internet["Public Internet"]
        User["End Users<br/>(Patients & Doctors)"]
    end

    subgraph AWS["Amazon Web Services (AWS)"]
        subgraph Edge["DNS & Security"]
            R53["Amazon Route 53<br/>care.yourhospital.com"]
            SG["Security Group<br/>Inbound: 22 (SSH), 80 (HTTP), 443 (HTTPS)"]
        end

        subgraph EC2["Amazon EC2 Instance (Ubuntu 22.04 LTS / t3.small)"]
            Nginx["Nginx Reverse Proxy (Port 80/443)<br/>• SSL Termination via Certbot<br/>• WebSocket Upgrade Headers (Upgrade & Connection)"]
            
            subgraph Daemon["Service Supervisor"]
                Sysd["systemd (vesph.service)<br/>Auto-restart on failure, restartSec=5"]
            end

            subgraph StreamlitApp["Python Virtual Environment (.venv)"]
                App["Streamlit Server (Port 8501)<br/>Headless Mode, 127.0.0.1 Binding"]
                Sec["secrets.toml (Permissions: 600)<br/>SUPABASE_URL, SUPABASE_KEY, LLM_API_KEY"]
            end
        end

        subgraph CloudStorage["External Managed Services"]
            SupaPostgres["Supabase Cloud PostgreSQL<br/>10 Live Relational Tables"]
            GroqLPU["Groq Cloud Inference Engine<br/>openai/gpt-oss-20b"]
        end
    end

    User --> R53
    R53 --> SG
    SG --> Nginx
    Nginx -- "Proxy pass to 127.0.0.1:8501<br/>(with WebSocket upgrade)" --> App
    Sysd --> App
    App --> Sec
    App <--> SupaPostgres
    App <--> GroqLPU
```

### Production `systemd` Configuration (`/etc/systemd/system/vesph.service`)
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

### Production Nginx Reverse Proxy Configuration (`/etc/nginx/sites-available/vesph`)
```nginx
server {
    listen 80;
    server_name care.yourhospital.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;

        # WebSocket support (Critical for Streamlit reactive components)
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

---

## 10. Automated Test Suite Matrix

The platform is validated by 19 automated unit tests covering safety-critical routing, rescheduling state transitions, and database enum compatibility:

| Test Identifier | Target Test Class | Tested User Scenario | Verified Assertion | Status |
|---|---|---|---|---|
| **TEST-01** | `TestPatientOrchestrator` | "Tell me about Dr. Rhea Mehta" | Doctor credentials, qualifications, room number | **PASS** |
| **TEST-02** | `TestPatientOrchestrator` | "What is my recovery trend?" | Historical biomarker trend & surgical clearance | **PASS** |
| **TEST-03** | `TestPatientOrchestrator` | "What is my medication adherence?" | Prescribed vs. taken ratio (33% adherence) | **PASS** |
| **TEST-04** | `TestPatientOrchestrator` | "When is my upcoming appointment?" | Next visit date, location, and prep instructions | **PASS** |
| **TEST-05** | `TestPatientOrchestrator` | "I took dolo" | Natural intake acknowledgment & `is_taken = True` | **PASS** |
| **TEST-06** | `TestPatientOrchestrator` | `normalize_appointment_status` | Maps "Reschedule Pending" strictly to "Pending" | **PASS** |
| **TEST-07** | `TestPatientOrchestrator` | `normalize_appointment_status` | Maps "Doctor Unavailable" strictly to "Cancelled" | **PASS** |
| **TEST-08** | `TestPatientOrchestrator` | `normalize_appointment_status` | Validates all outputs belong to `VALID_APPOINTMENT_STATUSES` | **PASS** |
| **TEST-09** | `TestDoctorOrchestrator` | "What's my schedule on 21st oct?" | Matches appointment count and returns OPD table | **PASS** |
| **TEST-10** | `TestDoctorOrchestrator` | "What's my schedule on 22nd oct?" | Accurately extracts ordinal dates ("22nd oct") | **PASS** |
| **TEST-11** | `TestDoctorOrchestrator` | "What's my schedule on 1st oct?" | Distinguishes single-digit from compound numbers | **PASS** |
| **TEST-12** | `TestDoctorOrchestrator` | "I'm not available on 22nd oct" | Generates unavailability proposal with conflicts | **PASS** |
| **TEST-13** | `TestDoctorOrchestrator` | "Tell me about Ananya Iyer" | Searches patient roster and confirms profile | **PASS** |
| **TEST-14** | `TestDoctorOrchestrator` | "What medication is Ananya Iyer taking?" | Recognizes patient and lists active prescriptions | **PASS** |
| **TEST-15** | `TestDoctorOrchestrator` | "Hello" / "Who are you?" | Responds with doctor capabilities and agenda options | **PASS** |
| **TEST-16** | `TestDoctorOrchestrator` | "Yes" with pending block action | Executes Supabase leave block and rebooking | **PASS** |
| **TEST-17** | `TestDoctorOrchestrator` | Consultation note extraction | Extracts diagnosis, vitals, prescriptions, and follow-ups | **PASS** |
| **TEST-18** | `TestDoctorOrchestrator` | "What's the weather today?" | Deflects non-medical chit-chat to clinical capabilities | **PASS** |
| **TEST-19** | `TestDoctorOrchestrator` | Fallback month matching | Defaults omitted months to active week's month | **PASS** |

Execution command:
```bash
python -m unittest discover tests -v
```

---

## 11. Engineering Challenges & Solutions

| Challenge Encountered | Root Cause | Engineering Solution |
|---|---|---|
| **PostgreSQL 22P02 Enum Error** | Code attempted to set `status = "Reschedule Pending"`, which is not declared in Supabase's `appointment_status_enum`. | Implemented `STATUS_NORMALIZATION_MAP` and `normalize_appointment_status`. When dates are changing, status is automatically normalized to `"Pending"` (awaiting patient confirmation) or `"Rescheduled"` on superseded records. |
| **Medication Name Redundancy** | Brand names in pharmaceutical catalogs sometimes contained dosage numbers (e.g. *Dolo 650*), resulting in display strings like *"Dolo 650 650 mg"*. | Cleaned baseline seed data and implemented regex deduplication `re.sub(r'\s*\d+\s*$', '', brand)` before concatenating dosage strings. |
| **Streamlit WebSocket Drops on EC2** | Streamlit UI became unresponsive or disconnected when accessed through standard HTTP reverse proxies. | Configured Nginx with persistent WebSocket upgrade directives (`proxy_set_header Upgrade $http_upgrade`, `proxy_set_header Connection "upgrade"`, `proxy_read_timeout 86400`). |
| **Raw UUID Visual Clutter** | 36-character hexadecimal UUIDs appeared in appointment cards, charts, and agent replies. | Built a centralized short ID system (`tools/db_tools.py`) mapping UUIDs into clean clinical badges (`PID-8421`, `DOC-RHEA-01`, `MED-6661`, `APT-1001`, `CON-1001`, `LAB-1001`). |
| **Multi-Table RAG Ingestion Sync** | Consultation notes combine diagnosis, vitals, future visits, and drugs into a single text block. | Engineered `tools/consultation_ingestion.py` using `pypdf` and Groq JSON entity extraction, followed by synchronized writes across 5 relational tables upon doctor confirmation. |

---

## 12. Conclusion & Future Roadmap

VESPH Care provides an enterprise-ready blueprint for post-discharge clinical coordination. By fusing deterministic state machines for safety-critical actions with scoped LLM extraction and relational PostgreSQL persistence, it reduces physician administrative overhead while providing patients with clear, structured recovery guidance.

### Future Roadmap
1. **FHIR R4 / HL7 Integration:** Direct bi-directional integration with hospital EHRs (Epic, Cerner).
2. **Omni-Channel Patient Notifications:** Automated WhatsApp Business API and SMS triggers for mealtime medication reminders and schedule change alerts.
3. **Multilingual Regional Support:** Localization for regional Indian languages (Hindi, Marathi, Tamil, Telugu).
4. **Computer Vision Lab Reader:** Multimodal vision parsing of printed pathology and diagnostic imaging reports.
