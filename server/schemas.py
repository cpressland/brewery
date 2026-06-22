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


class CommandOut(BaseModel):
    id: str
    action: str
    package_name: str
    package_type: str


class SyncResponse(BaseModel):
    status: str
    packages_updated: int
    commands: list[CommandOut] = []
