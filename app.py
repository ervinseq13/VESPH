from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

from tools.pdf_tools import generate_record_pdf
from tools.consultation_ingestion import (
    extract_text_from_pdf,
    parse_consultation_text,
    ingest_consultation_to_supabase,
    generate_sample_consultation_pdf,
)

from chat_service import answer_chat, is_connection_query
from integrations import IntegrationHub, IntegrationSettings
from orchestrator.graph import build_orchestrator, resolve
from tools.db_tools import (
    fetch_patient_snapshot,
    fetch_all_patients,
    fetch_all_doctors,
    fetch_doctor_snapshot,
    block_doctor_slot_in_supabase,
    unblock_doctor_slot_in_supabase,
    book_appointment_by_doctor,
    register_patient_and_book,
    update_appointment_in_supabase,
    cancel_appointment_and_escalate_in_supabase,
    toggle_prescription_taken_in_supabase,
    reset_supabase_database,
    generate_available_slots,
)


ASSET_DIR = Path(__file__).resolve().parent / "assets"
PATIENT_CHAT_AVATAR = str(ASSET_DIR / "patient-avatar.svg")
DOCTOR_CHAT_AVATAR = str(ASSET_DIR / "doctor-avatar.svg")
VESPH_CHAT_AVATAR = str(ASSET_DIR / "vesph-avatar.svg")


def short_patient_id(pid: str | None) -> str:
    """Format a clean, short, professional Patient ID for display."""
    if not pid:
        return "PID-8421"
    clean = str(pid).strip()
    if "2222" in clean:
        return "PID-8421"
    clean_no_hyphen = clean.replace("-", "").upper()
    return f"PID-{clean_no_hyphen[:5]}"


def short_doctor_id(did: str | None) -> str:
    """Format a clean, short, professional Doctor ID for display."""
    if not did:
        return "DOC-RHEA-01"
    clean = str(did).strip()
    if "1111" in clean:
        return "DOC-RHEA-01"
    clean_no_hyphen = clean.replace("-", "").upper()
    return f"DOC-{clean_no_hyphen[:5]}"


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
html, body {
  height: 100vh;
  overflow: hidden !important;
}
.stApp {
  background: var(--canvas);
  color: var(--ink);
  height: 100vh;
  overflow: hidden !important;
}
.block-container {
  max-width: 1760px;
  height: 100vh !important;
  max-height: 100vh !important;
  padding-top: 0.5rem !important;
  padding-bottom: 0.25rem !important;
  padding-left: 1.25rem !important;
  padding-right: 1.25rem !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: space-between !important;
  overflow: hidden !important;
}
[data-testid="stHeader"] {
  display: none !important;
  height: 0 !important;
}
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
.st-key-suggestion_row .stButton > button, .st-key-doc_suggestion_row .stButton > button { min-height:23px; padding:1px 3px; }
.st-key-suggestion_row .stButton > button > div, .st-key-doc_suggestion_row .stButton > button > div { width:100%; justify-content:center !important; }
.st-key-suggestion_row [data-testid="stMarkdownContainer"], .st-key-doc_suggestion_row [data-testid="stMarkdownContainer"] {
  height:100%; display:flex; align-items:center; justify-content:center;
  line-height:1 !important;
}
.st-key-suggestion_row .stButton p, .st-key-doc_suggestion_row .stButton p {
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
  [data-testid="stColumn"]:has(.left-panel-marker) {
    max-height: calc(100vh - 82px);
    overflow-y: auto;
    scrollbar-gutter: stable;
    padding-right: 4px;
  }
  [data-testid="stColumn"]:has(.middle-panel-marker) {
    max-height: calc(100vh - 82px);
    overflow-y: auto;
    scrollbar-gutter: stable;
    padding-right: 4px;
  }
  [data-testid="stColumn"]:has(.middle-panel-marker) .stTabs [role="tabpanel"] {
    height: calc(100vh - 210px);
    max-height: calc(100vh - 210px);
    min-height: 200px;
    overflow-y: auto;
    scrollbar-gutter: stable;
    padding-right: 4px;
  }
  [data-testid="stColumn"]:has(.right-panel-marker) {
    position: relative;
    max-height: calc(100vh - 82px);
  }
  .stApp .st-key-chat_history,
  .stApp .st-key-doctor_chat_history {
    height: calc(100vh - 265px) !important;
    min-height: 180px !important;
    max-height: calc(100vh - 265px) !important;
    overflow-y: auto !important;
    padding-bottom: 4px;
  }
  .st-key-chat_dock,
  .st-key-doctor_chat_dock {
    position: relative !important;
    bottom: auto !important;
    margin-top: 2px !important;
    gap: 3px !important;
  }
  .st-key-chat_dock [data-testid="stVerticalBlock"],
  .st-key-doctor_chat_dock [data-testid="stVerticalBlock"] { gap: 3px !important; }
  .st-key-chat_dock [data-testid="stForm"],
  .st-key-doctor_chat_dock [data-testid="stForm"] { margin: 0 !important; padding: 0 !important; }
  .st-key-chat_dock .safety-note,
  .st-key-doctor_chat_dock .safety-note { margin-top: 2px !important; }
  .footer-note {
    display: block;
    text-align: center;
    font-size: 9.5px;
    color: #7D8F8C;
    padding: 2px 0 1px;
    margin-top: 2px !important;
    margin-bottom: 0 !important;
    flex-shrink: 0;
  }
}

/* Tighten spacing between top bar and content grid */
.stApp [data-testid="stVerticalBlock"]:has(> [data-testid="stHorizontalBlock"]) {
  gap: 0.35rem !important;
}

/* Top bar reset button pill styling */
.st-key-top_reset_db_btn button {
  border-radius: 999px !important;
  background: #FFFFFF !important;
  border: 1px solid #94D3C5 !important;
  color: #075651 !important;
  font-weight: 700 !important;
  font-size: 11px !important;
  height: 34px !important;
  min-height: 34px !important;
  padding: 0 16px !important;
  box-shadow: 0 1px 3px rgba(23,53,50,0.06) !important;
  transition: all 0.15s ease-in-out !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
}
.st-key-top_reset_db_btn button:hover {
  background: #E6F4F1 !important;
  border-color: #075651 !important;
  color: #043834 !important;
}

/* Suppress Streamlit's "Press Enter to submit form" overlay popup in text inputs */
div[data-testid="InputInstructions"],
div[data-testid="InputInstructions"] > span,
.stTextInput [data-testid="InputInstructions"],
div[data-testid="stTextInput"] div:has(> [data-testid="InputInstructions"]) {
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
  opacity: 0 !important;
  pointer-events: none !important;
}

/* Agenda Card Click Interaction & Day Headers */
div[data-testid="stVerticalBlock"]:has(.agenda-card-wrapper) {
  position: relative !important;
  margin-bottom: 6px !important;
}
div[data-testid="stVerticalBlock"]:has(.agenda-card-wrapper) button {
  position: absolute !important;
  top: 0 !important;
  left: 0 !important;
  width: 100% !important;
  height: 100% !important;
  opacity: 0 !important;
  z-index: 10 !important;
  cursor: pointer !important;
}
div[data-testid="stVerticalBlock"]:has(.agenda-card-wrapper):hover .agenda-card {
  border-color: #0B6E69 !important;
  box-shadow: 0 4px 16px rgba(11, 110, 105, 0.14) !important;
  transform: translateY(-1px);
}
.agenda-day-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 14px 0 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #DCE7E4;
  font: 700 12px 'Manrope', sans-serif;
  color: var(--ink);
}

div[data-testid="stRadio"] {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
}
div[data-testid="stRadio"] > div {
  background: #EBF2F0;
  padding: 4px 10px;
  border-radius: 999px;
  gap: 14px;
  border: 1px solid var(--line);
}
div[data-testid="stRadio"] label {
  font-size: 11px !important;
  font-weight: 700 !important;
  cursor: pointer !important;
  color: var(--ink) !important;
  margin: 0 !important;
}

/* Doctor Portal & Meal Medication Styles */
.portal-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 8px 14px;
  margin-bottom: 10px;
  box-shadow: 0 4px 12px rgba(23,53,50,.04);
}
.doctor-header-card {
  background: linear-gradient(145deg, #1A3636 0%, #075651 100%);
  color: white;
  border-radius: 16px;
  padding: 14px;
  box-shadow: 0 8px 24px rgba(7,86,81,.18);
  margin-bottom: 10px;
}
.doctor-avatar {
  width: 44px; height: 44px; border-radius: 50%;
  background: rgba(255,255,255,.18); border: 2px solid rgba(255,255,255,.3);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 16px; color: white;
}
.agenda-card {
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-radius: 13px;
  padding: 12px 14px;
  margin-bottom: 10px;
  box-shadow: 0 2px 8px rgba(23,53,50,.03);
  transition: all .15s ease;
}
.agenda-card:hover {
  border-color: #9ABCB7;
  box-shadow: 0 4px 14px rgba(23,53,50,.07);
}
.agenda-time {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
  background: #EBF4F2;
  color: #0B6E69;
}
.rebook-notice {
  background: #FFF4E5;
  border-left: 3px solid #FF9800;
  color: #8C4B00;
  padding: 7px 10px;
  border-radius: 0 8px 8px 0;
  font-size: 10px;
  margin-top: 8px;
  line-height: 1.4;
}
.meal-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 11px;
  padding: 6px 10px;
  border-radius: 8px;
  margin: 10px 0 6px;
}
.meal-breakfast { background: #FFF7EB; color: #B25E00; border-left: 3px solid #FFA726; }
.meal-lunch { background: #EDF7F5; color: #075651; border-left: 3px solid #0B6E69; }
.meal-dinner { background: #EFF2FA; color: #283593; border-left: 3px solid #3F51B5; }
.meal-other { background: #F5F5F5; color: #424242; border-left: 3px solid #9E9E9E; }
.med-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-radius: 11px;
  padding: 9px 12px;
  margin-bottom: 6px;
}
.chart-section {
  background: #F8FAF9;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 10px;
}
.chart-title {
  font-weight: 700;
  font-size: 12px;
  color: var(--teal-dark);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: .05em;
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def get_integrations() -> IntegrationHub:
    """Create server-only clients from Streamlit secrets or local env vars."""

    return IntegrationHub(IntegrationSettings.from_sources(st.secrets))


INTEGRATIONS = get_integrations()


@st.cache_resource
def get_orchestrator():
    """Build the graph once so thread checkpoints survive Streamlit reruns."""

    return build_orchestrator()


ORCHESTRATOR = get_orchestrator()


def get_all_patients() -> list[dict]:
    try:
        return fetch_all_patients(INTEGRATIONS.supabase_client())
    except Exception:
        return []


def get_all_doctors() -> list[dict]:
    try:
        return fetch_all_doctors(INTEGRATIONS.supabase_client())
    except Exception:
        return []


def initialize_state() -> None:
    if "portal_mode" not in st.session_state:
        st.session_state.portal_mode = "patient"
    if "active_patient_id" not in st.session_state:
        st.session_state.active_patient_id = "22222222-2222-2222-2222-222222222222"
    if "active_doctor_id" not in st.session_state:
        st.session_state.active_doctor_id = "11111111-1111-1111-1111-111111111111"

    if (
        "care_data" not in st.session_state
        or st.session_state.get("_loaded_patient_id") != st.session_state.active_patient_id
    ):
        try:
            client = INTEGRATIONS.supabase_client()
            st.session_state.care_data = fetch_patient_snapshot(
                client, st.session_state.active_patient_id
            )
            st.session_state._loaded_patient_id = st.session_state.active_patient_id
        except Exception as exc:
            st.error(f"Error connecting to Supabase: {exc}")
            raise exc

    if (
        "messages" not in st.session_state
        or st.session_state.get("_chat_patient_id") != st.session_state.active_patient_id
    ):
        p_name = st.session_state.care_data.get("patient", {}).get("first_name", "there")
        meds = st.session_state.care_data.get("medications", [])
        breakfast_meds = [m["name"] for m in meds if m.get("meal_timing") == "breakfast"]
        lunch_meds = [m["name"] for m in meds if m.get("meal_timing") == "lunch"]

        intro_content = (
            f"Hi {p_name} — I have your live hospital record ready from Supabase. "
            "I can help with your recovery summary, appointments, reports, or medicines."
        )
        if breakfast_meds or lunch_meds:
            active_med = breakfast_meds[0] if breakfast_meds else lunch_meds[0]
            intro_content += (
                f"\n\n💊 **Mealtime Medication Check**: Did you take your **{active_med}** with your meal? "
                "You can tap the checkmark in the Medication tab or let me know right here!"
            )

        st.session_state.messages = [
            {
                "role": "assistant",
                "content": intro_content,
                "agent": "Patient Summary Agent · Med Reminder",
            }
        ]
        st.session_state._chat_patient_id = st.session_state.active_patient_id

    if "taken_medications" not in st.session_state:
        st.session_state.taken_medications = set()
    if "discharge_uploads" not in st.session_state:
        st.session_state.discharge_uploads = []
    if "doctor_messages" not in st.session_state:
        st.session_state.doctor_messages = [
            {
                "role": "assistant",
                "content": (
                    "**Doctor Clinical Assistant Active**\n\n"
                    "Ask me about upcoming appointments, clinic offs and blocked slots, "
                    "or your patients' clinical charts, active medications, and diagnostic records."
                ),
                "agent": "Doctor Assistant Agent",
            }
        ]



initialize_state()
DATA = st.session_state.care_data


def get_last_updated_str() -> str:
    """Retrieve timestamp of the latest field edit or appointment upload."""
    if "last_updated_time" not in st.session_state:
        st.session_state.last_updated_time = "18 Oct 2026 · 8:40 PM"
    return st.session_state.last_updated_time


def record_activity_update(action: str = "Last edit") -> None:
    """Update system timestamp whenever an appointment is added/rescheduled or a field is modified."""
    now = datetime.now()
    st.session_state.last_updated_time = now.strftime("%d %b %Y · %I:%M %p")


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
        persona="patient",
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


def format_ingestion_report(res: dict[str, Any], doc_title: str) -> str:
    """Format a comprehensive, structured clinical sync report for doctor chat."""
    md = [
        "### 📑 Consultation Ingested & Database Synchronized",
        f"**Source Document:** {doc_title}  ",
        f"**Target Patient:** {escape(str(res['patient_name']))} (`{short_patient_id(res['patient_id'])}`)  ",
        f"**Primary Diagnosis:** {escape(str(res['diagnosis']))}  ",
        "",
        "#### 🔄 Live Supabase Updates Applied:",
        f"- ✅ **Patient Summary Field Updated:** \"{escape(str(res['new_summary']))}\"",
        f"- ✅ **New Consultation Record Logged:** ID `{str(res['consultation_id'])[:8]}...`",
    ]
    if res.get("appointments_created"):
        md.append(f"- ✅ **Follow-up Appointments Scheduled ({len(res['appointments_created'])}):**")
        for a in res["appointments_created"]:
            md.append(f"  - 📅 **{a['date']} at {a['time']}** ({a['type']}) · {escape(str(a['summary']))}")
    if res.get("medications_added"):
        md.append(f"- ✅ **Prescriptions Scheduled by Mealtime ({len(res['medications_added'])}):**")
        for m in res["medications_added"]:
            meal_icon = "🍳" if m["meal_timing"] == "breakfast" else ("🥗" if m["meal_timing"] == "lunch" else "🍲")
            md.append(f"  - {meal_icon} **{m['meal_timing'].title()}:** {escape(str(m['name']))} {escape(str(m['dosage']))} · {escape(str(m['instructions']))} ({m['duration_days']} days)")
    if res.get("diagnostics_ordered"):
        md.append(f"- ✅ **Diagnostics Ordered ({len(res['diagnostics_ordered'])}):**")
        for d in res["diagnostics_ordered"]:
            md.append(f"  - 🔬 **{escape(str(d['name']))}** ({escape(str(d['category']))}) · {escape(str(d.get('summary', '')))}")

    md.append("")
    md.append("> 💡 *Switch to **👤 Patient View** above to inspect Ananya's live updated summary, newly scheduled mealtime medications, and confirmed follow-up visit.*")
    return "\n".join(md)


def handle_consultation_pdf_ingestion(pdf_bytes: bytes, file_name: str = "Uploaded Consultation Note") -> None:
    """Process consultation PDF bytes, extract clinical text, parse, and sync to Supabase."""
    client = INTEGRATIONS.supabase_client()
    text = extract_text_from_pdf(pdf_bytes)
    groq_c = INTEGRATIONS._groq_client() if INTEGRATIONS.groq_configured else None
    parsed = parse_consultation_text(text, groq_client=groq_c)
    res = ingest_consultation_to_supabase(
        client,
        parsed,
        doctor_id=st.session_state.active_doctor_id,
        default_patient_id=st.session_state.active_patient_id,
    )
    report_md = format_ingestion_report(res, file_name)
    st.session_state.doctor_messages.append({
        "role": "user",
        "content": f"Ingest consultation document: **{file_name}**",
    })
    st.session_state.doctor_messages.append({
        "role": "assistant",
        "content": report_md,
        "agent": "Clinical Ingestion & RAG Agent",
    })
    st.session_state._patient_data_id = None
    st.session_state._doctor_data_id = None
    st.session_state._loaded_patient_id = None
    record_activity_update("Consultation PDF ingested and synced to database")
    st.session_state["doctor_toast"] = ("Consultation note ingested and synced to Supabase!", "✅")


def add_doctor_chat_message(prompt: str, doc_snapshot: dict[str, Any]) -> None:
    """Process doctor queries or raw consultation notes in the doctor panel."""
    st.session_state.doctor_messages.append({"role": "user", "content": prompt})
    lowered = prompt.lower()
    clinical_keywords = ["diagnosis", "consultation", "patient:", "vitals", "rx:", "prescribe", "follow-up", "bp:"]
    matched_count = sum(1 for kw in clinical_keywords if kw in lowered)

    if matched_count >= 2 or ("patient" in lowered and ("rx" in lowered or "prescribe" in lowered or "follow-up" in lowered)):
        client = INTEGRATIONS.supabase_client()
        groq_c = INTEGRATIONS._groq_client() if INTEGRATIONS.groq_configured else None
        parsed = parse_consultation_text(prompt, groq_client=groq_c)
        res = ingest_consultation_to_supabase(
            client,
            parsed,
            doctor_id=st.session_state.active_doctor_id,
            default_patient_id=st.session_state.active_patient_id,
        )
        report_md = format_ingestion_report(res, "Clinical Consultation Note")
        st.session_state.doctor_messages.append({
            "role": "assistant",
            "content": report_md,
            "agent": "Clinical Ingestion & RAG Agent",
        })
        st.session_state._patient_data_id = None
        st.session_state._doctor_data_id = None
        st.session_state._loaded_patient_id = None
        record_activity_update("Consultation note ingested and synced to database")
        st.session_state["doctor_toast"] = ("Consultation note ingested and synced to Supabase!", "✅")
        return

    if is_connection_query(prompt):
        st.session_state.doctor_messages.append({
            "role": "assistant",
            "content": INTEGRATIONS.status_message(),
            "agent": "System · Connection check",
        })
        return

    doc_care_data = {
        "doctor": doc_snapshot.get("doctor", {}),
        "appointments": doc_snapshot.get("today_appointments", []) + doc_snapshot.get("week_appointments", []),
        "stats": doc_snapshot.get("stats", {}),
        "unavailability": doc_snapshot.get("unavailability", []),
        "patient": DATA.get("patient", {}),
        "medications": DATA.get("medications", []),
        "diagnostics": DATA.get("diagnostics", []),
        "discharge": DATA.get("discharge", {}),
    }

    reply = INTEGRATIONS.answer_with_groq(
        prompt,
        doc_care_data,
        recent_messages=st.session_state.doctor_messages[:-1],
        persona="doctor",
    )
    if not reply:
        doc_name = doc_snapshot.get("doctor", {}).get("name", "Dr. Rhea Mehta")
        today_cnt = len(doc_snapshot.get("today_appointments", []))
        week_cnt = len(doc_snapshot.get("week_appointments", []))
        reply = (
            f"**Clinical Status Overview for {escape(doc_name)}:**\n\n"
            f"• **Today's OPD Consultations:** {today_cnt} patients scheduled\n"
            f"• **Weekly Workload:** {week_cnt} appointments on agenda (18–24 Oct 2026)\n"
            "You can ask about upcoming appointments, clinic offs and blocked slots, or your patients' clinical charts and medications."
        )

    st.session_state.doctor_messages.append({
        "role": "assistant",
        "content": reply,
        "agent": f"Groq Clinical Assistant · {INTEGRATIONS.settings.groq_model}" if INTEGRATIONS.groq_configured else "Clinical Assistant",
    })



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


@st.dialog("Reschedule appointment")
def reschedule_dialog(appointment_index: int = 0) -> None:
    appointment = DATA["appointments"][appointment_index] if DATA["appointments"] else None
    if not appointment:
        st.warning("No appointment found to reschedule.")
        return

    st.markdown(
        f"**Current:** {appointment['type']} with **{appointment['doctor']}**  \n"
        f"📅 {appointment['date']} · 🕒 {appointment['time']}"
    )
    st.info("⚡ Available timeslots are auto-accepted and confirmed immediately without waiting for hospital approval.")

    target_doctor = appointment.get("doctor")
    doc_options = [row for row in DATA["appointment_schedule"] if row["doctor"] == target_doctor]
    options = doc_options if doc_options else DATA["appointment_schedule"]

    labels = [f"{row['date']} · {row['doctor']} ({row.get('department', 'General Surgery')})" for row in options]
    selected_label = st.selectbox("Choose date & doctor", labels)
    selected = options[labels.index(selected_label)]

    available_slots = selected.get("slots", [])
    if not available_slots:
        st.warning("No timeslots currently open for this date. Please choose another date.")
        return

    time = st.selectbox("Available timeslot", available_slots)
    note = st.text_input("Anything the care team should know? (Optional)", placeholder="e.g. Prefer morning slot")

    if st.button("Confirm & Reschedule", type="primary", use_container_width=True):
        record_activity_update("Rescheduled appointment")
        is_available = bool(time and time in available_slots)
        if is_available:
            appointment.update(
                {
                    "date": selected["date"],
                    "time": time,
                    "doctor": selected["doctor"],
                    "status": "Confirmed",
                    "request_note": note if note else None,
                }
            )
            # Slot is consumed so it cannot be double-booked
            if time in selected.get("slots", []):
                selected["slots"].remove(time)

            try:
                update_appointment_in_supabase(
                    INTEGRATIONS.supabase_client(),
                    appointment["id"],
                    "Confirmed",
                    new_date=selected["date"],
                    new_time=time,
                )
            except Exception:
                pass

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"Your appointment with {selected['doctor']} has been rescheduled and automatically confirmed "
                        f"for {selected['date']} at {time}. No further hospital confirmation is needed."
                    ),
                    "agent": "Reminder Agent · Scheduling",
                }
            )
            st.toast(f"Appointment rescheduled & confirmed for {selected['date']} at {time}!", icon="✅")
        else:
            appointment.update(
                {
                    "date": selected["date"],
                    "time": time,
                    "doctor": selected["doctor"],
                    "status": "Reschedule requested",
                    "request_note": note,
                }
            )
            try:
                update_appointment_in_supabase(
                    INTEGRATIONS.supabase_client(),
                    appointment["id"],
                    "Rescheduled",
                    new_date=selected["date"],
                    new_time=time,
                )
            except Exception:
                pass

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"Your preferred time, {selected['date']} at {time}, has been sent to the scheduling desk. "
                        "The existing appointment stays active until the hospital confirms the change."
                    ),
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
            record_activity_update("New appointment request")
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
            record_activity_update("Diagnostic report upload")
            DATA["diagnostics"].insert(
                0,
                {
                    "id": f"UPL-{len(DATA['diagnostics']) + 1}",
                    "date": "18 Oct 2026",
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
            record_activity_update("Medication added")
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
            record_activity_update("Discharge document upload")
            st.session_state.discharge_uploads.insert(
                0,
                {
                    "name": uploaded.name if uploaded else "Discharge document",
                    "date": "18 Oct 2026",
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
              <div class="detail-cell"><strong>Patient ID</strong>{escape(short_patient_id(DATA['patient']['id']))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if record.get("preparation"):
            st.info(record["preparation"])
        if record.get("status") != "Confirmed":
            col_cf, col_rs = st.columns(2)
            with col_cf:
                if st.button("✓ Confirm Attendance", key=f"dlg_cf_{record['id']}", type="primary", use_container_width=True):
                    record["status"] = "Confirmed"
                    try:
                        update_appointment_in_supabase(INTEGRATIONS.supabase_client(), record["id"], "Confirmed")
                    except Exception:
                        pass
                    record_activity_update("Confirmed appointment attendance")
                    st.toast("Appointment attendance confirmed!", icon="✅")
                    st.rerun()
            with col_rs:
                if st.button("Reschedule", key=f"dlg_rs_{record['id']}", use_container_width=True):
                    reschedule_dialog()
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
              <div class="detail-cell"><strong>Patient ID</strong>{escape(short_patient_id(DATA['patient']['id']))}</div>
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

    pdf_filename = filename.rsplit(".", 1)[0] + ".pdf"
    try:
        pdf_data = generate_record_pdf(record, record_type, DATA["patient"]["name"])
        st.download_button(
            "Download PDF",
            data=pdf_data,
            file_name=pdf_filename,
            mime="application/pdf",
            icon=":material/download:",
            use_container_width=True,
        )
    except Exception:
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


@st.dialog("Mark Doctor Unavailability / Block Schedule")
def doctor_unavailability_dialog(doctor_id: str, doctor_name: str) -> None:
    st.markdown(f"**Doctor:** {doctor_name}")
    st.caption("Blocking a day or timeslot marks you unavailable to patients and automatically reschedules conflicting patient appointments to your next available slot.")

    date_options = ["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"]
    col_d, col_s = st.columns(2)
    with col_d:
        block_date = st.selectbox("Date to block", date_options)
    with col_s:
        block_scope = st.radio("Block duration", ["Full Day", "Specific Timeslot"], horizontal=True)

    blocked_slot = None
    if block_scope == "Specific Timeslot":
        blocked_slot = st.selectbox("Select timeslot", ["09:00 AM", "10:30 AM", "11:30 AM", "02:00 PM", "03:00 PM", "04:30 PM"])

    reason = st.text_input("Reason for unavailability", placeholder="e.g. Emergency Laparotomy in OT / Medical Symposium")

    st.info("ℹ️ Existing appointments on this date/slot will receive an automated notice and be auto-rebooked to the next open OPD slot.")

    if st.button("⛔ Confirm Unavailability Block", type="primary", use_container_width=True):
        if not reason.strip():
            reason = "Doctor unavailable / Urgent duty"
        client = INTEGRATIONS.supabase_client()
        with st.spinner("Blocking slot and checking conflicting appointments..."):
            record_activity_update("Doctor availability blocked")
            rebooked = block_doctor_slot_in_supabase(
                client=client,
                doctor_id=doctor_id,
                blocked_date=block_date,
                blocked_slot=blocked_slot if block_scope == "Specific Timeslot" else None,
                reason=reason.strip(),
            )
            st.session_state._doctor_data_id = None
            if rebooked:
                msg = f"Slot blocked! {len(rebooked)} conflicting patient appointment(s) were auto-rebooked to open fallback slots."
                st.session_state["doctor_toast"] = (msg, "⚠️")
            else:
                st.session_state["doctor_toast"] = ("Schedule blocked successfully. No patient conflicts found.", "✅")
            st.rerun()


@st.dialog("Schedule Patient Appointment")
def doctor_book_appointment_dialog(doctor_id: str, default_patient_id: str | None = None) -> None:
    patients = get_all_patients()
    patient_choice = st.radio("Patient Type", ["Existing Patient", "New Patient"], horizontal=True)

    target_patient_id = None
    new_patient_info = {}

    if patient_choice == "Existing Patient":
        patient_options = {p["id"]: f"{p['name']} ({short_patient_id(p['id'])}, {p.get('gender', '')}, {p.get('age', '')}y) · {p.get('phone', '')}" for p in patients}
        default_index = 0
        if default_patient_id and default_patient_id in patient_options:
            default_index = list(patient_options.keys()).index(default_patient_id)
        selected_pid = st.selectbox("Select Patient", list(patient_options.keys()), format_func=lambda pid: patient_options[pid], index=default_index)
        target_patient_id = selected_pid
    else:
        c1, c2 = st.columns(2)
        with c1:
            first_name = st.text_input("First Name", placeholder="e.g. Meera")
            age = st.number_input("Age", min_value=1, max_value=120, value=30)
            phone = st.text_input("Phone", placeholder="+91 98200 12345")
        with c2:
            last_name = st.text_input("Last Name", placeholder="e.g. Joshi")
            gender = st.selectbox("Gender", ["Female", "Male", "Other"])
            email = st.text_input("Email", placeholder="meera.joshi@example.com")
        medical_summary = st.text_area("Initial Clinical Notes / Medical History", placeholder="Brief health notes or history", height=68)
        new_patient_info = {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "age": age,
            "gender": gender,
            "phone": phone.strip(),
            "email": email.strip(),
            "medical_summary": medical_summary.strip(),
        }

    c_date, c_time = st.columns(2)
    with c_date:
        appt_date = st.selectbox("Appointment Date", ["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"])
    with c_time:
        client = INTEGRATIONS.supabase_client()
        available_cadence_slots = generate_available_slots(client, doctor_id, appt_date)
        if not available_cadence_slots:
            available_cadence_slots = ["09:00 AM", "09:20 AM", "10:00 AM", "11:20 AM", "02:00 PM", "03:20 PM", "04:00 PM"]
        appt_slot = st.selectbox("Timeslot (15m + 5m buffer)", available_cadence_slots)

    c_type, c_loc = st.columns(2)
    with c_type:
        appt_type = st.selectbox("Type", ["Consultation", "FollowUp", "Diagnostic"])
    with c_loc:
        location = st.text_input("Location", value="OPD Wing B, Room 304")

    summary_note = st.text_input("Visit Summary / Clinical Objective", placeholder="e.g. Post-operative wound assessment and stitch review")

    if st.button("Confirm Appointment Booking", type="primary", use_container_width=True):
        client = INTEGRATIONS.supabase_client()
        with st.spinner("Booking appointment in Supabase..."):
            record_activity_update("Doctor appointment booking")
            if patient_choice == "Existing Patient":
                book_appointment_by_doctor(
                    client=client,
                    doctor_id=doctor_id,
                    patient_id=target_patient_id,
                    appt_date=appt_date,
                    appt_slot=appt_slot,
                    appt_type=appt_type,
                    location=location,
                    summary=summary_note.strip() or f"{appt_type} scheduled by doctor",
                )
            else:
                if not new_patient_info["first_name"]:
                    st.error("Please enter the patient's first name.")
                    return
                register_patient_and_book(
                    client=client,
                    doctor_id=doctor_id,
                    first_name=new_patient_info["first_name"],
                    last_name=new_patient_info["last_name"] or "Patient",
                    age=new_patient_info["age"],
                    gender=new_patient_info["gender"],
                    phone=new_patient_info["phone"] or "+91 98000 00000",
                    email=new_patient_info["email"] or "patient@vesphcare.com",
                    appt_date=appt_date,
                    appt_slot=appt_slot,
                    appt_type=appt_type,
                    location=location,
                    summary=summary_note.strip() or "Initial consultation scheduled by doctor",
                    medical_summary=new_patient_info["medical_summary"] or "No known chronic conditions.",
                )
            st.session_state._doctor_data_id = None
            st.session_state["doctor_toast"] = (f"Appointment booked for {appt_date} at {appt_slot}!", "✅")
            st.rerun()


@st.dialog("Patient Clinical Chart", width="large")
def patient_clinical_chart_dialog(patient_id: str, appointment_data: dict | None = None) -> None:
    client = INTEGRATIONS.supabase_client()
    try:
        p_snap = fetch_patient_snapshot(client, patient_id)
    except Exception as exc:
        st.error(f"Error loading patient data: {exc}")
        return

    p = p_snap["patient"]
    st.subheader(f"🩺 {p['name']} · Clinical Profile")
    st.caption(f"Patient ID: {short_patient_id(p['id'])} · Age: {p['age']}y · Sex: {p['gender']} · Blood: {p['blood_group']} · Phone: {p['phone']}")

    # Health & Vitals
    v1, v2, v3, v4 = st.columns(4)
    v1.metric("BP Systolic", f"{p.get('vitals', {}).get('systolic', 120)} mmHg")
    v2.metric("BP Diastolic", f"{p.get('vitals', {}).get('diastolic', 80)} mmHg")
    v3.metric("Blood Sugar", f"{p.get('vitals', {}).get('sugar', 95)} mg/dL")
    v4.metric("BMI", f"{p.get('vitals', {}).get('bmi', 21.5)} kg/m²")

    st.markdown(
        f"""
        <div class="chart-section" style="margin-bottom:12px;">
          <div class="chart-title">Clinical & Diagnosis Summary</div>
          <div style="font-size:12px; color:var(--ink); line-height:1.45;">{escape(p.get('health_summary', 'Normal recovery'))}</div>
          <div style="margin-top:6px; font-size:11px; color:var(--muted);"><strong>Known Allergies:</strong> {escape(', '.join(p.get('allergies', ['None'])))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_consults, tab_labs, tab_surg, tab_meds = st.tabs([
        "📋 Consultations & Visits",
        "🔬 Diagnostic Labs & Reports",
        "🏥 Surgical & Hospital History",
        "💊 Active Prescriptions & Vitals",
    ])

    with tab_consults:
        st.markdown('<div class="timeline-label">PREVIOUS CLINICAL CONSULTATIONS</div>', unsafe_allow_html=True)
        consults = p_snap.get("consultations", [])
        if not consults:
            st.caption("No previous recorded clinical consultations.")
        else:
            for c in consults:
                st.markdown(
                    f"""
                    <div style="background:white; border:1px solid var(--line); border-radius:10px; padding:10px; margin-bottom:8px;">
                      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                          <strong style="font-size:12px; color:var(--ink);">{escape(c.get('diagnosis') or 'Clinical Consultation')}</strong>
                          <div style="font-size:10px; color:var(--muted); margin-top:2px;">Doctor: {escape(c.get('doctor', 'Dr. Rhea Mehta'))} · {escape(c.get('department', 'OPD'))} · Date: {escape(c.get('date', ''))}</div>
                        </div>
                        <span class="micro-pill" style="font-weight:700;">Consultation</span>
                      </div>
                      <div style="font-size:11px; color:#2E4744; margin-top:6px; line-height:1.45;">
                        <strong>Symptoms:</strong> {escape(c.get('symptoms') or 'N/A')}<br>
                        <strong>Treatment Plan:</strong> {escape(c.get('treatment_plan') or 'N/A')}<br>
                        <strong>Summary:</strong> {escape(c.get('summary') or 'Routine review')}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="timeline-label">INDIVIDUAL APPOINTMENTS BREAKDOWN (WHAT HAPPENED DURING VISIT)</div>', unsafe_allow_html=True)
        patient_appts = p_snap.get("appointments", [])
        if not patient_appts:
            st.caption("No appointments recorded for this patient.")
        else:
            for appt in patient_appts:
                status_class = "status" if appt.get("status") == "Confirmed" else ("status old" if appt.get("status") == "Completed" else "status wait")
                notes = appt.get("preparation") or appt.get("summary") or "General clinical follow-up and patient evaluation."
                st.markdown(
                    f"""
                    <div style="background:#FAFDFC; border:1px solid #D6E7E3; border-radius:10px; padding:10px; margin-bottom:8px;">
                      <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                          <strong style="font-size:12px; color:var(--ink);">📅 {escape(appt.get('date', ''))} at {escape(appt.get('time', ''))}</strong>
                          <span style="font-size:10px; color:var(--muted); margin-left:6px;">· {escape(appt.get('type', 'Consultation'))}</span>
                        </div>
                        <span class="{status_class}">{escape(appt.get('status', 'Confirmed'))}</span>
                      </div>
                      <div style="font-size:11px; color:#3F5D58; margin-top:5px;">
                        <strong>Attending Doctor:</strong> {escape(appt.get('doctor', 'Dr. Rhea Mehta'))} ({escape(appt.get('department', 'OPD'))}) · <strong>Location:</strong> {escape(appt.get('location', 'OPD Room 304'))}
                      </div>
                      <div style="font-size:11px; color:var(--ink); margin-top:4px; line-height:1.4;">
                        <strong>What happened / Visit Notes:</strong> {escape(notes)}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with tab_labs:
        st.markdown('<div class="timeline-label">DIAGNOSTIC TEST RESULTS & LAB SUMMARIES</div>', unsafe_allow_html=True)
        labs = p_snap.get("diagnostics", [])
        if not labs:
            st.caption("No diagnostic reports on record.")
        else:
            for lab in labs:
                flag = lab.get("flag", "Normal")
                st.markdown(
                    f"""
                    <div style="background:white; border:1px solid var(--line); border-radius:10px; padding:10px; margin-bottom:8px;">
                      <div style="display:flex; justify-content:space-between;">
                        <strong style="font-size:12px; color:var(--ink);">{escape(lab['name'])}</strong>
                        <span class="status">{escape(lab.get('category', 'Lab'))}</span>
                      </div>
                      <div style="font-size:11px; color:#3F5D58; margin-top:4px;"><strong>Result:</strong> {escape(lab.get('result_value') or lab.get('summary', ''))}</div>
                      <div style="font-size:10px; color:var(--muted); margin-top:3px;">Reference Range: {escape(lab.get('reference_range', 'Normal'))} · Flag: {escape(flag)} · Date: {escape(lab.get('date', ''))}</div>
                      <div style="font-size:11px; color:var(--ink); margin-top:4px;"><strong>Summary:</strong> {escape(lab.get('summary', ''))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        diag_appts = [a for a in p_snap.get("appointments", []) if "diag" in a.get("type", "").lower() or "lab" in a.get("type", "").lower() or "test" in a.get("type", "").lower()]
        if diag_appts:
            st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
            st.markdown('<div class="timeline-label">ASSOCIATED DIAGNOSTIC APPOINTMENTS</div>', unsafe_allow_html=True)
            for da in diag_appts:
                st.markdown(
                    f"""
                    <div style="background:#F6FAF9; border:1px solid #D1E5E2; border-radius:8px; padding:8px 10px; margin-bottom:6px; font-size:11px;">
                      <strong>{escape(da.get('date', ''))} at {escape(da.get('time', ''))}</strong> · {escape(da.get('type', ''))} ({escape(da.get('status', ''))})
                      <div style="font-size:10px; color:var(--muted); margin-top:2px;">Location: {escape(da.get('location', 'Hospital Lab'))} · Notes: {escape(da.get('preparation', ''))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with tab_surg:
        st.markdown('<div class="timeline-label">SURGICAL PROCEDURE & DISCHARGE SUMMARY</div>', unsafe_allow_html=True)
        discharge = p_snap.get("discharge", {})
        if discharge and discharge.get("procedure"):
            st.markdown(
                f"""
                <div style="background:white; border:1px solid var(--line); border-radius:10px; padding:12px; margin-bottom:10px;">
                  <strong style="font-size:13px; color:var(--ink);">{escape(discharge.get('procedure', 'Surgical procedure'))}</strong>
                  <div style="font-size:11px; color:var(--muted); margin-top:3px;">
                    Date of Discharge: {escape(discharge.get('discharge_date', ''))} · Lead Consultant: {escape(discharge.get('consultant', 'Dr. Rhea Mehta'))} ({escape(discharge.get('department', 'General Surgery'))})
                  </div>
                  <div style="font-size:11px; color:#2E4744; margin-top:8px; line-height:1.45;">
                    <strong>Condition at Discharge:</strong> {escape(discharge.get('condition_at_discharge', 'Stable recovery'))}
                  </div>
                  <div style="font-size:11px; color:#2E4744; margin-top:6px; line-height:1.45;">
                    <strong>Recommended Follow-up:</strong> {escape(discharge.get('follow_up', 'Surgical OPD review'))}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            instructions = discharge.get("instructions", [])
            if instructions:
                st.markdown('<div class="timeline-label">POST-OPERATIVE RECOVERY INSTRUCTIONS</div>', unsafe_allow_html=True)
                for inst in instructions:
                    st.markdown(f"• <span style='font-size:11px; color:var(--ink);'>{escape(inst)}</span>", unsafe_allow_html=True)
        else:
            st.caption("No surgical procedure recorded for this patient.")

    with tab_meds:
        st.markdown('<div class="timeline-label">ACTIVE MEDICATIONS & MEAL TIMINGS</div>', unsafe_allow_html=True)
        meds = p_snap.get("medications", [])
        if not meds:
            st.caption("No active medications prescribed.")
        else:
            for m in meds:
                meal_tag = m.get("meal_timing", "general").capitalize()
                taken_str = "✓ Taken" if m.get("is_taken") else "○ Pending"
                st.markdown(
                    f"""
                    <div class="med-row">
                      <div>
                        <strong style="font-size:12px; color:var(--ink);">{escape(m['name'])}</strong>
                        <div style="font-size:10px; color:var(--muted);">{escape(m.get('instruction', ''))} · {escape(m.get('duration', ''))}</div>
                      </div>
                      <div style="text-align:right;">
                        <span class="micro-pill" style="background:#EBF5F3; color:#0B6E69; font-weight:700;">{meal_tag}</span>
                        <span class="micro-pill" style="margin-left:4px;">{taken_str}</span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Bottom Actions Bar
    st.markdown("<div style='height:14px; border-top:1px solid #E0EAE8; margin-top:14px;'></div>", unsafe_allow_html=True)

    target_appt = appointment_data
    if not target_appt:
        upcoming_list = [a for a in p_snap.get("appointments", []) if a.get("status") not in ("Completed", "Cancelled", "Doctor Unavailable (Reschedule Required)")]
        if upcoming_list:
            target_appt = upcoming_list[0]

    if target_appt:
        t_date = target_appt.get("date", "")
        t_time = target_appt.get("time", "")
        t_type = target_appt.get("type", "Appointment")
        st.markdown(
            f"""
            <div style="background:#F2F8F7; border:1px solid #CBE2DD; border-radius:8px; padding:6px 12px; margin-bottom:10px; font-size:11px; color:#0B6E69;">
              <strong>Active Appointment:</strong> {escape(t_date)} at {escape(t_time)} · {escape(t_type)}
            </div>
            """,
            unsafe_allow_html=True,
        )

    act_col1, act_col2 = st.columns(2, gap="medium")
    with act_col1:
        if st.button("＋ Book Follow-up Appointment", type="primary", use_container_width=True, key=f"chart_book_fu_{patient_id}"):
            doctor_book_appointment_dialog(st.session_state.active_doctor_id, default_patient_id=patient_id)

    with act_col2:
        if target_appt:
            if st.button(
                "⛔ Cancel Appointment (Doctor Unavailable)",
                type="secondary",
                use_container_width=True,
                key=f"chart_cancel_btn_{patient_id}_{target_appt.get('id')}",
                help="Doctor is unavailable: cancels appointment and creates an escalation for the patient to rebook",
            ):
                with st.spinner("Cancelling appointment and dispatching escalation to patient..."):
                    client = INTEGRATIONS.supabase_client()
                    doc_s = fetch_doctor_snapshot(client, st.session_state.active_doctor_id)
                    d_name = doc_s.get("doctor", {}).get("name", "Dr. Rhea Mehta")
                    cancel_appointment_and_escalate_in_supabase(
                        client=client,
                        appointment_id=str(target_appt.get("id")),
                        patient_id=patient_id,
                        reason="Doctor unavailable for scheduled OPD slot",
                        doctor_name=d_name,
                    )
                    st.session_state._doctor_data_id = None
                    st.session_state._patient_data_id = None
                    record_activity_update(f"Appointment for {p['name']} on {target_appt.get('date')} cancelled due to doctor unavailability. Rebooking escalation dispatched.")
                    st.session_state["doctor_toast"] = (f"Appointment cancelled. An escalation notice was dispatched to {p['name']} to rebook!", "⚠️")
                    st.rerun()
        else:
            st.button("⛔ Cancel Appointment", disabled=True, use_container_width=True, help="No active upcoming appointment to cancel for this patient")


def render_patient_portal() -> None:
    patient = DATA["patient"]
    left, middle, right = st.columns([1, 1.8, 0.92], gap="medium")

    with left:
        st.markdown('<span class="left-panel-marker"></span>', unsafe_allow_html=True)
        panel_header("Patient overview", "", f"Updated {get_last_updated_str()}")
        st.markdown(
            f"""
            <div class="patient-card">
              <div class="patient-head">
                <div class="avatar">{escape(patient['initials'])}</div>
                <div><div class="patient-name">{escape(patient['name'])}</div><div class="patient-id">Patient ID · {escape(short_patient_id(patient['id']))}</div></div>
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
        # Find unconfirmed upcoming appointments that require patient action
        unconfirmed_appts = [
            a for a in DATA.get("appointments", [])
            if a.get("status") not in ("Confirmed", "Completed", "Cancelled")
        ]

        show_cbc = not st.session_state.get("cbc_done", False)
        show_insurance = not st.session_state.get("insurance_done", False)

        meds_list = DATA.get("medications", [])
        untaken_b = [m for m in meds_list if m.get("meal_timing") == "breakfast" and not m.get("is_taken")]
        untaken_l = [m for m in meds_list if m.get("meal_timing") == "lunch" and not m.get("is_taken")]
        untaken_d = [m for m in meds_list if m.get("meal_timing") == "dinner" and not m.get("is_taken")]

        if untaken_b:
            active_meal = "Breakfast"
            active_meds = untaken_b
        elif untaken_l:
            active_meal = "Lunch"
            active_meds = untaken_l
        elif untaken_d:
            active_meal = "Dinner"
            active_meds = untaken_d
        else:
            active_meal = "Daily Routine"
            active_meds = []

        show_med_check = bool(active_meds)
        has_actionable_items = bool(unconfirmed_appts or show_cbc or show_insurance or show_med_check)

        reminder_strip = st.container(
            horizontal=True,
            wrap=False,
            horizontal_alignment="left",
            gap="small",
            key="reminder_carousel",
        )

        if not has_actionable_items:
            with reminder_strip.container(border=True, width=420):
                st.markdown(
                    """
                    <div class="reminder-card secondary" style="display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center; padding:16px 14px;">
                      <div style="font-size:24px;">🎉</div>
                      <div style="font:700 13px/1.2 'Manrope',sans-serif; color:var(--teal-dark); margin-top:5px;">Notification Centre · All Caught Up!</div>
                      <div style="font-size:10px; color:var(--muted); margin-top:3px;">All appointments confirmed and tasks completed. No pending action needed.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            # 1. Unconfirmed Appointments (Pending action: Confirm attendance or reschedule)
            if unconfirmed_appts:
                target_appt = unconfirmed_appts[0]
                with reminder_strip.container(border=True, width=340):
                    st.markdown(
                        f"""
                        <div class="reminder-card primary">
                          <div class="reminder-top">
                            <div class="reminder-kicker">Appointment · Action Needed</div>
                            <div class="reminder-time">In 2 days</div>
                          </div>
                          <div class="reminder-title">{escape(target_appt['type'])}</div>
                          <div class="reminder-detail">{escape(target_appt['doctor'])} · {escape(target_appt['date'])}<br>{escape(target_appt['time'])} · {escape(target_appt['location'])}</div>
                          <div class="reminder-meta">Attendance pending confirmation · Bring reports</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    action_a, action_b = st.columns(2, gap="small")
                    with action_a:
                        if st.button("✓ Confirm", type="primary", key="confirm_reminder", use_container_width=True):
                            target_appt["status"] = "Confirmed"
                            try:
                                update_appointment_in_supabase(
                                    INTEGRATIONS.supabase_client(),
                                    target_appt["id"],
                                    "Confirmed",
                                )
                            except Exception:
                                pass
                            record_activity_update("Confirmed appointment attendance")
                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "content": f"Your {target_appt['type']} on {target_appt['date']} at {target_appt['time']} with {target_appt['doctor']} has been confirmed! It has been moved to your confirmed schedule and marked done in your notification centre.",
                                    "agent": "Reminder Agent · Appointments",
                                }
                            )
                            st.toast("Appointment attendance confirmed & marked done!", icon="✅")
                            st.rerun()
                    with action_b:
                        if st.button("Reschedule", key="reschedule_reminder", use_container_width=True):
                            reschedule_dialog()

            # 2. Diagnostic Reminder
            if show_cbc:
                with reminder_strip.container(border=True, width=340):
                    st.markdown(
                        """
                        <div class="reminder-card secondary">
                          <div class="reminder-top"><div class="reminder-kicker">Diagnostic · Test Needed</div><div class="reminder-time">In 2 days</div></div>
                          <div class="reminder-title">Complete Blood Count</div>
                          <div class="reminder-detail">20 Oct · 9:00 AM<br>Ground floor · No fasting</div>
                          <div class="reminder-meta">Reminder 1 of 2</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    c_a, c_b = st.columns(2, gap="small")
                    with c_a:
                        if st.button("View booking", icon=":material/visibility:", key="view_cbc_reminder", use_container_width=True):
                            record_detail_dialog("diagnostic_booking", DATA["diagnostic_schedule"][0])
                    with c_b:
                        if st.button("✓ Mark Done", key="btn_done_cbc", use_container_width=True):
                            st.session_state.cbc_done = True
                            st.toast("Diagnostic reminder marked as done!", icon="✅")
                            st.rerun()

            # 3. Document Upload Reminder
            if show_insurance:
                with reminder_strip.container(border=True, width=340):
                    st.markdown(
                        """
                        <div class="reminder-card secondary">
                          <div class="reminder-top"><div class="reminder-kicker">Document · Pending</div><div class="reminder-time">Due 24 Oct</div></div>
                          <div class="reminder-title">Insurance claim form</div>
                          <div class="reminder-detail">Signed copy required<br>1 document pending</div>
                          <div class="reminder-meta">Upload by 24 Oct · Reminder 1 of 2</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    i_a, i_b = st.columns(2, gap="small")
                    with i_a:
                        if st.button("Upload", icon=":material/upload_file:", key="insurance_upload", use_container_width=True):
                            add_item_dialog("Discharge document")
                    with i_b:
                        if st.button("✓ Mark Done", key="btn_done_insurance", use_container_width=True):
                            st.session_state.insurance_done = True
                            st.toast("Insurance requirement marked done!", icon="✅")
                            st.rerun()

            # 4. Proactive Meal Medication Check Card
            if show_med_check:
                with reminder_strip.container(border=True, width=340):
                    med_names_str = ", ".join(m["name"] for m in active_meds)
                    st.markdown(
                        f"""
                        <div class="reminder-card secondary">
                          <div class="reminder-top"><div class="reminder-kicker">Medication · {active_meal}</div><div class="reminder-time">Daily</div></div>
                          <div class="reminder-title">{active_meal} Meds Check</div>
                          <div class="reminder-detail">{escape(med_names_str)}<br>Take as instructed with meal</div>
                          <div class="reminder-meta">Tap below to mark taken or confirm in chat</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button(f"✓ Mark {active_meal} Meds Taken", type="primary", key="quick_mark_meal_taken", use_container_width=True):
                        record_activity_update("Meal medication taken")
                        client = INTEGRATIONS.supabase_client()
                        for m in active_meds:
                            m["is_taken"] = True
                            try:
                                toggle_prescription_taken_in_supabase(client, m["id"], True)
                            except Exception:
                                pass
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"Confirmed! I've marked your {active_meal} medication ({med_names_str}) as taken. Great job maintaining your prescribed routine!",
                            "agent": "Medication Agent",
                        })
                        st.toast(f"{active_meal} medications marked as taken!", icon="✅")
                        st.rerun()

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
                st.caption("GROUPED BY MEALTIME: BREAKFAST · LUNCH · DINNER")
            with head_b:
                if st.button("＋ Add", key="add_medication_tab", use_container_width=True):
                    add_item_dialog("Medication")

            client = INTEGRATIONS.supabase_client()
            meds = DATA.get("medications", [])

            meal_groups = [
                ("🍳 BREAKFAST (MORNING)", "breakfast", "meal-breakfast"),
                ("🥗 LUNCH (AFTERNOON)", "lunch", "meal-lunch"),
                ("🍲 DINNER (NIGHT)", "dinner", "meal-dinner"),
                ("💊 AS NEEDED / GENERAL", "other", "meal-other"),
            ]

            for label, meal_key, css_class in meal_groups:
                if meal_key == "other":
                    group_meds = [m for m in meds if m.get("meal_timing") not in ("breakfast", "lunch", "dinner")]
                else:
                    group_meds = [m for m in meds if m.get("meal_timing") == meal_key]

                if group_meds:
                    st.markdown(f'<div class="meal-group-header {css_class}">{label}</div>', unsafe_allow_html=True)
                    for index, medication in enumerate(group_meds):
                        is_taken = medication.get("is_taken", False)
                        col_info, col_btn = st.columns([3.2, 1.2], gap="small")
                        with col_info:
                            record_card(
                                title=medication["name"],
                                meta=f"{medication['instruction']} · {medication.get('duration', '')}",
                                key=f"med_card_{meal_key}_{index}",
                                record_type="medication",
                                record=medication,
                                icon=":material/medication:",
                            )
                        with col_btn:
                            btn_label = "✓ Taken" if is_taken else "○ Mark taken"
                            btn_type = "secondary" if is_taken else "primary"
                            if st.button(btn_label, key=f"taken_btn_{medication.get('id', index)}_{meal_key}", type=btn_type, use_container_width=True):
                                record_activity_update("Medication taken toggle")
                                new_val = not is_taken
                                medication["is_taken"] = new_val
                                try:
                                    toggle_prescription_taken_in_supabase(client, medication["id"], new_val)
                                except Exception:
                                    pass
                                if new_val:
                                    st.session_state.messages.append({
                                        "role": "assistant",
                                        "content": f"I've marked your {medication['name']} as taken for {meal_key.title()}. Great job!",
                                        "agent": "Medication Agent",
                                    })
                                    st.toast(f"Marked {medication['name']} as taken!", icon="✅")
                                else:
                                    st.toast(f"Marked {medication['name']} as pending.", icon="ℹ️")
                                st.rerun()

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
                "Did I take my morning meds?",
                "What meds with lunch?",
                "Next appointment?",
                "My medicines?",
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


def render_doctor_portal() -> None:
    client = INTEGRATIONS.supabase_client()
    doc_snap = fetch_doctor_snapshot(client, st.session_state.active_doctor_id)
    doc = doc_snap.get("doctor") or {}
    today_appts = doc_snap.get("today_appointments") or []
    week_appts = doc_snap.get("week_appointments") or []
    all_appts = doc_snap.get("all_appointments") or []
    unavailability = doc_snap.get("unavailability") or []
    stats = doc_snap.get("stats") or {}

    doc_name = doc.get("name") or doc.get("doctor_name") or "Dr. Rhea Mehta"
    doc_id = doc.get("id") or doc.get("doctor_id") or st.session_state.get("active_doctor_id", "11111111-1111-1111-1111-111111111111")
    doc_specialization = doc.get("specialization") or doc.get("qualifications", "General Surgery Specialist")

    doc_left, doc_main, doc_right = st.columns([0.88, 1.35, 1.05], gap="medium")

    with doc_left:
        st.markdown('<span class="left-panel-marker"></span>', unsafe_allow_html=True)
        panel_header("Doctor Profile & Clinic", "", f"Updated {get_last_updated_str()} · OPD Live")
        st.markdown(
            f"""
            <div class="doctor-header-card">
              <div style="display:flex; gap:12px; align-items:center;">
                <div class="doctor-avatar">{escape(doc.get('initials', 'DR'))}</div>
                <div>
                  <div style="font:700 16px/1.2 'Manrope',sans-serif;">{escape(doc_name)}</div>
                  <div style="font-size:10px; opacity:.85; margin-top:2px;">Doctor ID · {escape(short_doctor_id(doc_id))} · {escape(doc_specialization)}</div>
                </div>
              </div>
              <div style="margin-top:12px; padding-top:10px; border-top:1px solid rgba(255,255,255,.15); font-size:10px; opacity:.88; line-height:1.5;">
                <div><strong>Department:</strong> {escape(doc.get('department', 'General Surgery'))}</div>
                <div><strong>Location:</strong> {escape(doc.get('location', doc.get('room_no', 'OPD Wing B, Room 304')))}</div>
                <div><strong>Contact:</strong> {escape(doc.get('email', doc.get('contact_email', 'dr.mehta@vesphcare.com')))}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="timeline-label">CLINIC WORKLOAD</div>', unsafe_allow_html=True)
        s_c1, s_c2, s_c3 = st.columns(3)
        s_c1.metric("Today", f"{stats.get('today_count', len(today_appts))}")
        s_c2.metric("This Week", f"{stats.get('week_count', len(week_appts))}")
        s_c3.metric("Blocked", f"{stats.get('blocked_count', len(unavailability))}")

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="timeline-label">BLOCKED TIME & LEAVE</div>', unsafe_allow_html=True)
        if st.button("⛔ Mark Unavailability / Block Slot", key="doc_block_btn", type="primary", use_container_width=True):
            doctor_unavailability_dialog(doc_id, doc_name)

        if not unavailability:
            st.caption("No schedule blocks active. All open OPD slots are available to patients.")
        else:
            for unavail in unavailability:
                u_id = unavail["unavailability_id"]
                u_date = unavail["blocked_date"]
                u_slot = unavail.get("blocked_slot") or "All Day"
                u_reason = unavail.get("reason", "Doctor unavailable")
                col_u_info, col_u_del = st.columns([3.2, 1.2], gap="small")
                with col_u_info:
                    st.markdown(
                        f"""
                        <div style="background:white; border:1px solid #FFD8A8; border-radius:9px; padding:7px 9px; font-size:10px; margin-top:6px;">
                          <strong style="color:#B25E00;">{escape(u_date)} · {escape(u_slot)}</strong>
                          <div style="color:var(--muted); font-size:9px; margin-top:2px;">{escape(u_reason)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with col_u_del:
                    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
                    if st.button("Unblock", key=f"unblock_btn_{u_id}", use_container_width=True):
                        record_activity_update("Doctor availability unblocked")
                        unblock_doctor_slot_in_supabase(client, u_id)
                        st.session_state._doctor_data_id = None
                        st.toast(f"Unblocked {u_date} {u_slot}!", icon="✅")
                        st.rerun()

    with doc_main:
        st.markdown('<span class="middle-panel-marker"></span>', unsafe_allow_html=True)
        hdr_col, btn_col = st.columns([1.75, 1.15], gap="small")
        with hdr_col:
            panel_header(
                "Doctor Appointment Agenda",
                f"Schedule Overview · {doc_name}",
                "Click on any appointment card to view patient clinical chart and actions.",
            )
        with btn_col:
            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
            if st.button("＋ Schedule Appointment", key="doc_add_appt_btn", type="primary", use_container_width=True):
                doctor_book_appointment_dialog(doc_id)

        doc_tabs = st.tabs([
            f"Today (18 Oct) · {len(today_appts)}",
            f"This Week (18–24 Oct) · {len(week_appts)}",
        ])

        # TAB 1: TODAY
        with doc_tabs[0]:
            st.markdown('<div class="timeline-label">TODAY\'S APPOINTMENTS (18 OCT 2026)</div>', unsafe_allow_html=True)
            if not today_appts:
                st.info("No appointments scheduled for today.")
            else:
                for idx, a in enumerate(today_appts):
                    p_name = a.get("patient_name", "Patient")
                    p_age = a.get("patient_age", "30")
                    p_gender = a.get("patient_gender", "F")
                    p_id = a.get("patient_id", "")
                    p_phone = a.get("patient_phone", "")
                    appt_date = a.get("date", "")
                    appt_time = a.get("time", "")
                    appt_type = a.get("type", "Consultation")
                    appt_status = a.get("status", "Confirmed")
                    appt_loc = a.get("location", "OPD Wing B")
                    appt_sum = a.get("summary", "")
                    rebook_notice = a.get("rebook_notice")

                    status_badge_class = "status" if appt_status == "Confirmed" else ("status wait" if "Reschedule" in appt_status or "Unavailable" in appt_status else "status old")
                    notice_html = f'<div class="rebook-notice">⚠️ <strong>Notice:</strong> {escape(rebook_notice)}</div>' if rebook_notice else ""

                    with st.container():
                        st.markdown('<div class="agenda-card-wrapper">', unsafe_allow_html=True)
                        st.markdown(
                            f"""
                            <div class="agenda-card">
                              <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                                <div style="display:flex; align-items:center; gap:8px;">
                                  <span class="agenda-time">{escape(appt_time)}</span>
                                  <strong style="font-size:13px; color:var(--ink);">{escape(p_name)}</strong>
                                  <span style="font-size:10px; color:var(--muted);">({escape(p_gender)}, {p_age}y) · ID: {escape(p_id[-4:] if p_id else '')}</span>
                                </div>
                                <div style="display:flex; gap:6px; align-items:center;">
                                  <span class="micro-pill" style="font-weight:700;">{escape(appt_type)}</span>
                                  <span class="{status_badge_class}">{escape(appt_status)}</span>
                                </div>
                              </div>
                              <div style="margin-top:6px; font-size:11px; color:#425B58; line-height:1.4;">
                                <strong>Date:</strong> {escape(appt_date)} · <strong>Location:</strong> {escape(appt_loc)} · <strong>Phone:</strong> {escape(p_phone)}
                              </div>
                              <div style="margin-top:5px; font-size:11px; color:var(--ink); line-height:1.4;">
                                {escape(appt_sum)}
                              </div>
                              {notice_html}
                              <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:6px; border-top:1px dashed #E2ECE9; font-size:10px; color:#0B6E69; font-weight:600;">
                                <span>🩺 Patient Clinical Chart & Actions</span>
                                <span>↗ Click card to view details</span>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if st.button("Open Chart", key=f"card_today_{idx}_{a['id']}", use_container_width=True):
                            patient_clinical_chart_dialog(p_id, appointment_data=a)

        # TAB 2: THIS WEEK (Clubbed by day/date of the week)
        with doc_tabs[1]:
            st.markdown('<div class="timeline-label">WEEKLY APPOINTMENTS BY DAY (18 – 24 OCT 2026)</div>', unsafe_allow_html=True)
            if not week_appts:
                st.info("No appointments scheduled for this week.")
            else:
                from collections import defaultdict
                grouped_by_day = defaultdict(list)
                for a in week_appts:
                    day_key = a.get("date") or "Scheduled OPD"
                    grouped_by_day[day_key].append(a)

                for day_label, day_appts in grouped_by_day.items():
                    st.markdown(
                        f"""
                        <div class="agenda-day-header">
                          <span>📅 {escape(day_label)}</span>
                          <span class="micro-pill" style="font-weight:700;">{len(day_appts)} appointment(s)</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    for idx, a in enumerate(day_appts):
                        p_name = a.get("patient_name", "Patient")
                        p_age = a.get("patient_age", "30")
                        p_gender = a.get("patient_gender", "F")
                        p_id = a.get("patient_id", "")
                        p_phone = a.get("patient_phone", "")
                        appt_date = a.get("date", "")
                        appt_time = a.get("time", "")
                        appt_type = a.get("type", "Consultation")
                        appt_status = a.get("status", "Confirmed")
                        appt_loc = a.get("location", "OPD Wing B")
                        appt_sum = a.get("summary", "")
                        rebook_notice = a.get("rebook_notice")

                        status_badge_class = "status" if appt_status == "Confirmed" else ("status wait" if "Reschedule" in appt_status or "Unavailable" in appt_status else "status old")
                        notice_html = f'<div class="rebook-notice">⚠️ <strong>Notice:</strong> {escape(rebook_notice)}</div>' if rebook_notice else ""

                        with st.container():
                            st.markdown('<div class="agenda-card-wrapper">', unsafe_allow_html=True)
                            st.markdown(
                                f"""
                                <div class="agenda-card">
                                  <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                                    <div style="display:flex; align-items:center; gap:8px;">
                                      <span class="agenda-time">{escape(appt_time)}</span>
                                      <strong style="font-size:13px; color:var(--ink);">{escape(p_name)}</strong>
                                      <span style="font-size:10px; color:var(--muted);">({escape(p_gender)}, {p_age}y) · ID: {escape(p_id[-4:] if p_id else '')}</span>
                                    </div>
                                    <div style="display:flex; gap:6px; align-items:center;">
                                      <span class="micro-pill" style="font-weight:700;">{escape(appt_type)}</span>
                                      <span class="{status_badge_class}">{escape(appt_status)}</span>
                                    </div>
                                  </div>
                                  <div style="margin-top:6px; font-size:11px; color:#425B58; line-height:1.4;">
                                    <strong>Date:</strong> {escape(appt_date)} · <strong>Location:</strong> {escape(appt_loc)} · <strong>Phone:</strong> {escape(p_phone)}
                                  </div>
                                  <div style="margin-top:5px; font-size:11px; color:var(--ink); line-height:1.4;">
                                    {escape(appt_sum)}
                                  </div>
                                  {notice_html}
                                  <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:6px; border-top:1px dashed #E2ECE9; font-size:10px; color:#0B6E69; font-weight:600;">
                                    <span>🩺 Patient Clinical Chart & Actions</span>
                                    <span>↗ Click card to view details</span>
                                  </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                            if st.button("Open Chart", key=f"card_week_{day_label}_{idx}_{a['id']}", use_container_width=True):
                                patient_clinical_chart_dialog(p_id, appointment_data=a)

    with doc_right:
        st.markdown('<span class="right-panel-marker"></span>', unsafe_allow_html=True)
        panel_header("Clinical Assistant", "")

        doc_chat_box = st.container(border=False, key="doctor_chat_history")
        with doc_chat_box:
            for message_index, message in enumerate(st.session_state.doctor_messages):
                avatar = DOCTOR_CHAT_AVATAR if message["role"] == "user" else VESPH_CHAT_AVATAR
                with st.chat_message(message["role"], avatar=avatar):
                    st.markdown(message["content"])
                if message["role"] == "assistant" and message.get("agent"):
                    st.markdown(
                        f'<div class="agent-route">{escape(message["agent"])}</div>',
                        unsafe_allow_html=True,
                    )

        with st.container(key="doctor_chat_dock"):
            upload_col, form_col = st.columns([0.18, 1.18], gap="small")
            with upload_col:
                with st.popover("", icon=":material/upload_file:", use_container_width=True, help="Upload Clinical Document (PDF)"):
                    st.markdown("**Upload Clinical Document (PDF)**")
                    uploaded_pdf = st.file_uploader(
                        "Clinical PDF",
                        type=["pdf"],
                        key="doc_pdf_uploader_widget",
                        label_visibility="collapsed",
                    )
                    if uploaded_pdf is not None:
                        if st.button("⚡ Process & Sync to DB", key="btn_process_uploaded_pdf", type="primary", use_container_width=True):
                            with st.spinner("Extracting text and syncing consultation to Supabase..."):
                                handle_consultation_pdf_ingestion(
                                    uploaded_pdf.getvalue(),
                                    file_name=uploaded_pdf.name,
                                )
                                st.rerun()

            with form_col:
                with st.form("doctor_chat_form", clear_on_submit=True):
                    prompt_col, send_col = st.columns([1, 0.18], gap="small")
                    with prompt_col:
                        doc_prompt = st.text_input(
                            "Message",
                            placeholder="Ask about appointments, offs, or patient details…",
                            label_visibility="collapsed",
                        )
                    with send_col:
                        doc_submitted = st.form_submit_button(
                            "",
                            key="doc_send_submit",
                            icon=":material/send:",
                            type="primary",
                            use_container_width=True,
                            help="Send message",
                        )

            if doc_submitted and doc_prompt.strip():
                add_doctor_chat_message(doc_prompt.strip(), doc_snap)
                st.rerun()

            doc_suggestions = [
                "Today's appointments?",
                "Ananya's current meds?",
                "Summarize Ananya's recovery",
                "Weekly schedule & offs",
            ]
            with st.container(key="doc_suggestion_row"):
                s_cols = st.columns(2, gap=None)
                for s_idx, sugg in enumerate(doc_suggestions):
                    with s_cols[s_idx % 2]:
                        if st.button(sugg, key=f"doc_sugg_{s_idx}", use_container_width=True):
                            add_doctor_chat_message(sugg, doc_snap)
                            st.rerun()


# -----------------------------------------------------------------------------
# Top Navigation Bar & Portal Dispatch
# -----------------------------------------------------------------------------
if st.session_state.get("doctor_toast"):
    msg, ic = st.session_state.pop("doctor_toast")
    st.toast(msg, icon=ic)

top_bar_col1, top_bar_col2, top_bar_col_reset, top_bar_col3 = st.columns([1.15, 1.25, 0.7, 1.1], gap="small", vertical_alignment="center")

with top_bar_col1:
    st.markdown(
        """
        <div style="display:flex; align-items:center; gap:10px; padding:2px 0;">
          <div class="brand-mark" style="width:34px; height:34px; font-size:18px;">✚</div>
          <div>
            <div style="font:700 16px/1.2 'Manrope',sans-serif; color:var(--ink);">VESPH Care</div>
            <div style="font-size:10px; color:var(--muted);">Virtual Engagement System for Patient Health</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top_bar_col2:
    mode_options = ["👤 Patient View", "🩺 Doctor View"]
    current_mode_idx = 0 if st.session_state.portal_mode == "patient" else 1
    selected_mode = st.radio(
        "Portal Mode",
        mode_options,
        index=current_mode_idx,
        horizontal=True,
        label_visibility="collapsed",
        key="portal_mode_radio",
    )
    new_mode = "patient" if "Patient" in selected_mode else "doctor"
    if new_mode != st.session_state.portal_mode:
        st.session_state.portal_mode = new_mode
        st.rerun()

with top_bar_col_reset:
    if st.button("↺ Reset DB", key="top_reset_db_btn", use_container_width=True, help="Reset Supabase database & state back to baseline"):
        with st.spinner("Restoring Supabase database to baseline..."):
            try:
                reset_supabase_database(INTEGRATIONS.supabase_client())
                st.session_state.clear()
                st.toast("Database and session reset to baseline!", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Error resetting database: {e}")

with top_bar_col3:
    if st.session_state.portal_mode == "patient":
        st.session_state.active_patient_id = "22222222-2222-2222-2222-222222222222"
        st.markdown(
            f"""
            <div style="display:flex; justify-content:flex-end; align-items:center; height:100%;">
              <div style="background:#E6F4F1; border:1px solid #94D3C5; border-radius:999px; padding:6px 14px; font-size:12px; font-weight:700; color:#075651; display:flex; align-items:center; gap:6px;">
                <span>👤</span>
                <span>Ananya Iyer · {short_patient_id(st.session_state.active_patient_id)}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.session_state.active_doctor_id = "11111111-1111-1111-1111-111111111111"
        st.markdown(
            f"""
            <div style="display:flex; justify-content:flex-end; align-items:center; height:100%;">
              <div style="background:#E6F4F1; border:1px solid #94D3C5; border-radius:999px; padding:6px 14px; font-size:12px; font-weight:700; color:#075651; display:flex; align-items:center; gap:6px;">
                <span>🩺</span>
                <span>Dr. Rhea Mehta · {short_doctor_id(st.session_state.active_doctor_id)}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

if st.session_state.portal_mode == "patient":
    render_patient_portal()
else:
    render_doctor_portal()

st.markdown(
    '<div class="footer-note">VESPH Care · Live Supabase Database Connection · Supported open-ended questions use Groq when configured</div>',
    unsafe_allow_html=True,
)
