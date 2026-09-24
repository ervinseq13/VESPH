from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from chat_service import answer_chat
from data_store import load_demo_data
from integrations import IntegrationHub, IntegrationSettings
from orchestrator.graph import build_orchestrator, resolve


ASSET_DIR = Path(__file__).resolve().parent / "assets"
PATIENT_CHAT_AVATAR = str(ASSET_DIR / "patient-avatar.svg")
VESPH_CHAT_AVATAR = str(ASSET_DIR / "vesph-avatar.svg")


st.set_page_config(
    page_title="VESPH Care · Patient Follow-up",
    page_icon="✚",
    layout="wide",
    initial_sidebar_state="collapsed",
)


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700&display=swap');

:root {
  --ink: #173532;
  --muted: #667B78;
  --teal: #0B6E69;
  --teal-dark: #075651;
  --mint: #E5F3F0;
  --canvas: #F4F7F6;
  --line: #DCE7E4;
  --amber: #A65E00;
  --amber-bg: #FFF5DE;
  --red: #A53A35;
  --red-bg: #FFF0EE;
}

html, body, [class*="css"] { font-family: "DM Sans", sans-serif; }
.stApp { background: var(--canvas); color: var(--ink); }
.block-container { max-width: 1760px; padding: 1.1rem 1.45rem 2rem; }
[data-testid="stHeader"] { background: rgba(244,247,246,.86); }
[data-testid="stToolbar"] { right: 1rem; }
h1, h2, h3 { font-family: "Manrope", sans-serif !important; letter-spacing: -.02em; }

.brand-panel {
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: 0 6px 24px rgba(23,53,50,.05);
  padding: 10px 12px;
  margin-bottom: 8px;
}
.brand-lockup { display:flex; align-items:center; gap:12px; }
.brand-mark {
  width: 38px; height: 38px; border-radius: 11px; background: var(--teal);
  color: white; display:flex; align-items:center; justify-content:center;
  font-size: 22px; font-weight:700;
}
.brand-name { font: 700 17px/1.15 "Manrope", sans-serif; color:var(--ink); }
.brand-sub { font-size: 11px; color:var(--muted); margin-top:3px; }

.panel-title { margin:0 0 8px; padding-top:2px; }
.eyebrow { color:var(--teal); text-transform:uppercase; letter-spacing:.11em; font-size:10px; font-weight:700; }
.panel-heading { color:var(--ink); font:700 17px/1.2 "Manrope", sans-serif; margin-top:3px; }
.panel-copy { color:var(--muted); font-size:11px; margin-top:3px; }

.patient-card {
  background: linear-gradient(145deg, #0B6E69 0%, #075651 100%);
  color:white; border-radius:17px; padding:10px; margin-bottom:7px;
  box-shadow:0 10px 25px rgba(7,86,81,.16);
}
.patient-head { display:flex; gap:9px; align-items:center; }
.avatar {
  width:38px; height:38px; border-radius:50%; background:rgba(255,255,255,.17);
  border:1px solid rgba(255,255,255,.28); display:flex; align-items:center;
  justify-content:center; font-weight:700; font-size:13px;
}
.patient-name { font:700 15px/1.2 "Manrope", sans-serif; }
.patient-id { font-size:10px; opacity:.75; margin-top:3px; }
.patient-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:5px; margin-top:8px; }
.patient-stat { background:rgba(255,255,255,.09); border-radius:8px; padding:5px 6px; min-width:0; }
.patient-stat.compact { grid-column:span 2; }
.patient-stat.wide { grid-column:span 3; }
.patient-stat span { display:block; font-size:8px; opacity:.7; }
.patient-stat strong { display:block; margin-top:1px; font-size:10px; line-height:1.3; overflow-wrap:anywhere; }
.patient-contact strong { font-size:8px; font-weight:600; line-height:1.35; }

.summary-note {
  background:white; border:1px solid var(--line); border-radius:14px;
  padding:8px 9px; color:var(--ink); font-size:12px; line-height:1.4; margin-bottom:6px;
}
.summary-copy { min-height:36px; max-height:36px; overflow:hidden; color:#425B58; font-size:9px; line-height:1.34; }
.summary-label { display:flex; gap:6px; align-items:center; font-weight:700; font-size:10px; margin-bottom:4px; }
.summary-icon { width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; border-radius:6px; background:var(--mint); }
.micro-list { display:flex; flex-wrap:wrap; gap:5px; margin-top:5px; }
.micro-pill { padding:3px 6px; border-radius:999px; background:#F0F5F4; color:#42615E; font-size:8px; font-weight:600; }

.reminder-card { min-height:108px; margin-bottom:6px; }
.reminder-card.primary { background:linear-gradient(145deg,#113E3A,#0B6E69); color:white; border-radius:13px; padding:10px; }
.reminder-card.secondary { background:white; color:var(--ink); border-radius:13px; padding:10px; }
.reminder-top { display:flex; justify-content:space-between; align-items:center; gap:8px; }
.reminder-kicker { font-size:9px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; opacity:.72; }
.reminder-time { background:rgba(255,255,255,.13); border-radius:999px; padding:5px 8px; font-size:9px; font-weight:700; }
.reminder-title { font:700 14px/1.2 "Manrope",sans-serif; margin-top:9px; }
.reminder-detail { font-size:10px; opacity:.82; margin-top:4px; line-height:1.35; }
.reminder-meta { margin-top:10px; font-size:9px; opacity:.72; line-height:1.45; }
.reminder-card.secondary .reminder-kicker { color:var(--teal); opacity:1; }
.reminder-card.secondary .reminder-time { background:var(--mint); color:var(--teal-dark); }

.item-card { background:white; border:1px solid var(--line); border-radius:14px; padding:12px 13px; margin-bottom:8px; }
.item-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
.item-title { color:var(--ink); font-weight:700; font-size:12px; }
.item-sub { color:var(--muted); font-size:10px; margin-top:3px; line-height:1.4; }
.item-meta { color:#42615E; font-size:10px; margin-top:8px; }
.status { border-radius:999px; padding:4px 7px; font-size:8px; font-weight:700; white-space:nowrap; background:var(--mint); color:var(--teal-dark); }
.status.wait { background:var(--amber-bg); color:var(--amber); }
.status.old { background:#F0F3F2; color:#61726F; }
.alert-strip { background:var(--amber-bg); color:#704500; border-radius:11px; padding:9px 10px; font-size:10px; margin:8px 0; }
.danger-strip { background:var(--red-bg); color:var(--red); border-radius:11px; padding:9px 10px; font-size:10px; margin:8px 0; }
.safety-note { background:#EDF4F3; color:#536C69; border-radius:11px; padding:7px 9px; font-size:8px; line-height:1.35; margin-top:6px; }
.escalation-confirm { background:var(--amber-bg); color:#704500; border-radius:11px; padding:8px 9px; font-size:9px; line-height:1.4; margin:2px 0 5px; }
.escalation-confirm strong { display:block; color:#5D3900; margin-bottom:2px; }
.escalation-resolved { background:var(--mint); color:var(--teal-dark); border-radius:9px; padding:6px 8px; font-size:8px; margin:2px 0 6px; }
[class*="st-key-escalation_actions_"] .stButton > button { min-height:29px; padding:4px 7px; font-size:9px; line-height:1.2; }
.agent-route { font-size:9px; color:var(--teal); font-weight:700; margin-top:-8px; margin-bottom:8px; padding-left:5px; }
.footer-note { color:#7D8F8C; text-align:center; font-size:9px; margin-top:16px; }
.timeline-label { color:#6C807D; font-size:9px; font-weight:700; letter-spacing:.09em; margin:9px 0 5px; }
.detail-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; margin:5px 0 10px; }
.detail-cell { background:#F5F8F7; border-radius:9px; padding:8px; font-size:10px; color:#425B58; }
.detail-cell strong { display:block; color:var(--ink); margin-bottom:2px; }
.st-key-suggestion_row .stButton > button { min-height:23px; padding:1px 3px; }
.st-key-suggestion_row .stButton > button > div { width:100%; justify-content:center !important; }
.st-key-suggestion_row [data-testid="stMarkdownContainer"] {
  height:100%; display:flex; align-items:center; justify-content:center;
  line-height:1 !important;
}
.st-key-suggestion_row .stButton p {
  display:block !important; width:100%; margin:0; font-size:8px !important; line-height:1 !important;
  text-align:center !important; white-space:nowrap;
}
[data-testid="stBaseButton-tertiary"] {
  min-height:58px !important; justify-content:flex-start !important; text-align:left !important;
  background:#FFFFFF !important; border:1px solid var(--line) !important;
  border-radius:12px !important; padding:10px 12px !important;
  box-shadow:0 1px 3px rgba(23,53,50,.035);
}
[data-testid="stBaseButton-tertiary"] p {
  width:100% !important; text-align:left !important;
}
[data-testid="stBaseButton-tertiary"] > div {
  width:100% !important; justify-content:flex-start !important;
}
[data-testid="stBaseButton-tertiary"]:hover { border-color:#9ABCB7 !important; background:#F8FBFA !important; }
[data-testid="stForm"] { border:0 !important; padding:8px 0 2px !important; }

[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line) !important; border-radius:16px !important; background:#FFFFFF; }
[data-testid="stExpander"] { border:1px solid var(--line); border-radius:12px; background:#FFFFFF; }
[data-testid="stExpander"] summary { font-size:10px; font-weight:600; color:var(--ink); min-height:43px; }
.stTabs [data-baseweb="tab-list"] { gap:3px; background:#EAF0EE; padding:4px; border-radius:11px; }
.stTabs [data-baseweb="tab"] { height:34px; border-radius:8px; padding:0 10px; font-size:10px; }
.stTabs [aria-selected="true"] { background:white !important; box-shadow:0 1px 5px rgba(23,53,50,.08); }
.stButton > button, .stDownloadButton > button { border-radius:10px; min-height:34px; font-weight:600; font-size:11px; border-color:#C9D8D5; }
.stButton > button[kind="primary"] { background:var(--teal); border-color:var(--teal); }
[data-testid="stChatMessage"] { background:#F7FAF9; border:1px solid var(--line); border-radius:13px; padding:8px 10px; margin-bottom:7px; }
[data-testid="stChatMessage"] p { font-size:11px; line-height:1.48; }
[data-testid="stChatInput"] { border-color:#C9D8D5; border-radius:12px; }
[data-testid="stFileUploader"] { font-size:11px; }
div[data-testid="stMetric"] { background:#F7FAF9; border:1px solid var(--line); border-radius:11px; padding:8px; }
div[data-testid="stMetric"] label { font-size:9px; }
div[data-testid="stMetricValue"] { font-size:16px; }

.left-panel-marker, .middle-panel-marker, .right-panel-marker { display:none; }

@media (min-width: 901px) {
  [data-testid="stAppViewContainer"], [data-testid="stMain"] { overflow:hidden; }
  .block-container { height:100vh; overflow:hidden; padding-bottom:.75rem; }
  [data-testid="stColumn"]:has(.left-panel-marker),
  [data-testid="stColumn"]:has(.middle-panel-marker),
  [data-testid="stColumn"]:has(.right-panel-marker) {
    height:calc(100vh - 2rem);
    min-height:0;
    box-sizing:border-box;
    padding-top:8px;
    padding-bottom:10px;
  }
  [data-testid="stColumn"]:has(.left-panel-marker),
  [data-testid="stColumn"]:has(.right-panel-marker) { overflow:hidden; }
  [data-testid="stColumn"]:has(.right-panel-marker) { position:relative; }
  .stApp .st-key-chat_history {
    height:calc(100vh - 19.1rem) !important;
    min-height:calc(100vh - 19.1rem) !important;
    max-height:calc(100vh - 19.1rem) !important;
    overflow-y:auto;
    padding-bottom:8px;
  }
  .st-key-chat_dock {
    position:absolute;
    left:0;
    right:0;
    bottom:76px;
    gap:6px !important;
  }
  .st-key-chat_dock [data-testid="stVerticalBlock"] { gap:6px !important; }
  .st-key-chat_dock [data-testid="stForm"] { margin:0 !important; padding:0 !important; }
  .st-key-chat_dock .safety-note { margin-top:0; }
  [data-testid="stColumn"]:has(.middle-panel-marker) {
    overflow-y:hidden;
    overflow-x:hidden;
  }
  [data-testid="stColumn"]:has(.middle-panel-marker) .stTabs [role="tabpanel"] {
    height:calc(100vh - 390px);
    min-height:220px;
    overflow-y:auto;
    overflow-x:hidden;
    scrollbar-gutter:stable;
    padding-right:4px;
  }
  .footer-note { display:none; }
}

@media (max-width: 900px) {
  .block-container { padding:.75rem; }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def initialize_state() -> None:
    if "care_data" not in st.session_state:
        st.session_state.care_data = load_demo_data()
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi Ananya — I have your recent hospital record ready. I can help with your recovery summary, appointments, reports, or medicines.",
                "agent": "Patient Summary Agent",
            }
        ]
    if "taken_medications" not in st.session_state:
        st.session_state.taken_medications = set()
    if "discharge_uploads" not in st.session_state:
        st.session_state.discharge_uploads = []


initialize_state()
DATA = st.session_state.care_data


@st.cache_resource
def get_orchestrator():
    """Build the graph once so thread checkpoints survive Streamlit reruns."""

    return build_orchestrator()


ORCHESTRATOR = get_orchestrator()


@st.cache_resource
def get_integrations() -> IntegrationHub:
    """Create server-only clients from Streamlit secrets or local env vars."""

    return IntegrationHub(IntegrationSettings.from_sources(st.secrets))


INTEGRATIONS = get_integrations()


def panel_header(eyebrow: str, title: str, copy: str = "") -> None:
    st.markdown(
        f"""
        <div class="panel-title">
          <div class="eyebrow">{escape(eyebrow)}</div>
          {f'<div class="panel-heading">{escape(title)}</div>' if title else ''}
          {f'<div class="panel-copy">{escape(copy)}</div>' if copy else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_class(status: str) -> str:
    lowered = status.lower()
    if "await" in lowered or "pending" in lowered:
        return "status wait"
    if "complete" in lowered or "reviewed" in lowered:
        return "status old"
    return "status"


def clipped(text: str, max_chars: int = 180) -> str:
    """Keep fixed summary cards compact without breaking a word."""

    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def add_chat_message(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    patient_id = DATA["patient"]["id"]
    reply = answer_chat(
        ORCHESTRATOR,
        INTEGRATIONS,
        prompt,
        DATA,
        patient_id,
        recent_messages=st.session_state.messages[:-1],
        thread_id=patient_id,
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": reply.message,
            "agent": reply.agent,
            "escalated": reply.escalated,
            "escalation": reply.escalation,
        }
    )


def confirm_escalation_resolution(message_index: int, resolution: str) -> None:
    """Record a patient's resolution choice and close the pending chat prompt."""

    source_message = st.session_state.messages[message_index]
    escalation = source_message.get("escalation")
    if not escalation or escalation.get("status") != "pending_confirmation":
        return

    patient_id = DATA["patient"]["id"]
    result = resolve(
        ORCHESTRATOR,
        escalation["id"],
        resolution,
        DATA,
        patient_id,
        thread_id=patient_id,
    )
    source_message["escalation"] = result.escalation
    st.session_state.messages.append(
        {
            "role": "user",
            "content": f"Resolution confirmed: {resolution}",
        }
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.message,
            "agent": result.agent,
            "escalated": result.escalated,
            "escalation": None,
        }
    )


@st.dialog("Choose a new appointment time")
def reschedule_dialog() -> None:
    st.caption("Available General Surgery times for this patient")
    options = DATA["appointment_schedule"][:3]
    labels = [f"{row['date']} · {row['doctor']}" for row in options]
    selected_label = st.selectbox("Date and doctor", labels)
    selected = options[labels.index(selected_label)]
    time = st.selectbox("Preferred time", selected["slots"])
    note = st.text_input("Anything the scheduling desk should know?", placeholder="Optional")
    if st.button("Request this time", type="primary", use_container_width=True):
        appointment = DATA["appointments"][0]
        appointment.update(
            {
                "date": selected["date"],
                "time": time,
                "doctor": selected["doctor"],
                "status": "Reschedule requested",
                "request_note": note,
            }
        )
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"Your preferred time, {selected['date']} at {time}, has been sent to the scheduling desk. The existing appointment stays active until the hospital confirms the change.",
                "agent": "Reminder Agent · Scheduling",
            }
        )
        st.rerun()


@st.dialog("Add to your care record")
def add_item_dialog(default_action: str = "New appointment") -> None:
    actions = ["New appointment", "Diagnostic report", "Medication", "Discharge document"]
    action = st.radio(
        "What would you like to add?",
        actions,
        index=actions.index(default_action),
        horizontal=True,
    )
    if action == "New appointment":
        schedule = DATA["appointment_schedule"]
        departments = list(dict.fromkeys(row["department"] for row in schedule))
        department = st.selectbox("Department", departments)
        matches = [row for row in schedule if row["department"] == department]
        doctor_options = [f"{row['doctor']} · {row['date']}" for row in matches]
        doctor_date = st.selectbox("Doctor and date", doctor_options)
        selected = matches[doctor_options.index(doctor_date)]
        slot = st.selectbox("Available time", selected["slots"])
        reason = st.text_input("Reason for visit", placeholder="Briefly describe what you need")
        if st.button("Send booking request", type="primary", use_container_width=True):
            DATA["appointments"].insert(
                0,
                {
                    "id": f"APT-NEW-{len(DATA['appointments']) + 1}",
                    "date": selected["date"],
                    "time": slot,
                    "department": department,
                    "doctor": selected["doctor"],
                    "type": reason or "New consultation",
                    "location": "Location shared after confirmation",
                    "status": "Booking requested",
                    "preparation": "The hospital will share preparation details.",
                },
            )
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"Your {department} appointment request for {selected['date']} at {slot} has been sent. I’ll remind you when the hospital confirms it.",
                    "agent": "Reminder Agent · Appointments",
                }
            )
            st.rerun()
    elif action == "Diagnostic report":
        report_type = st.selectbox("Report type", ["Blood test", "Radiology", "Prescription", "Other diagnostic"])
        uploaded = st.file_uploader("Choose a PDF or image", type=["pdf", "png", "jpg", "jpeg"])
        note = st.text_input("Note for the care team", placeholder="Optional")
        if st.button("Add report", type="primary", use_container_width=True, disabled=uploaded is None):
            DATA["diagnostics"].insert(
                0,
                {
                    "id": f"UPL-{len(DATA['diagnostics']) + 1}",
                    "date": "19 Sep 2026",
                    "name": uploaded.name if uploaded else "Uploaded report",
                    "category": report_type,
                    "ordered_by": "Patient upload",
                    "status": "Awaiting review",
                    "summary": note or "New patient-uploaded report awaiting care-team review.",
                    "flag": "Review pending",
                },
            )
            st.rerun()
    elif action == "Medication":
        name = st.text_input("Medication name and strength", placeholder="e.g. Vitamin D3 60,000 IU")
        instruction = st.text_input("Instructions", placeholder="e.g. Once weekly after food")
        duration = st.text_input("Duration", placeholder="e.g. 6 weeks")
        if st.button("Add medication", type="primary", use_container_width=True, disabled=not name.strip()):
            DATA["medications"].insert(
                0,
                {
                    "name": name.strip(),
                    "instruction": instruction.strip() or "Instructions not added",
                    "duration": duration.strip() or "Not specified",
                    "next_dose": "Not scheduled",
                    "status": "Patient added",
                },
            )
            st.rerun()
    else:
        uploaded = st.file_uploader("Choose a discharge PDF or image", type=["pdf", "png", "jpg", "jpeg"])
        note = st.text_input("Document note", placeholder="Optional")
        if st.button("Add discharge document", type="primary", use_container_width=True, disabled=uploaded is None):
            st.session_state.discharge_uploads.insert(
                0,
                {
                    "name": uploaded.name if uploaded else "Discharge document",
                    "date": "19 Sep 2026",
                    "note": note.strip() or "Patient-uploaded discharge document.",
                },
            )
            st.rerun()


@st.dialog("Record details", width="large")
def record_detail_dialog(record_type: str, record: dict) -> None:
    """Show the full record and keep download actions out of the timeline."""

    if record_type == "appointment":
        st.subheader(record["type"])
        st.caption(f"{record['date']} · {record['time']} · {record['status']}")
        st.markdown(
            f"""
            <div class="detail-grid">
              <div class="detail-cell"><strong>Doctor</strong>{escape(record['doctor'])}</div>
              <div class="detail-cell"><strong>Department</strong>{escape(record['department'])}</div>
              <div class="detail-cell"><strong>Location</strong>{escape(record['location'])}</div>
              <div class="detail-cell"><strong>Patient ID</strong>{escape(DATA['patient']['id'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if record.get("preparation"):
            st.info(record["preparation"])
        filename = f"{record['id']}.txt"
    elif record_type == "diagnostic_booking":
        st.subheader(record["test"])
        st.caption(f"{record['date']} · {record['time']} · {record['status']}")
        st.markdown(
            f"""
            <div class="detail-grid">
              <div class="detail-cell"><strong>Location</strong>{escape(record['location'])}</div>
              <div class="detail-cell"><strong>Preparation</strong>{escape(record['preparation'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        filename = f"{record['id']}.txt"
    elif record_type == "diagnostic_result":
        st.subheader(record["name"])
        st.caption(f"{record['date']} · {record['category']} · {record['status']}")
        st.write(record["summary"])
        st.info(f"Ordered by {record['ordered_by']} · {record['flag']}")
        filename = f"{record['id']}.txt"
    elif record_type == "medication":
        st.subheader(record["name"])
        st.caption(record["status"])
        st.markdown(
            f"""
            <div class="detail-grid">
              <div class="detail-cell"><strong>Instructions</strong>{escape(record['instruction'])}</div>
              <div class="detail-cell"><strong>Duration</strong>{escape(record['duration'])}</div>
              <div class="detail-cell"><strong>Next dose</strong>{escape(record['next_dose'])}</div>
              <div class="detail-cell"><strong>Patient ID</strong>{escape(DATA['patient']['id'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        filename = "medication-record.txt"
    elif record_type == "discharge":
        st.subheader("Surgical discharge")
        st.caption(f"{record['discharge_date']} · Completed")
        st.markdown(
            f"""
            <div class="detail-grid">
              <div class="detail-cell"><strong>Consultant</strong>{escape(record['consultant'])}</div>
              <div class="detail-cell"><strong>Department</strong>{escape(record['department'])}</div>
              <div class="detail-cell"><strong>Diagnosis</strong>{escape(record['diagnosis'])}</div>
              <div class="detail-cell"><strong>Procedure</strong>{escape(record['procedure'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write(record["condition_at_discharge"])
        st.caption("Instructions")
        for instruction in record["instructions"]:
            st.markdown(f"- {instruction}")
        filename = "discharge-summary.txt"
    else:
        st.subheader(record["name"])
        st.caption(f"{record['date']} · Awaiting review")
        st.write(record["note"])
        filename = "discharge-upload.txt"

    download_data = "\n".join(f"{key}: {value}" for key, value in record.items())
    st.download_button(
        "Download record",
        data=download_data,
        file_name=filename,
        mime="text/plain",
        icon=":material/download:",
        use_container_width=True,
    )


def record_card(
    *,
    title: str,
    meta: str,
    key: str,
    record_type: str,
    record: dict,
    icon: str,
) -> None:
    if st.button(
        f"**{title}**  \n{meta}",
        key=key,
        type="tertiary",
        icon=icon,
        use_container_width=True,
        wrap=True,
    ):
        record_detail_dialog(record_type, record)


patient = DATA["patient"]
left, middle, right = st.columns([1, 1.8, 0.92], gap="medium")


with left:
    st.markdown('<span class="left-panel-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="brand-panel">
          <div class="brand-lockup">
            <div class="brand-mark">✚</div>
            <div><div class="brand-name">VESPH Care</div><div class="brand-sub">Virtual Engagement System for Patient Health</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    panel_header("Patient overview", "", "Updated 19 Sep 2026 · 8:40 PM")
    st.markdown(
        f"""
        <div class="patient-card">
          <div class="patient-head">
            <div class="avatar">{escape(patient['initials'])}</div>
            <div><div class="patient-name">{escape(patient['name'])}</div><div class="patient-id">Patient ID · {escape(patient['id'])}</div></div>
          </div>
          <div class="patient-grid">
            <div class="patient-stat compact"><span>Age</span><strong>{patient['age']} yrs</strong></div>
            <div class="patient-stat compact"><span>Blood</span><strong>{escape(patient['blood_group'])}</strong></div>
            <div class="patient-stat compact"><span>Sex</span><strong>{escape(patient['gender'])}</strong></div>
            <div class="patient-stat wide"><span>Primary doctor</span><strong>{escape(patient['primary_doctor'].replace('Dr. ', 'Dr. '))}</strong></div>
            <div class="patient-stat wide patient-contact"><span>Contact</span><strong>{escape(patient['phone'])}<br>{escape(patient['email'])}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="summary-note">
          <div class="summary-label"><span class="summary-icon">♡</span> Health summary</div>
          <div class="summary-copy">{escape(clipped(patient['health_summary'], 190))}</div>
          <div class="micro-list">
            <span class="micro-pill">Allergy · {escape(patient['allergies'][0])}</span>
            <span class="micro-pill">Mild asthma</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for icon, label, summary in [
        ("⌁", "Diagnostic summary", patient["diagnostic_summary"]),
        ("◌", "Medication summary", patient["medication_summary"]),
        ("◷", "Appointment summary", patient["appointment_summary"]),
    ]:
        st.markdown(
            f"""
            <div class="summary-note">
              <div class="summary-label"><span class="summary-icon">{icon}</span> {escape(label)}</div>
              <div class="summary-copy">{escape(clipped(summary))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="safety-note">This view summarizes hospital records. It does not replace your doctor or provide a diagnosis.</div>',
        unsafe_allow_html=True,
    )


with middle:
    st.markdown('<span class="middle-panel-marker"></span>', unsafe_allow_html=True)
    panel_header("Notification centre", "")
    next_appointment = DATA["appointments"][0]
    reminder_strip = st.container(
        horizontal=True,
        wrap=False,
        horizontal_alignment="left",
        gap="small",
        key="reminder_carousel",
    )
    with reminder_strip.container(border=True, width=340):
        st.markdown(
            f"""
            <div class="reminder-card primary">
              <div class="reminder-top"><div class="reminder-kicker">Appointment · action needed</div><div class="reminder-time">In 3 days</div></div>
              <div class="reminder-title">{escape(next_appointment['type'])}</div>
              <div class="reminder-detail">{escape(next_appointment['doctor'])} · {escape(next_appointment['date'])}<br>{escape(next_appointment['time'])} · {escape(next_appointment['location'])}</div>
              <div class="reminder-meta">Reminder 1 of 2 · Bring latest CBC</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        action_a, action_b = st.columns(2, gap="small")
        with action_a:
            if st.button("Confirm", type="primary", key="confirm_reminder", use_container_width=True):
                next_appointment["status"] = "Confirmed"
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": "Your surgical follow-up is confirmed. I’ll send the second reminder 24 hours before the appointment.",
                        "agent": "Reminder Agent · Appointments",
                    }
                )
                st.rerun()
        with action_b:
            if st.button("Reschedule", key="reschedule_reminder", use_container_width=True):
                reschedule_dialog()
    with reminder_strip.container(border=True, width=340):
        st.markdown(
            """
            <div class="reminder-card secondary">
              <div class="reminder-top"><div class="reminder-kicker">Diagnostic</div><div class="reminder-time">Tomorrow</div></div>
              <div class="reminder-title">Complete Blood Count</div>
              <div class="reminder-detail">20 Sep · 9:00 AM<br>Ground floor · No fasting</div>
              <div class="reminder-meta">Reminder 1 of 2</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("View booking", icon=":material/visibility:", key="view_cbc_reminder", use_container_width=True):
            record_detail_dialog("diagnostic_booking", DATA["diagnostic_schedule"][0])
    with reminder_strip.container(border=True, width=340):
        st.markdown(
            """
            <div class="reminder-card secondary">
              <div class="reminder-top"><div class="reminder-kicker">Document</div><div class="reminder-time">Due 24 Sep</div></div>
              <div class="reminder-title">Insurance claim form</div>
              <div class="reminder-detail">Signed copy required<br>1 document pending</div>
              <div class="reminder-meta">Upload by 24 Sep · Reminder 1 of 2</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Upload", icon=":material/upload_file:", key="insurance_upload", use_container_width=True):
            add_item_dialog("Discharge document")

    appointments_tab, diagnostics_tab, medications_tab, discharge_tab = st.tabs(
        ["Appointments", "Diagnostics", "Medication", "Discharge"]
    )

    with appointments_tab:
        head_a, head_b = st.columns([1, 0.52])
        with head_a:
            st.caption("UPCOMING → PAST")
        with head_b:
            if st.button("＋ Add", key="new_appointment_tab", use_container_width=True):
                add_item_dialog("New appointment")

        upcoming_appointments = [row for row in DATA["appointments"] if row["status"] != "Completed"]
        past_appointments = [row for row in DATA["appointments"] if row["status"] == "Completed"]
        for group_label, records in [("UPCOMING", upcoming_appointments), ("PAST", past_appointments)]:
            st.markdown(f'<div class="timeline-label">{group_label}</div>', unsafe_allow_html=True)
            for appointment in records:
                record_card(
                    title=appointment["type"],
                    meta=f"{appointment['date']} · {appointment['time']} · {appointment['doctor']} · {appointment['status']}",
                    key=f"appointment_card_{appointment['id']}",
                    record_type="appointment",
                    record=appointment,
                    icon=":material/calendar_month:",
                )

    with diagnostics_tab:
        head_a, head_b = st.columns([1, 0.52])
        with head_a:
            st.caption("UPCOMING → PAST")
        with head_b:
            if st.button("＋ Upload", key="add_report_tab", use_container_width=True):
                add_item_dialog("Diagnostic report")

        st.markdown('<div class="timeline-label">UPCOMING</div>', unsafe_allow_html=True)
        for scheduled in DATA["diagnostic_schedule"]:
            if scheduled["status"] != "Booked":
                continue
            record_card(
                title=scheduled["test"],
                meta=f"{scheduled['date']} · {scheduled['time']} · {scheduled['location']} · {scheduled['status']}",
                key=f"diagnostic_booking_card_{scheduled['id']}",
                record_type="diagnostic_booking",
                record=scheduled,
                icon=":material/science:",
            )

        st.markdown('<div class="timeline-label">PAST RESULTS</div>', unsafe_allow_html=True)
        for report in DATA["diagnostics"]:
            record_card(
                title=report["name"],
                meta=f"{report['date']} · {report['category']} · {report['status']}",
                key=f"diagnostic_result_card_{report['id']}",
                record_type="diagnostic_result",
                record=report,
                icon=":material/lab_profile:",
            )

    with medications_tab:
        head_a, head_b = st.columns([1, 0.52])
        with head_a:
            st.caption("CURRENT → COMPLETED")
        with head_b:
            if st.button("＋ Add", key="add_medication_tab", use_container_width=True):
                add_item_dialog("Medication")
        st.markdown('<div class="timeline-label">CURRENT</div>', unsafe_allow_html=True)
        for index, medication in enumerate(DATA["medications"]):
            record_card(
                title=medication["name"],
                meta=f"{medication['instruction']} · {medication['status']}",
                key=f"medication_card_{index}",
                record_type="medication",
                record=medication,
                icon=":material/medication:",
            )

    with discharge_tab:
        head_a, head_b = st.columns([1, 0.52])
        with head_a:
            st.caption("RECENT → OLDER")
        with head_b:
            if st.button("＋ Upload", key="add_discharge_tab", use_container_width=True):
                add_item_dialog("Discharge document")
        discharge = DATA["discharge"]
        st.markdown('<div class="timeline-label">RECENT</div>', unsafe_allow_html=True)
        record_card(
            title="Surgical discharge",
            meta=f"{discharge['discharge_date']} · {discharge['consultant']} · Completed",
            key="discharge_card_primary",
            record_type="discharge",
            record=discharge,
            icon=":material/clinical_notes:",
        )
        for index, document in enumerate(st.session_state.discharge_uploads):
            record_card(
                title=document["name"],
                meta=f"{document['date']} · Awaiting review",
                key=f"discharge_upload_card_{index}",
                record_type="discharge_upload",
                record=document,
                icon=":material/description:",
            )


with right:
    st.markdown('<span class="right-panel-marker"></span>', unsafe_allow_html=True)
    panel_header("Care assistant", "")

    chat_box = st.container(border=False, key="chat_history")
    with chat_box:
        for message_index, message in enumerate(st.session_state.messages):
            avatar = PATIENT_CHAT_AVATAR if message["role"] == "user" else VESPH_CHAT_AVATAR
            with st.chat_message(message["role"], avatar=avatar):
                st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("agent"):
                st.markdown(
                    f'<div class="agent-route">{escape(message["agent"])}</div>',
                    unsafe_allow_html=True,
                )
            escalation = message.get("escalation")
            if message["role"] == "assistant" and escalation:
                if escalation.get("status") == "pending_confirmation":
                    st.markdown(
                        f'<div class="escalation-confirm"><strong>Resolution confirmation</strong>{escape(escalation["prompt"])}</div>',
                        unsafe_allow_html=True,
                    )
                    with st.container(key=f"escalation_actions_{escalation['id']}"):
                        for option_index, option in enumerate(escalation["options"]):
                            if st.button(
                                option,
                                key=f"resolve_{escalation['id']}_{option_index}",
                                use_container_width=True,
                            ):
                                confirm_escalation_resolution(message_index, option)
                                st.rerun()
                elif escalation.get("resolution"):
                    st.markdown(
                        f'<div class="escalation-resolved">Confirmed plan · {escape(escalation["resolution"])}</div>',
                        unsafe_allow_html=True,
                    )

    with st.container(key="chat_dock"):
        upload_col, form_col = st.columns([0.18, 1.18], gap="small")
        with upload_col:
            add_clicked = st.button(
                "",
                key="chat_upload_button",
                icon=":material/upload_file:",
                use_container_width=True,
                help="Upload or manually add a care record",
            )
        with form_col:
            with st.form("patient_chat_form", clear_on_submit=True):
                prompt_col, send_col = st.columns([1, 0.18], gap="small")
                with prompt_col:
                    prompt = st.text_input(
                        "Message",
                        placeholder="Ask about your care…",
                        label_visibility="collapsed",
                    )
                with send_col:
                    submitted = st.form_submit_button(
                        "",
                        key="chat_send_submit",
                        icon=":material/send:",
                        type="primary",
                        use_container_width=True,
                        help="Send message",
                    )
        if add_clicked:
            add_item_dialog("Diagnostic report")
        if submitted and prompt.strip():
            add_chat_message(prompt.strip())
            st.rerun()

        suggestions = [
            "Next appointment?",
            "Latest diagnostic?",
            "My medicines?",
            "Discharge instructions?",
        ]
        with st.container(key="suggestion_row"):
            suggestion_cols = st.columns(2, gap=None)
            for index, suggestion in enumerate(suggestions):
                with suggestion_cols[index % 2]:
                    if st.button(suggestion, key=f"suggestion_{index}", use_container_width=True):
                        add_chat_message(suggestion)
                        st.rerun()

        st.markdown(
            '<div class="safety-note"><strong>Emergency?</strong> Do not wait for chat. Call +91 22 4000 1122 or your local emergency service.</div>',
            unsafe_allow_html=True,
        )


st.markdown(
    '<div class="footer-note">Capstone prototype · Synthetic patient data · Supported open-ended questions use Groq when configured</div>',
    unsafe_allow_html=True,
)
