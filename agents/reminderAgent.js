const { ChatOpenAI } = require('@langchain/openai');
const { SystemMessage, HumanMessage } = require('@langchain/core/messages');
const pool = require('./db');
require('dotenv').config();

const model = new ChatOpenAI({
  modelName: 'gpt-4o-mini',
  temperature: 0.2,
  openAIApiKey: process.env.OPENAI_API_KEY
});

class ReminderAgent {
  /**
   * 1. Check intervals and trigger pending reminders for appointments,
   *    diagnostics, operations, insurance docs, and medications.
   */
  static async getPendingReminders(patientId) {
    // 1. Fetch upcoming appointments
    const apptQuery = `
      SELECT a.appointment_id, a.appointment_type, a.appointment_datetime, 
             a.reminders_sent_count, a.status, a.location,
             d.doctor_name, d.department, d.room_no,
             p.first_name, p.contact_phone, p.insurance_provider, p.insurance_policy_no
      FROM appointments a
      JOIN patients p ON a.patient_id = p.patient_id
      LEFT JOIN doctors d ON a.doctor_id = d.doctor_id
      WHERE a.patient_id = $1 
        AND a.status IN ('BOOKED', 'CONFIRMED', 'RESCHEDULED')
        AND a.appointment_datetime > NOW()
      ORDER BY a.appointment_datetime ASC
      LIMIT 1;
    `;
    const apptRes = await pool.query(apptQuery, [patientId]);
    const appointment = apptRes.rows[0];

    // 2. Fetch pending medication adherence checks
    const medQuery = `
      SELECT pm.prescription_item_id, m.brand_name, pm.dosage, 
             pm.frequency_per_day, pm.instructions, pm.is_taken
      FROM patient_medications pm
      JOIN medicines m ON pm.medicine_id = m.medicine_id
      WHERE pm.patient_id = $1 
        AND pm.start_date <= CURRENT_DATE 
        AND (pm.start_date + pm.duration_days) >= CURRENT_DATE
        AND pm.is_taken = false;
    `;
    const medRes = await pool.query(medQuery, [patientId]);

    // 3. Fetch insurance billing status
    const billQuery = `
      SELECT billing_status, patient_payable_amount 
      FROM billing_and_payments 
      WHERE patient_id = $1 AND billing_status = 'INSURANCE_PROCESSING'
      LIMIT 1;
    `;
    const billRes = await pool.query(billQuery, [patientId]);

    return {
      appointment,
      pendingMeds: medRes.rows,
      insurancePending: billRes.rows[0]
    };
  }

  /**
   * 2. Formulate AI personalized reminder based on timing and context
   */
  static async generateScheduledReminder(patientId) {
    const data = await this.getPendingReminders(patientId);
    if (!data.appointment && data.pendingMeds.length === 0) {
      return { message: "You have no upcoming appointments or pending medication reminders right now." };
    }

    const { appointment, pendingMeds, insurancePending } = data;
    let timingCategory = "GENERAL";

    if (appointment) {
      const now = new Date();
      const apptTime = new Date(appointment.appointment_datetime);
      const hoursDiff = (apptTime - now) / (1000 * 60 * 60);

      if (hoursDiff <= 48 && hoursDiff > 12 && appointment.reminders_sent_count === 0) {
        timingCategory = "T_MINUS_48_HOURS";
      } else if (hoursDiff <= 12 && hoursDiff > 0 && appointment.reminders_sent_count <= 1) {
        timingCategory = "T_MINUS_2_HOURS";
      }
    }

    const prompt = `
      You are the Hospital AI Patient Follow-Up & Reminder Assistant.
      Compose a warm, helpful, and concise SMS / WhatsApp notification for:
      - Patient: ${appointment?.first_name || 'Patient'}
      - Appointment Type: ${appointment?.appointment_type || 'N/A'} (e.g. CONSULTATION, DIAGNOSTIC, OPERATION)
      - Doctor / Dept: ${appointment?.doctor_name || 'Assigned Department'} (${appointment?.department || 'Main Wing'})
      - Location / Room: ${appointment?.location || 'General OPD'} Room ${appointment?.room_no || ''}
      - Scheduled DateTime: ${appointment?.appointment_datetime || 'N/A'}
      - Reminder Stage: ${timingCategory}
      - Insurance Issue: ${insurancePending ? "Insurance requires missing identity/policy documentation upload." : "None"}
      - Pending Medications: ${pendingMeds.map(m => `${m.brand_name} (${m.dosage},${m.frequency_per_day})`).join(', ') || "None"}

      MANDATORY INSTRUCTIONS:
      1. For appointment reminders, explicitly state: "Reply CONFIRM to confirm or RESCHEDULE with your preferred date/time slot."
      2. If appointment type is 'OPERATION' or 'DIAGNOSTIC', remind them of fasting/pre-procedure protocols.
      3. If insurance documentation is pending, urge them to submit the documents before visit.
      4. If medications are due, ask if they have taken them today.
      Keep it clear and readable on mobile screens.
    `;

    const response = await model.invoke([new SystemMessage(prompt)]);

    // Update reminder counter in DB if appointment was alerted
    if (appointment && timingCategory !== "GENERAL") {
      await pool.query(
        `UPDATE appointments SET reminders_sent_count = reminders_sent_count + 1 WHERE appointment_id = $1`,
        [appointment.appointment_id]
      );
    }

    return {
      reminderText: response.content,
      appointmentId: appointment?.appointment_id,
      medications: pendingMeds
    };
  }

  /**
   * 3. Process Patient Reply (Confirm / Reschedule / Medication Check-off)
   */
  static async handlePatientReply(patientId, userReply) {
    const intentPrompt = `
      Extract the intent and any entities from this patient response:
      "${userReply}"
      
      Output JSON strictly with keys:
      {
        "intent": "CONFIRM" | "RESCHEDULE" | "MEDICATION_TAKEN" | "GENERAL_QUERY",
        "preferred_datetime": "ISO-8601 string or null if not provided",
        "notes": "short note"
      }
    `;

    const intentRes = await model.invoke([new SystemMessage(intentPrompt)]);
    const cleanJson = intentRes.content.replace(/```json/g, '').replace(/```/g, '').trim();
    const parsed = JSON.parse(cleanJson);

    let confirmationMessage = "";

    if (parsed.intent === "CONFIRM") {
      await pool.query(
        `UPDATE appointments SET status = 'CONFIRMED' 
         WHERE patient_id = $1 AND status IN ('BOOKED', 'RESCHEDULED') 
         ORDER BY appointment_datetime ASC LIMIT 1`,
        [patientId]
      );
      confirmationMessage = "✅ Thank you! Your appointment has been officially confirmed.";
    } 
    else if (parsed.intent === "RESCHEDULE") {
      if (parsed.preferred_datetime) {
        await pool.query(
          `UPDATE appointments 
           SET appointment_datetime = $1, status = 'RESCHEDULED', reminders_sent_count = 0
           WHERE patient_id = $2 AND status IN ('BOOKED', 'CONFIRMED', 'RESCHEDULED')
           ORDER BY appointment_datetime ASC LIMIT 1`,
          [parsed.preferred_datetime, patientId]
        );
        confirmationMessage = `🗓️ Your appointment has been rescheduled to ${new Date(parsed.preferred_datetime).toLocaleString()}.`;
      } else {
        confirmationMessage = "We received your request to reschedule. Please provide your preferred date and time slot (e.g., 'Tomorrow at 3 PM').";
      }
    } 
    else if (parsed.intent === "MEDICATION_TAKEN") {
      await pool.query(
        `UPDATE patient_medications SET is_taken = true 
         WHERE patient_id = $1 AND is_taken = false`,
        [patientId]
      );
      confirmationMessage = "💊 Great job! We've recorded that you've taken your prescribed medication today.";
    } 
    else {
      // General conversational fallback
      const reply = await model.invoke([
        new SystemMessage("You are a helpful hospital coordinator assistant. Keep answers concise."),
        new HumanMessage(userReply)
      ]);
      confirmationMessage = reply.content;
    }

    return {
      botResponse: confirmationMessage,
      actionTaken: parsed.intent
    };
  }
}

module.exports = ReminderAgent;
