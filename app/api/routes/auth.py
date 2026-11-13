"""Authentication and user registration API routes."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, OptionalUserDep, SessionDep
from app.core.security import create_access_token
from app.models.user import UserRole
from app.schemas.user import LoginRequest, Token, UserCreate, UserRead
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Allows public registration only for the very first user (bootstrapped as admin). "
    "Subsequent user registrations require an authenticated administrator.",
)
def register(
    user_in: UserCreate,
    db: SessionDep,
    current_user: OptionalUserDep,
) -> UserRead:
    """Register a new user in the system."""
    total_users = user_service.count_users(db)

    # Business rule: after the first user exists, only admins can register users
    if total_users > 0:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to register new users",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can register new users",
            )

    # Prevent duplicate email addresses
    existing_user = user_service.get_user_by_email(db, user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{user_in.email}' already exists",
        )

    # First user automatically becomes admin
    if total_users == 0:
        user_in.role = UserRole.ADMIN

    new_user = user_service.create_user(db, user_in)
    return new_user


@router.post(
    "/login",
    response_model=Token,
    summary="Authenticate and receive a JWT access token",
)
def login(
    login_data: LoginRequest,
    db: SessionDep,
) -> Token:
    """Validate credentials and return a signed Bearer token."""
    user = user_service.authenticate_user(
        db,
        email=login_data.email,
        password=login_data.password,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        subject=user.id,
        role=user.role.value,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get profile of current authenticated user",
)
def read_current_user_profile(
    current_user: CurrentUserDep,
) -> UserRead:
    """Return profile attributes of the currently authenticated user."""
    return current_user
