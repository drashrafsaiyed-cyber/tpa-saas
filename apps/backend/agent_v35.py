import json
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
from .ai_openai import generate_letter, analyze_final_gap

class AuthorizationStatus(Enum):
    PENDING = "Pending"
    QUERY_RAISED = "Query Raised"
    QUERY_REPLIED = "Query Replied"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    PARTIALLY_APPROVED = "Partially Approved"

@dataclass
class PreAuthorizationRecord:
    case_id: str
    request_date: datetime
    requested_amount: float
    approval_status: AuthorizationStatus
    approved_amount: Optional[float]
    approval_number: Optional[str]
    approval_date: Optional[datetime]
    queries: List[Dict]
    rejection_reason: Optional[str]

@dataclass
class FinalAuthorizationRecord:
    case_id: str
    request_date: datetime
    final_bill_amount: float
    pre_auth_approved: float
    additional_amount_requested: float
    approval_status: AuthorizationStatus
    approved_amount: Optional[float]
    approval_number: Optional[str]
    approval_date: Optional[datetime]
    queries: List[Dict]
    deductions: Dict[str, float]
    rejection_reason: Optional[str]
    documents_submitted: List[str]

class EnhancedTPAWithFinalAuth:
    def __init__(self):
        self.cases = {}
        self.pre_authorizations = {}
        self.final_authorizations = {}
        self.discharge_records = {}

    # NOTE: hospital_block/insurer_block are built by the Flask route (tenant aware)

    def send_preauth_request(self, case_id: str, patient_data: Dict, estimated_cost: float):
        self.cases[case_id] = patient_data
        self.pre_authorizations[case_id] = PreAuthorizationRecord(
            case_id=case_id, request_date=datetime.now(),
            requested_amount=estimated_cost, approval_status=AuthorizationStatus.PENDING,
            approved_amount=None, approval_number=None, approval_date=None, queries=[], rejection_reason=None
        )
        return {"status": "pre_auth_sent", "case_id": case_id, "requested_amount": estimated_cost}

    def handle_preauth_query(self, case_id: str, query_content: str, hospital_block:str, insurer_block:str):
        pre_auth = self.pre_authorizations.get(case_id)
        if not pre_auth:
            return {"error": "Pre-auth not found"}
        case_block = f"Query:\n{query_content}\n\nRespond point-wise with medical/policy justification."
        html = generate_letter(hospital_block, insurer_block, case_block, "pre-authorization")
        pre_auth.queries.append({
            "date": datetime.now().isoformat(),
            "query": query_content,
            "response": html
        })
        pre_auth.approval_status = AuthorizationStatus.QUERY_REPLIED
        return {"status": "query_replied", "response_html": html}

    def record_preauth_approval(self, case_id: str, approval_data: Dict):
        pre_auth = self.pre_authorizations.get(case_id)
        if not pre_auth:
            return {"error": "Pre-auth not found"}
        pre_auth.approval_status = AuthorizationStatus.APPROVED
        pre_auth.approved_amount = approval_data["approved_amount"]
        pre_auth.approval_number = approval_data["approval_number"]
        pre_auth.approval_date = datetime.fromisoformat(approval_data["approval_date"])
        return {"status": "pre_auth_approved", "approved_amount": pre_auth.approved_amount}

    def generate_final_auth_request(self, case_id: str, discharge_data: Dict, hospital_block:str, insurer_block:str):
        pre_auth = self.pre_authorizations.get(case_id)
        patient = self.cases.get(case_id)
        if not pre_auth or not patient:
            return {"error": "Pre-auth or patient data not found"}

        self.discharge_records[case_id] = discharge_data
        final_bill = discharge_data["final_bill_amount"]
        pre_auth_amount = pre_auth.approved_amount or 0
        additional_needed = max(0, final_bill - pre_auth_amount)

        case_block = f"""
CASE:
- Patient: {patient.get('name','N/A')}
- Pre-auth Approved: ₹{pre_auth_amount:,.2f} (Ref: {pre_auth.approval_number})
- Final Bill: ₹{final_bill:,.2f}
- Additional Needed: ₹{additional_needed:,.2f}

DISCHARGE SUMMARY:
- Admission: {discharge_data.get('admission_date')}
- Discharge: {discharge_data.get('discharge_date')}
- Final Diagnosis: {discharge_data.get('final_diagnosis')}
- Procedures: {', '.join(discharge_data.get('procedures', []))}
- LOS: {discharge_data.get('los', 0)} days
- Complications: {discharge_data.get('complications', 'None')}

BILL BREAKDOWN:
Room: ₹{discharge_data.get('room_charges',0):,.2f}
Surgery: ₹{discharge_data.get('surgery_charges',0):,.2f}
Pharmacy: ₹{discharge_data.get('pharmacy_charges',0):,.2f}
Investigations: ₹{discharge_data.get('investigation_charges',0):,.2f}
Doctor Fees: ₹{discharge_data.get('doctor_fees',0):,.2f}
Others: ₹{discharge_data.get('other_charges',0):,.2f}
"""
        html = generate_letter(hospital_block, insurer_block, case_block, "final authorization")

        self.final_authorizations[case_id] = FinalAuthorizationRecord(
            case_id=case_id, request_date=datetime.now(), final_bill_amount=final_bill,
            pre_auth_approved=pre_auth_amount, additional_amount_requested=additional_needed,
            approval_status=AuthorizationStatus.PENDING, approved_amount=None,
            approval_number=None, approval_date=None, queries=[], deductions={},
            rejection_reason=None, documents_submitted=[
                "Discharge Summary","Final Bill (itemized)","Investigation Reports","Pharmacy Bills","OT Notes","IPD Charts"
            ]
        )
        return {"status": "final_auth_generated", "request_letter_html": html, "additional_requested": additional_needed}

    def handle_final_auth_query(self, case_id: str, query_content: str, hospital_block:str, insurer_block:str):
        final_auth = self.final_authorizations.get(case_id)
        discharge = self.discharge_records.get(case_id)
        if not final_auth or not discharge:
            return {"error": "Final auth or discharge data not found"}
        case_block = f"""FINAL AUTH QUERY:
- Query: {query_content}
- Discharge Dx: {discharge.get('final_diagnosis','N/A')}
- LOS: {discharge.get('los',0)} days
- Procedures: {', '.join(discharge.get('procedures', []))}
Provide clear justification and list documents if needed."""
        html = generate_letter(hospital_block, insurer_block, case_block, "final authorization")
        final_auth.queries.append({
            "date": datetime.now().isoformat(),
            "query": query_content,
            "response": html
        })
        final_auth.approval_status = AuthorizationStatus.QUERY_REPLIED
        return {"status": "query_analyzed", "response_html": html}

    def record_final_auth_approval(self, case_id: str, approval_data: Dict):
        final_auth = self.final_authorizations.get(case_id)
        if not final_auth:
            return {"error": "Final auth not found"}
        final_auth.approval_status = AuthorizationStatus.APPROVED
        final_auth.approved_amount = approval_data["approved_amount"]
        final_auth.approval_number = approval_data["approval_number"]
        final_auth.approval_date = datetime.fromisoformat(approval_data["approval_date"])
        final_auth.deductions = approval_data.get("deductions", {})

        billed = final_auth.final_bill_amount
        approved = final_auth.approved_amount
        gap = billed - approved
        gap_pct = (gap / billed * 100) if billed else 0.0
        analysis = analyze_final_gap(billed, approved, json.dumps(final_auth.deductions, indent=2))
        return {
            "status": "final_auth_approved",
            "final_bill": billed, "approved_amount": approved,
            "gap_amount": gap, "gap_percentage": gap_pct,
            "deductions": final_auth.deductions,
            "ai_analysis": analysis,
            "requires_escalation": gap_pct > 20
        }
