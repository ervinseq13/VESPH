# Patient Follow-up Assistant

A single-screen Streamlit frontend for a healthcare capstone. It shows one synthetic patient, their follow-up work, and an agent-style chat without login, user switching, or external services.

## What is included

- **Patient Summary Agent:** patient details, health history, diagnostic summary, medication summary, appointments, and discharge summary.
- **Reminder Agent:** two-stage appointment reminders, confirm/reschedule actions, diagnostic and insurance-document reminders, medication reminders, and new booking requests.
- **Escalation Agent:** deterministic handling for emergencies, missed appointments, unavailable doctors, wrong reports, new care requests, and report reissues. Every escalation ends with resolution choices that the patient must confirm.
- **One-screen layout:** patient record on the left, care workbench in the centre, and chat/actions on the right.
- **Reliable demo mode:** deterministic safety and care routes continue to work from local synthetic data. Groq enhances unsupported open-ended questions when configured, with a local fallback if it is unavailable.
- **Chat-accessible readiness check:** ask “Check connections” to validate Groq and Supabase from the deployed Streamlit server without displaying secret values or assuming tables already exist.

## Run locally

From this folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

For local integration testing, create `.streamlit/secrets.toml` (never commit it):

```toml
LLM_API_KEY = "your-groq-key"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-publishable-or-anon-key"
# Optional. Defaults to the current production model below.
GROQ_MODEL = "openai/gpt-oss-20b"
```

Use only a Supabase publishable/anon key in this user-facing application—never a service-role or secret key. The same names can be added in Streamlit Community Cloud under **App settings → Secrets**.

If `py` is not available, install Python 3.11+ and run the equivalent commands with `python`.

## Run the checks

The routing and safety checks use Python's built-in test runner:

```powershell
python -m unittest discover -s tests -v
```

## Demo walkthrough

1. Start with the **72-hour surgical follow-up reminder** in the centre and confirm it.
2. Open **Reschedule**, choose an available timeslot, and show that open slots are automatically accepted and confirmed immediately without waiting for hospital approval.
3. Move across the four care tabs: **Appointments**, **Diagnostics**, **Medication**, and **Discharge**. Click any record card to open its detail popup and download action.
4. Use the **+** button in the assistant panel to request a new appointment or upload a diagnostic file.
5. Ask “Summarise my latest report” and “What medicines am I taking?”
6. Ask “This is someone else's report,” then choose how the Records Desk should resolve it. The confirmed instruction is stored in the escalation record and acknowledged in chat.
7. Ask “I have severe pain, is this an emergency?” to demonstrate immediate safety guidance followed by confirmation of how the patient is proceeding. The confirmation never replaces or delays the emergency instruction.

## Data included

All records are fictional and live under `data/`:

| File | Purpose |
|---|---|
| `patient.json` | Identity and the five patient summaries |
| `patient_appointments.json` | Patient appointment history and upcoming visits |
| `patient_diagnostics.json` | Reports and diagnostic summaries |
| `patient_discharge.json` | Admission, procedure, discharge, and recovery instructions |
| `medications.json` | Current medication schedule |
| `appointment_schedule.json` | Bookable hospital appointment slots |
| `diagnostic_schedule.json` | Booked and available diagnostic slots |
| `doctor_schedule.json` | Doctor availability used by rescheduling |
| `operation_schedule.json` | Operation-theatre record for the patient journey |
| `reminders.json` | First and second reminder intervals |
| `escalations.json` | Pending and patient-confirmed escalation resolutions |

The separation is intentional: `data_store.py` is the only module that knows these are JSON files. It can later be replaced by APIs or a database without redesigning the screen.

## Minimal architecture

```text
Streamlit UI
   ├── Patient summary panel
   ├── Follow-up workbench
   └── Chat and action panel
            │
            ▼
      LangGraph orchestrator
      ├── Patient Summary Agent
      ├── Reminder Agent
      └── Escalation Agent
            │
            ▼
      Ground-truth data tools
            │
            ▼
      Synthetic JSON repository
```

## Agent and memory structure

The app uses a deterministic LangGraph `StateGraph` for safety-critical routing. Clinical records are passed as run-scoped context, so they are fetched from the current source of truth on each turn rather than written into conversational memory. If `LLM_API_KEY` is configured, only router fallback questions go to Groq with a constrained copy of the synthetic patient record.

```text
orchestrator/   graph, state schema, checkpointer, and long-term store
agents/         plug-and-play summary, reminder, and escalation agents
tools/          source-of-truth data boundary and ChromaDB retrieval seam
scheduled/      reminder generation kept outside the conversational graph
```

The local capstone uses LangGraph's `InMemorySaver` for thread-scoped state and `InMemoryStore` for confirmed durable facts. For production, swap those backends for `PostgresSaver` and `PostgresStore` using Supabase Postgres. Replace `tools/db_tools.py` with Supabase reads/writes, store files in private S3, and use ChromaDB only for retrieval over report/discharge text—not as the source of truth for appointments or prescriptions.

`SUPABASE_URL` and `SUPABASE_KEY` are initialized today, but the app deliberately does not query clinical tables until their schema and row-level security policies are finalized. The connection check validates the project endpoint and key through Supabase Auth, while synthetic JSON remains the declared source of truth. This avoids coupling the agent to placeholder table names.

Suggested LangGraph nodes:

```text
User message
   → emergency safety check
   → intent router
      → summary retrieval
      → appointment/reminder action
      → records escalation
   → explicit resolution confirmation for every escalation
   → response formatter
```

The escalation confirmation is important: the assistant opens a pending escalation, displays context-specific resolution choices at the end of the chat response, and records the patient's selection before the hospital team acts. Emergency replies still tell the patient to call immediately; the confirmation only records what they are doing.

## Production cautions

This is a frontend prototype, not a clinical system. Before real patient use, add authentication, consent, encryption, audit logs, role-based access, retention rules, clinical review, and a tested emergency policy. Never put an LLM API key, AWS secret, or real patient data inside the frontend or repository.
