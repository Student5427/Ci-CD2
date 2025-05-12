from datetime import timedelta
from typing import List

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps import get_db
from app.api.schemas.user import UserCreate
from app.api.schemas.user import UserSchema
from app.core import security
from app.core.config import settings
from app.db.cruds import crud_user
from app.services.messaging.email import send_email

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


router = APIRouter()


@router.post("/token", tags=["auth"])
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = security.authenticate_user(
        db=db, username=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get(
    "/users",
    response_model=List[UserSchema],
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    users = crud_user.get_users(db=db, skip=skip, limit=limit)
    return users


@router.get("/users/me", response_model=UserSchema, tags=["users"])
def read_users_me(
    current_user: UserSchema = Depends(get_current_user), db: Session = Depends(get_db)
):
    with tracer.start_as_current_span("user_profile_request") as parent_span:
        try:
            # Устанавливаем атрибуты для родительского спана
            parent_span.set_attributes(
                {"user.id": str(current_user.id), "user.email": current_user.email}
            )

            with tracer.start_as_current_span("validate_session"):
                if not current_user.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive"
                    )

            # Важно: возвращаем полный объект current_user, а не частичный
            return current_user

        except Exception as e:
            # Записываем ошибку в спан
            parent_span.record_exception(e)
            parent_span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise


@router.get("/users/{user_id}", response_model=UserSchema, tags=["users"])
def read_user(user_id: int, db: Session = Depends(get_db)):
    db_user = crud_user.get_user(db=db, user_id=user_id)
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return db_user


@router.post("/users", response_model=UserSchema, tags=["users"])
def create_user(
    user: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    with tracer.start_as_current_span("create_user_operation") as parent_span:
        with tracer.start_as_current_span("check_email_exists"):
            db_user = crud_user.get_user_by_email(db=db, email=user.email)
            if db_user:
                raise HTTPException(status_code=400, detail="Email already registered")

        with tracer.start_as_current_span("create_user_record"):
            new_user = crud_user.create_user(db=db, user=user)

        if settings.SMTP_SERVER != "your_stmp_server_here":
            with tracer.start_as_current_span("send_welcome_email"):
                background_tasks.add_task(
                    send_email, user.email, message="You've created your account!"
                )

        return new_user


@router.delete("/users/{user_id}", tags=["admin"])
def remove_user(user_id: int, db: Session = Depends(get_db)):
    db_user = crud_user.get_user(db=db, user_id=user_id)
    if not db_user:
        raise HTTPException(status_code=400, detail="User not found")
    crud_user.delete_user(db=db, user=db_user)
    return {"detail": f"User with id {db_user.id} successfully deleted"}
