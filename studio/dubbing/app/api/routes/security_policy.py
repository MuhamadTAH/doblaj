"""
Public Security Disclosure Policy Route for Dubbing Studio.

Implements Part 10 / Video 57 (DayW9qUEVyF.mp4):
- Public Security & Compliance Disclosure Page
- Answers enterprise procurement security questionnaire items:
  - Encryption in transit (TLS 1.3) and at rest (AES-256)
  - Row Level Security (RLS) & workspace isolation
  - Vulnerability reporting channel & Security Contact
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/security")
async def get_security_policy():
    """Public Security Disclosure Policy and Procurement Statement."""
    return {
        "platform": "Dubbing Studio",
        "security_contact": "security@doblaj.com",
        "compliance": {
            "encryption_in_transit": "TLS 1.3 / HTTPS",
            "encryption_at_rest": "AES-256 (Cloudflare R2 & Convex)",
            "authentication": "Clerk JWT (RS256 signature verification)",
            "data_isolation": "Row Level Security (RLS) & Workspace Scoping",
            "owasp_headers": "Strict-Transport-Security, Content-Security-Policy, X-Frame-Options",
            "security_scans": "Automated build scans & dependency audits",
        },
        "vulnerability_reporting": {
            "policy": "Responsible Disclosure Policy",
            "email": "security@doblaj.com",
            "response_sla": "24 hours",
        }
    }
