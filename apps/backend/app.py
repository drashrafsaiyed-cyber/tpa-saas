import os
from datetime import timedelta, datetime
from email.mime.text import MIMEText
import smtplib

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash

from models import (
    db, Hospital, User, Insurer, HospitalInsurer, Case, Authorization, EmailLog,
    ROLE_SUPERADMIN, ROLE_HOSPITAL_ADMIN, ROLE_STAFF
)
from agent_v35 import EnhancedTPAWithFinalAuth
from ai_openai import generate_letter

DB_URL = os.getenv("DATABASE_URL", "sqlite:///tpa_saas.db")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")

app = Flask(__name__)
app.config.update(
    SQLALCHEMY_DATABASE_URI=DB_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    JWT_SECRET_KEY=JWT_SECRET
)
db.init_app(app)
jwt = JWTManager(app)
agent = EnhancedTPAWithFinalAuth()

# ---------- Helpers ----------
def claims(): return get_jwt()
def current_hid():
    c = claims()
    return None if c.get("role")==ROLE_SUPERADMIN else c.get("hospital_id")

def require_role(*roles):
    def wrapper(fn):
        from functools import wraps
        @wraps(fn)
        def inner(*a, **k):
            if claims().get("role") not in roles:
                return jsonify({"error":"insufficient_role"}), 403
            return fn(*a, **k)
        return inner
    return wrapper

@jwt.additional_claims_loader
def add_claims(identity):
    user = User.query.get(identity)
    return {"role": user.role, "hospital_id": user.hospital_id}

def tenant_ok(row_hid:int)->bool:
    hid = current_hid()
    return hid is None or hid == row_hid

def hospital_block(h:Hospital)->str:
    return f"""Hospital:
- Name: {h.name}
- Address: {h.address or 'N/A'}
- ROHINI: {h.rohini_id or 'N/A'}
- Phone: {h.phone or 'N/A'}"""

def insurer_block(hid:int, ins:Insurer)->str:
    hi = HospitalInsurer.query.filter_by(hospital_id=hid, insurer_id=ins.id).first()
    return f"""Insurer:
- Name: {ins.name}
- Cashless Email: {(hi.cashless_email if hi else ins.default_email) or 'N/A'}"""

def resolve_sender(h:Hospital):
    # hospital-level sender first, else global fallback
    return dict(
        host=h.smtp_host or os.getenv("SMTP_HOST"),
        port=int(h.smtp_port or os.getenv("SMTP_PORT","465")),
        user=h.smtp_user or os.getenv("SMTP_USER"),
        pwd=h.smtp_pass or os.getenv("SMTP_PASS"),
        sender_name=h.sender_name or os.getenv("SENDER_NAME","TPA Desk"),
        sender_email=h.sender_email or os.getenv("SENDER_EMAIL", os.getenv("SMTP_USER"))
    )

def send_email(hospital:Hospital, to_email:str, subject:str, html:str):
    cfg = resolve_sender(hospital)
    msg = MIMEText(html, "html")
    msg["Subject"] = subject
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender_email']}>"
    msg["To"] = to_email
    try:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
            server.login(cfg["user"], cfg["pwd"])
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)

# ---------- Routes ----------
@app.get("/")
def root():
    return jsonify({"name":"TPA API","status":"ok"})

@app.post("/bootstrap/superadmin")
def bootstrap():
    with app.app_context():
        db.create_all()
    if User.query.filter_by(role=ROLE_SUPERADMIN).first():
        return jsonify({"message":"superadmin_exists"})
    data = request.json or {"email":"admin@tpasaas.local","password":"Admin@123"}
    u = User(email=data["email"], password_hash=generate_password_hash(data["password"]), role=ROLE_SUPERADMIN)
    db.session.add(u); db.session.commit()
    return jsonify({"message":"superadmin_created","email":u.email})

@app.post("/auth/login")
def login():
    data = request.json
    u = User.query.filter_by(email=data["email"]).first()
    if not u or not check_password_hash(u.password_hash, data["password"]):
        return jsonify({"error":"invalid_credentials"}), 401
    if u.role != ROLE_SUPERADMIN:
        h = Hospital.query.get(u.hospital_id)
        if not h or not h.is_active:
            return jsonify({"error":"hospital_not_approved"}), 403
    token = create_access_token(identity=u.id, expires_delta=timedelta(hours=12))
    return jsonify({"access_token":token})

@app.post("/auth/register_hospital")
@jwt_required()
@require_role(ROLE_SUPERADMIN)
def register_hospital():
    data = request.json
    h = Hospital(
        name=data["name"], address=data.get("address"), rohini_id=data.get("rohini_id"),
        phone=data.get("phone"), admin_contact=data.get("admin_contact"),
        is_active=data.get("is_active", False)
    )
    db.session.add(h); db.session.commit()
    return jsonify({"id":h.id,"name":h.name,"is_active":h.is_active})

@app.post("/auth/create_user")
@jwt_required()
@require_role(ROLE_SUPERADMIN, ROLE_HOSPITAL_ADMIN)
def create_user():
    data = request.json
    role = claims().get("role")
    target_hid = data.get("hospital_id") if role==ROLE_SUPERADMIN else claims().get("hospital_id")
    u = User(email=data["email"], password_hash=generate_password_hash(data["password"]),
             role=data.get("role", ROLE_STAFF), hospital_id=target_hid)
    db.session.add(u); db.session.commit()
    return jsonify({"id":u.id,"email":u.email,"role":u.role})

@app.post("/insurers")
@jwt_required()
@require_role(ROLE_SUPERADMIN)
def create_insurer():
    data = request.json
    ins = Insurer(name=data["name"], default_email=data.get("default_email"), notes=data.get("notes"))
    db.session.add(ins); db.session.commit()
    return jsonify({"id":ins.id,"name":ins.name})

@app.post("/hospitals/insurers")
@jwt_required()
@require_role(ROLE_HOSPITAL_ADMIN, ROLE_SUPERADMIN)
def attach_insurer():
    data = request.json
    role = claims().get("role")
    hid = data.get("hospital_id") if role==ROLE_SUPERADMIN else claims().get("hospital_id")
    hi = HospitalInsurer(
        hospital_id=hid, insurer_id=data["insurer_id"],
        mou_number=data.get("mou_number"), cashless_email=data.get("cashless_email"),
        escalation_email=data.get("escalation_email"),
        requires_final_auth=data.get("requires_final_auth", True),
        final_auth_deadline_days=data.get("final_auth_deadline_days", 7)
    )
    db.session.add(hi); db.session.commit()
    return jsonify({"id":hi.id})

@app.post("/cases")
@jwt_required()
def create_case():
    data = request.json
    hid = current_hid() or data.get("hospital_id")
    c = Case(case_code=data["case_code"], hospital_id=hid, patient_name=data["patient_name"],
             insurer_id=data["insurer_id"], policy_no=data.get("policy_no"))
    db.session.add(c); db.session.commit()
    return jsonify({"id":c.id,"case_code":c.case_code})

@app.post("/ai/generate_letter")
@jwt_required()
def ai_generate_letter_route():
    data = request.json
    case = Case.query.filter_by(case_code=data["case_code"]).first()
    if not case or not tenant_ok(case.hospital_id):
        return jsonify({"error":"case_not_found_or_forbidden"}), 404
    h = Hospital.query.get(case.hospital_id)
    ins = Insurer.query.get(case.insurer_id)
    html = generate_letter(hospital_block(h), insurer_block(h.id, ins),
                           data.get("case_block",""), data.get("phase","pre-authorization"))
    return jsonify({"html":html})

@app.post("/authorizations/request")
@jwt_required()
def send_authorization_email():
    data = request.json
    case = Case.query.filter_by(case_code=data["case_code"]).first()
    if not case or not tenant_ok(case.hospital_id):
        return jsonify({"error":"case_not_found_or_forbidden"}), 404

    h = Hospital.query.get(case.hospital_id)
    ins = Insurer.query.get(case.insurer_id)
    hi = HospitalInsurer.query.filter_by(hospital_id=h.id, insurer_id=ins.id).first()
    to_email = (hi.cashless_email if hi else ins.default_email)
    if not to_email:
        return jsonify({"error":"insurer_email_not_configured"}), 400

    subject = data.get("subject", f"{data.get('phase','pre').title()} Authorization – {case.case_code}")
    html = data["html_body"]

    log = EmailLog(hospital_id=case.hospital_id, case_id=case.id,
                   to_email=to_email, subject=subject, body_html=html, status="queued")
    db.session.add(log); db.session.commit()

    ok, err = send_email(h, to_email, subject, html)
    log.sent_at = datetime.utcnow()
    log.status = "sent" if ok else f"error:{err}"
    db.session.commit()

    auth = Authorization(case_id=case.id, hospital_id=case.hospital_id,
                         phase=data.get("phase","pre"), requested_amount=data.get("requested_amount"),
                         status="pending", details_json=data.get("details_json"))
    db.session.add(auth); db.session.commit()

    return jsonify({"to":to_email,"email_status":log.status,"authorization_id":auth.id})

@app.get("/email_logs")
@jwt_required()
def email_logs():
    hid = current_hid()
    q = EmailLog.query if hid is None else EmailLog.query.filter_by(hospital_id=hid)
    rows = q.order_by(EmailLog.id.desc()).limit(200).all()
    return jsonify([
        {"id":r.id,"case_id":r.case_id,"to":r.to_email,"subject":r.subject,
         "status":r.status,"sent_at":(r.sent_at.isoformat() if r.sent_at else None)}
        for r in rows
    ])

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=True)
