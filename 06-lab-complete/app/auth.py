"""
API Key authentication (tiêu chí 6).

• Client gửi header  X-API-Key: <key>
• Key phải trùng biến môi trường AGENT_API_KEY
• Thiếu hoặc sai key → HTTP 401
"""
import hashlib
import secrets

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_UNAUTHORIZED = {"WWW-Authenticate": "ApiKey"}


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key).

    Trả về định danh của client (hash của key) để rate limit / cost guard
    dùng làm khoá Redis — không bao giờ lưu key gốc vào Redis hay log.
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Include header: X-API-Key: <your-key>",
            headers=_UNAUTHORIZED,
        )
    expected = settings.agent_api_key
    # compare_digest: so sánh thời gian hằng, tránh timing attack
    if not expected or not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key.", headers=_UNAUTHORIZED)
    return client_id(api_key)


def client_id(api_key: str) -> str:
    """Định danh ổn định, không lộ secret: 16 ký tự đầu của SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]
