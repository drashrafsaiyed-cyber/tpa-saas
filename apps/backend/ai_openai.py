import os
from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_letter(hospital_block: str, insurer_block: str, case_block: str, phase: str):
    prompt = f"""
You are a hospital TPA desk writer. Draft a professional {phase} authorization email
for cashless processing. Use neutral, clinical tone and clear sections.

{hospital_block}

{insurer_block}

{case_block}
"""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return f"<pre>{resp.choices[0].message.content}</pre>"

def analyze_final_gap(billed: float, approved: float, deductions_json: str):
    prompt = f"""
Analyze final authorization result.

BILLED: ₹{billed:,.2f}
APPROVED: ₹{approved:,.2f}
DEDUCTIONS: {deductions_json}

Return bullet points:
1) Acceptable gap? (<10% is OK)
2) Escalation? (>20% act)
3) Immediate actions
4) Expected recovery
"""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content
