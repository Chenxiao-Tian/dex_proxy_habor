from pydantic import BaseModel

class StatusParams(BaseModel):
    """Empty request model for endpoints with no body."""
    pass

class StatusResponse(BaseModel):
    status: str

