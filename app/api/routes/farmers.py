"""Farmer management API routes."""

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.user import UserRole
from app.schemas.farmer import (
    FarmerBulkImportResult,
    FarmerCreate,
    FarmerListResponse,
    FarmerRead,
    FarmerUpdate,
)
from app.schemas.job import JobRead
from app.schemas.land_parcel import LandParcelRead
from app.services import farmer_service, job_service, parcel_service
from app.services.parcel_service import FarmerNotFoundError

router = APIRouter(prefix="/farmers", tags=["Farmers"])

# Role-based dependencies
CanManageFarmers = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.FIELD_OFFICER)),
]
CanDeleteFarmers = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN)),
]


@router.post(
    "",
    response_model=FarmerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new farmer",
    description="Requires admin or field_officer role. Farmer consent is mandatory.",
)
def create_farmer(
    farmer_in: FarmerCreate,
    db: SessionDep,
    _current_user: CanManageFarmers,
) -> FarmerRead:
    """Create a new farmer in the MRV system."""
    new_farmer = farmer_service.create_farmer(db, farmer_in)
    return new_farmer


@router.post(
    "/bulk-import",
    response_model=FarmerBulkImportResult,
    summary="Bulk import farmers from CSV",
    description="Upload a CSV file containing farmer records. Each row is validated independently; bad rows do not halt the import.",
)
async def bulk_import_farmers(
    db: SessionDep,
    _current_user: CanManageFarmers,
    file: UploadFile = File(..., description="CSV file containing farmer records"),
) -> FarmerBulkImportResult:
    """Bulk upload and parse farmer records from a CSV file."""
    if file.filename and not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a CSV file (.csv).",
        )
    contents = await file.read()
    return farmer_service.bulk_import_farmers_from_csv(db, contents)


@router.post(
    "/bulk-import-async",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Asynchronously bulk import farmers via background job",
    description="Enqueue a background job to import farmers from a CSV file. Returns HTTP 202 with a job ticket ID.",
)
async def bulk_import_farmers_async(
    db: SessionDep,
    _current_user: CanManageFarmers,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="CSV file containing farmer records"),
) -> JobRead:
    """Queue an asynchronous CSV import job and return immediately with HTTP 202 Accepted."""
    if file.filename and not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a CSV file (.csv).",
        )
    contents = await file.read()
    job = job_service.create_job(
        db,
        job_type="farmer_bulk_import",
        payload={"filename": file.filename, "size_bytes": len(contents)},
    )
    background_tasks.add_task(
        job_service.process_farmer_bulk_import_job,
        job.id,
        contents,
    )
    return JobRead.model_validate(job)


@router.get(
    "/{farmer_id}",
    response_model=FarmerRead,
    summary="Get farmer by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_farmer(
    farmer_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> FarmerRead:
    """Fetch farmer details by primary key ID."""
    farmer = farmer_service.get_farmer_by_id(db, farmer_id=farmer_id)
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer with id {farmer_id} not found",
        )
    return farmer


@router.get(
    "/{farmer_id}/parcels",
    response_model=list[LandParcelRead],
    summary="Get all parcels belonging to a farmer",
    description="Accessible by all authenticated roles. Returns all parcels owned by the active farmer.",
)
def get_farmer_parcels(
    farmer_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> list[LandParcelRead]:
    """Retrieve all land parcels associated with a farmer."""
    try:
        return parcel_service.get_parcels_by_farmer(db, farmer_id=farmer_id)
    except FarmerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=FarmerListResponse,
    summary="List farmers with pagination, filtering, and search",
    description="Returns paginated farmers matching district, state, or name search filters.",
)
def list_farmers(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    district: str | None = Query(default=None, description="Filter by district name"),
    state: str | None = Query(default=None, description="Filter by state / province"),
    search: str | None = Query(default=None, description="Search farmer by name substring"),
) -> FarmerListResponse:
    """List farmers with pagination and filters."""
    items, total = farmer_service.list_farmers(
        db,
        page=page,
        page_size=page_size,
        district=district,
        state=state,
        search=search,
    )
    return FarmerListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{farmer_id}",
    response_model=FarmerRead,
    summary="Update farmer information",
    description="Requires admin or field_officer role.",
)
def update_farmer(
    farmer_id: int,
    update_in: FarmerUpdate,
    db: SessionDep,
    _current_user: CanManageFarmers,
) -> FarmerRead:
    """Partially update farmer attributes."""
    farmer = farmer_service.get_farmer_by_id(db, farmer_id=farmer_id)
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer with id {farmer_id} not found",
        )
    updated_farmer = farmer_service.update_farmer(db, farmer=farmer, update_in=update_in)
    return updated_farmer


@router.delete(
    "/{farmer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete a farmer",
    description="Administrative action. Complies with MRV rules: marks is_deleted=True without purging DB rows.",
)
def delete_farmer(
    farmer_id: int,
    db: SessionDep,
    _current_user: CanDeleteFarmers,
) -> Response:
    """Soft delete a farmer by ID."""
    farmer = farmer_service.get_farmer_by_id(db, farmer_id=farmer_id)
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer with id {farmer_id} not found",
        )
    farmer_service.soft_delete_farmer(db, farmer=farmer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
