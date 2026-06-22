from pydantic import BaseModel


class PackageIn(BaseModel):
    name: str
    version: str | None = None


class SyncRequest(BaseModel):
    serial_number: str
    hostname: str
    agent_version: str | None = None
    formulas: list[PackageIn] = []
    casks: list[PackageIn] = []


class SyncResponse(BaseModel):
    status: str
    packages_updated: int
