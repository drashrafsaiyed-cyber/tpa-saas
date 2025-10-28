from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

ROLE_SUPERADMIN = "superadmin"
ROLE_HOSPITAL_ADMIN = "hospital_admin"
ROLE_STAFF = "staff"

class Hospital(db.Model):
    __tablename__ = "hospitals"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(512))
    rohini_id = db.Column(db.String(64))
    phone = db.Column(db.String(32))
    admin_contact = db.Column(db.String(128))
    # per-hospital sender settings (can be updated any time)
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer)
    smtp_user = db.Column(db.String(255))
    smtp_pass = db.Column(db.String(255))
    sender_name = db.Column(db.String(255))
    sender_email = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=False)
    is_data_opt_in = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), default=ROLE_STAFF)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

class Insurer(db.Model):
    __tablename__ = "insurers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    default_email = db.Column(db.String(255))
    notes = db.Column(db.Text)

class HospitalInsurer(db.Model):
    __tablename__ = "hospital_insurers"
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    insurer_id = db.Column(db.Integer, db.ForeignKey("insurers.id"), nullable=False)
    mou_number = db.Column(db.String(128))
    cashless_email = db.Column(db.String(255))
    escalation_email = db.Column(db.String(255))
    requires_final_auth = db.Column(db.Boolean, default=True)
    final_auth_deadline_days = db.Column(db.Integer, default=7)
    __table_args__ = (db.UniqueConstraint("hospital_id","insurer_id", name="uq_hosp_insurer"),)

class Case(db.Model):
    __tablename__ = "cases"
    id = db.Column(db.Integer, primary_key=True)
    case_code = db.Column(db.String(64), unique=True, nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    patient_name = db.Column(db.String(255), nullable=False)
    insurer_id = db.Column(db.Integer, db.ForeignKey("insurers.id"), nullable=False)
    policy_no = db.Column(db.String(128))
    status = db.Column(db.String(32), default="preauth_pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Authorization(db.Model):
    __tablename__ = "authorizations"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    phase = db.Column(db.String(16))  # "pre" | "final"
    requested_amount = db.Column(db.Float)
    approved_amount = db.Column(db.Float)
    approval_number = db.Column(db.String(128))
    status = db.Column(db.String(32), default="pending")
    details_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EmailLog(db.Model):
    __tablename__ = "email_logs"
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    to_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime)
    status = db.Column(db.String(32), default="queued")
    provider_message_id = db.Column(db.String(255))
