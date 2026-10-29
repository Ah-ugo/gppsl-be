from typing import Literal, Optional
from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
IncidentType = Literal["incident", "near_miss", "unsafe_condition", "property_damage"]
AuditType = Literal["safety_inspection", "hse_audit", "permit_check", "toolbox_talk"]
RiskLevel = Literal["low", "medium", "high", "extreme"]
PermitType = Literal["hot_work", "confined_space", "working_at_height", "electrical", "excavation", "general"]


class HSEIncidentCreate(BaseModel):
    type: IncidentType
    title: str
    description: str
    date: Optional[str] = None
    time: Optional[str] = None
    location: str
    project_id: Optional[str] = None
    persons_involved: list[str] = []
    injuries: str = "none"  # none, first_aid, medical, lost_time, fatality
    severity: Severity = "low"
    immediate_actions: Optional[str] = None
    root_cause: Optional[str] = None
    photos: list[str] = []


class CorrectiveActionIn(BaseModel):
    incident_id: Optional[str] = None
    audit_id: Optional[str] = None
    description: str
    assigned_to_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    due_date: Optional[str] = None
    priority: Severity = "medium"


class CorrectiveActionUpdate(BaseModel):
    status: Optional[Literal["open", "in_progress", "closed", "overdue"]] = None
    resolution: Optional[str] = None
    closed_date: Optional[str] = None


class RiskAssessmentCreate(BaseModel):
    title: str
    project_id: Optional[str] = None
    activity: str
    hazards: list[dict] = []  # [{description, likelihood, severity, risk_level, controls}]
    reviewed_by: Optional[str] = None
    review_date: Optional[str] = None
    valid_until: Optional[str] = None


class PermitToWorkCreate(BaseModel):
    type: PermitType
    title: str
    project_id: Optional[str] = None
    location: str
    work_description: str
    permit_holder: str
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    precautions: list[str] = []
    issued_by: Optional[str] = None


class PermitToWorkUpdate(BaseModel):
    status: Optional[Literal["draft", "issued", "active", "suspended", "closed"]] = None
    suspension_reason: Optional[str] = None
    closed_at: Optional[str] = None


class HSEAuditCreate(BaseModel):
    type: AuditType
    title: str
    project_id: Optional[str] = None
    location: Optional[str] = None
    conducted_by: Optional[str] = None
    date: Optional[str] = None
    findings: list[dict] = []  # [{item, compliant, finding, action_required}]
    overall_score: Optional[float] = None
    notes: Optional[str] = None
