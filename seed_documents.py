"""Sample documents for AI search and signing demos. Loaded by seed.py after the main data."""
from app.core.common import new_id, utcnow_iso
from app.modules.documents import service
from app.modules.documents.pdfsign import make_text_pdf

DOCS = [
    ("Hydrotest Safety Procedure.pdf", "Procedures", ["md", "admin", "supervisor", "storekeeper", "hr", "finance"], "Hydrotest safety procedure", [
        "Before any hydrostatic pressure test, the supervisor must isolate the line, fit blanks at all open ends and confirm gauge calibration certificates are valid.",
        "All personnel not involved in the test must leave the exclusion zone, which is 15 metres around the test section. Pressure is raised in steps of 10 percent of test pressure with a 5 minute hold at each step.",
        "A test is complete only when the pressure holds for 60 minutes with no drop beyond the allowed tolerance. The supervisor signs the test record and sends a photo to the office."]),
    ("Equipment Rental Terms.pdf", "Contracts", ["md", "admin", "finance", "storekeeper"], "Equipment rental terms and conditions", [
        "Equipment is rented at a daily, weekly or monthly rate stated on the handover form. Rental starts on the day of check-out and ends on the day of return.",
        "The client must return equipment by the agreed date. Late return is charged at the full daily rate for each additional day. Equipment with an expired inspection certificate is never released.",
        "The client is responsible for damage beyond normal wear. Condition is recorded with four photographs and a signature at hand-over and again at return."]),
    ("Leave and Attendance Policy.pdf", "HR", ["md", "admin", "hr", "supervisor"], "Leave and attendance policy", [
        "Permanent staff receive twenty working days of annual leave, requested at least two weeks ahead through the supervisor and approved by HR.",
        "Staff clock in with a selfie and location at the start of every shift. A shift starts at 08:00 and clock-in after 08:15 is recorded as late. A failed face match never leads to an automatic penalty, a supervisor reviews it.",
        "Payroll is calculated from verified attendance only. Flagged entries are reviewed by the supervisor before the month closes."]),
    ("Expense and Approval Policy.pdf", "Finance", ["md", "admin", "finance", "supervisor", "storekeeper", "hr"], "Expense and approval policy", [
        "Every expense is raised with a photograph of the receipt. Expenses up to the finance limit are approved by Finance. Anything above the limit is approved by the Managing Director.",
        "The system flags a possible duplicate when the vendor, amount and date match an earlier expense, and flags an expense as unusually high when it is more than three times the category average.",
        "Receipts must be attached. An expense without a receipt may be rejected by the approver, who must write a reason."]),
    ("Confined Space Entry Standard.pdf", "Procedures", ["md", "admin", "supervisor", "storekeeper"], "Confined space entry standard", [
        "No person enters a confined space without a valid permit, a gas test and a standby person outside. H2S awareness certification is mandatory for all entrants.",
        "Gas readings for oxygen, flammable gas and hydrogen sulphide must be recorded before entry and every hour during the work.",
        "In an emergency the standby person raises the alarm and must never enter the space to attempt a rescue alone."]),
    ("Nitrogen Unit Operating Manual.pdf", "Equipment manuals", ["md", "admin", "supervisor", "storekeeper"], "Nitrogen unit operating manual", [
        "The nitrogen unit must be serviced every 600 run hours. Check the liquid nitrogen vaporiser, pump seals and pressure relief valve at each service.",
        "Before deployment confirm the pressure inspection and calibration certificates are in date. Record the run-hour meter at hand-over and at return.",
        "During operation keep the unit on level ground, earth the unit, and maintain a 10 metre exclusion zone around discharge lines."]),
    ("Warri Base Site Rules.pdf", "Sites", ["md", "admin", "supervisor", "storekeeper", "hr"], "Warri base site rules", [
        "All visitors sign in at the gate. Safety boots, helmet, glasses and coveralls are mandatory in the yard. The assembly point is next to the fuel store.",
        "Vehicles move at walking pace inside the yard. Lifting operations need a banksman and a lifting plan signed by the supervisor.",
        "Warri crew start at 08:00. The clock-in geofence for the base is 250 metres around the gate."]),
    ("Incident Reporting Guide.pdf", "Procedures", ["md", "admin", "supervisor", "storekeeper", "hr", "finance"], "Incident reporting guide", [
        "Report every incident, near miss and spill from the site using the app, with photos. Choose a severity of low, medium or high.",
        "A high severity incident alerts the Managing Director immediately. The supervisor secures the area and does not disturb evidence until the HSE officer arrives.",
        "Within 24 hours the supervisor adds the cause and the corrective action to the report."]),
    ("Client Master Service Agreement (sample).pdf", "Contracts", ["md", "admin", "finance"], "Master service agreement, sample", [
        "This sample agreement is between Global Process and Pipeline Services Limited and a placeholder client for pipeline cleaning, hydrotesting and equipment rental services.",
        "Invoices are payable within the agreed payment terms. Late payment may delay further equipment releases. VAT is charged at 7.5 percent where applicable.",
        "Either party may end the agreement with thirty days written notice. Disputes are first escalated to senior management of both companies."]),
    ("Vendor Onboarding Checklist.pdf", "Finance", ["md", "admin", "finance"], "Vendor onboarding checklist", [
        "Collect the company registration, tax identification number and bank account confirmation before the first payment to any vendor.",
        "Two quotations are required for purchases above the finance approval limit. The MD approves the final selection.",
        "Record WHT deducted on each payment so finance can track the figures. This checklist does not give tax advice."]),
]


async def seed_documents(db, data, today):
    md = {"id": data["users"][0]["_id"], "name": data["users"][0]["name"], "role": "md"}
    created = {}
    for name, folder, roles, title, paras in DOCS:
        pdf = make_text_pdf(title, paras)
        doc = await service.create_document(name, folder, pdf, "application/pdf", roles, md)
        created[name] = doc
    # a document waiting for the MD and Admin to sign, in order, so the signing demo starts with one in the queue
    target = created["Client Master Service Agreement (sample).pdf"]
    signers = [{"user_id": u["_id"], "name": u["name"], "order": i, "status": "pending", "signed_at": None, "ip": None, "location": None}
               for i, u in enumerate([data["users"][2], data["users"][0]], start=1)]  # finance first, then MD
    await db.signature_requests.insert_one({"_id": new_id(), "document_id": target["_id"], "document_name": target["name"], "signers": signers,
                                            "status": "Awaiting signature", "requested_by": {"id": data["users"][1]["_id"], "name": data["users"][1]["name"]},
                                            "created_at": utcnow_iso()})
    await db.documents.update_one({"_id": target["_id"]}, {"$set": {"status": "Awaiting signature"}})
