"""
File Browser route — GCS-backed folder browsing, creation, and item moves.

All paths are relative to the case root ({caseId}/) in GCS.
Folders are represented by a .keep placeholder object (GCS has no real folders).

GET  /api/v1/storage/cases/{case_id}/browse          — list files and folders at a path
POST /api/v1/storage/cases/{case_id}/folders         — create a folder
POST /api/v1/storage/cases/{case_id}/move            — move a file or folder
"""

import logging

from fastapi import APIRouter, Query, Request

from app.config import get_settings
from app.models.storage import (
    BrowseItem,
    BrowseResponse,
    CreateFolderRequest,
    CreateFolderResponse,
    MoveRequest,
    MoveResponse,
)
from app.utils.audit import AuditAction, log_audit_event
from app.utils.gcs_client import get_gcs_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage", tags=["File Browser"])


def _get_bucket():
    settings = get_settings()
    client = get_gcs_client()
    return client.bucket(settings.gcs_bucket_name)


def _strip_case_prefix(blob_name: str, case_id: str) -> str:
    """Remove '{case_id}/' prefix from a GCS object name."""
    return blob_name[len(f"{case_id}/"):]


@router.get(
    "/cases/{case_id}/browse",
    response_model=BrowseResponse,
    summary="List files and folders at a path within the case GCS directory",
)
def browse_folder(
    request: Request,
    case_id: str,
    path: str = Query("", description="Folder path relative to caseId; empty = case root"),
):
    """
    Returns immediate children (files and sub-folders) at the given path.

    Folders are items that have child objects under their prefix.
    .keep placeholder blobs are filtered from the file listing.
    Items are sorted folders-first, then alphabetically by name.
    """
    bucket = _get_bucket()
    prefix = f"{case_id}/{path}/" if path else f"{case_id}/"

    iterator = bucket.list_blobs(prefix=prefix, delimiter="/")
    blobs = list(iterator)  # consume iterator so iterator.prefixes is populated
    prefixes = list(iterator.prefixes)

    items: list[BrowseItem] = []

    for blob in blobs:
        name = blob.name.split("/")[-1]
        if not name or name == ".keep":
            continue
        rel_path = _strip_case_prefix(blob.name, case_id)
        items.append(BrowseItem(
            name=name,
            path=rel_path,
            type="file",
            size_bytes=blob.size,
            updated_at=blob.updated.isoformat() if blob.updated else None,
        ))

    for folder_prefix in prefixes:
        # folder_prefix looks like "{case_id}/medical-records/"
        rel_path = _strip_case_prefix(folder_prefix, case_id).rstrip("/")
        name = rel_path.split("/")[-1]
        if not name:
            continue
        items.append(BrowseItem(
            name=name,
            path=rel_path,
            type="folder",
        ))

    # Sort: folders first, then files; alphabetically within each group
    items.sort(key=lambda x: (0 if x.type == "folder" else 1, x.name.lower()))

    log_audit_event(
        action=AuditAction.browse_folder,
        request=request,
        case_id=case_id,
        metadata={"path": path, "items_returned": len(items)},
    )

    return BrowseResponse(case_id=case_id, path=path, items=items)


@router.post(
    "/cases/{case_id}/folders",
    response_model=CreateFolderResponse,
    status_code=201,
    summary="Create a folder within the case GCS directory",
)
def create_folder(
    request: Request,
    case_id: str,
    body: CreateFolderRequest,
):
    """
    Creates a folder by uploading an empty .keep placeholder object.
    Also ensures the case root .keep exists so the case directory is visible.
    """
    bucket = _get_bucket()

    # Ensure the case root is anchored
    root_keep = bucket.blob(f"{case_id}/.keep")
    if not root_keep.exists():
        root_keep.upload_from_string(b"", content_type="application/octet-stream")

    folder_keep = bucket.blob(f"{case_id}/{body.path}/.keep")
    folder_keep.upload_from_string(b"", content_type="application/octet-stream")

    log_audit_event(
        action=AuditAction.create_folder,
        request=request,
        case_id=case_id,
        resource=f"{case_id}/{body.path}/",
        metadata={"path": body.path},
    )

    return CreateFolderResponse(created=True, path=body.path)


@router.post(
    "/cases/{case_id}/move",
    response_model=MoveResponse,
    summary="Move a file or folder within the case GCS directory",
)
def move_item(
    request: Request,
    case_id: str,
    body: MoveRequest,
):
    """
    Moves a file or folder to a new path within the same case directory.

    For folders: copies all blobs under source prefix, then deletes originals.
    For files: copies the single blob, then deletes the original.
    """
    bucket = _get_bucket()
    full_source = f"{case_id}/{body.source_path}"
    full_dest = f"{case_id}/{body.destination_path}"

    # Detect folder by checking for children under source prefix
    children = list(bucket.list_blobs(prefix=f"{full_source}/"))

    if children:
        # Folder move: copy all children to new prefix, then delete originals
        for blob in children:
            suffix = blob.name[len(full_source):]  # e.g. "/.keep" or "/subdir/file.pdf"
            new_name = full_dest + suffix
            bucket.copy_blob(blob, bucket, new_name)
        for blob in children:
            blob.delete()
    else:
        # File move
        src_blob = bucket.blob(full_source)
        bucket.copy_blob(src_blob, bucket, full_dest)
        src_blob.delete()

    log_audit_event(
        action=AuditAction.move_item,
        request=request,
        case_id=case_id,
        resource=full_dest,
        metadata={
            "source_path": body.source_path,
            "destination_path": body.destination_path,
            "items_moved": len(children) if children else 1,
        },
    )

    return MoveResponse(moved=True, destination=body.destination_path)
