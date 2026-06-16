from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class CreateRoleRequest(BaseModel):
    roleId: str
    displayName: str
    description: Optional[str] = ""
    permissions: List[str]


class UpdateRoleRequest(BaseModel):
    displayName: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


class UpdatePermissionsRegistryRequest(BaseModel):
    permissions: List[dict]
