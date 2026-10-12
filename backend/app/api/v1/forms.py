from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models.enums import AuditAction, FormScope, FormStatus
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import audit
from ...services.forms import (
    AnswerInput,
    FormService,
    QuestionSpec,
    Target,
    apply_status,
    can_create,
    can_manage,
    can_view_results,
    clean_description,
    clean_questions,
    clean_title,
    require_id,
)
from ...services.serializers import iso, sid
from ..deps import Auth, get_db, get_outbox, require_auth

router = APIRouter(prefix="/forms", tags=["forms"])
CREATE_LIMIT = (20, 3600)
SUBMIT_LIMIT = (30, 600)
LIST_LIMIT = (120, 60)


class FormClassTarget(BaseModel):
    type: Literal["class"]
    class_id: str = Field(max_length=24)


class FormSchoolTarget(BaseModel):
    type: Literal["school"]


class FormQuestionBody(BaseModel):
    type: Literal["short_text", "long_text", "single_choice", "multiple_choice"]
    label: str = Field(max_length=1000)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)


class FormCreateBody(BaseModel):
    title: str = Field(max_length=1000)
    description: str = Field(default="", max_length=8000)
    target: Annotated[FormClassTarget | FormSchoolTarget, Field(discriminator="type")]
    questions: list[FormQuestionBody] = Field(max_length=100)


class FormUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=8000)
    status: Literal["open", "closed"] | None = None


class FormAnswerBody(BaseModel):
    question_id: str = Field(max_length=24)
    text: str | None = Field(default=None, max_length=8000)
    options: list[str] = Field(default_factory=list, max_length=32)


class FormSubmitBody(BaseModel):
    answers: list[FormAnswerBody] = Field(max_length=100)


def parse_target(body: FormClassTarget | FormSchoolTarget) -> Target:
    if isinstance(body, FormSchoolTarget):
        return Target(FormScope.SCHOOL)
    class_id = require_id(body.class_id)
    if class_id is None:
        raise AppError("validation_error", 422)
    return Target(FormScope.CLASS, class_id)


@router.get("")
async def list_forms(request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    service: FormService = request.app.state.forms
    enforce(request, "form-list", *LIST_LIMIT, subject=str(auth.user.id))
    return {"items": await service.listing(db, auth.user)}


@router.post("")
async def create_form(
    body: FormCreateBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict:
    user = auth.user
    service: FormService = request.app.state.forms
    if not can_create(user):
        raise AppError("form_create_forbidden", 403)
    title = clean_title(body.title)
    description = clean_description(body.description)
    specs = clean_questions([QuestionSpec(type=q.type, label=q.label, required=q.required, options=list(q.options)) for q in body.questions])
    target = parse_target(body.target)
    school_class = await service.resolve_class(db, target.school_class_id) if target.scope is FormScope.CLASS else None
    enforce(request, "form-create", *CREATE_LIMIT, subject=str(user.id))
    form, questions = await service.create(db, user, target, title, description, specs)
    audience = await service.audience_ids(db, form)
    await service.announce(db, outbox, form, user, audience, school_class.code if school_class else None)
    audit.record(
        db,
        AuditAction.FORM_CREATE,
        actor_id=user.id,
        target_type="form",
        target_id=form.id,
        details={
            "title": form.title,
            "scope": form.target_scope,
            "class_id": sid(form.school_class_id),
            "questions": len(questions),
            "audience": sum(1 for user_id in audience if user_id != user.id),
        },
    )
    payload = await service.detail(db, user, form, questions)
    await db.commit()
    await outbox.flush()
    return payload


@router.get("/{form_id}")
async def get_form(form_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    service: FormService = request.app.state.forms
    form = await service.require_visible(db, auth.user, form_id)
    return await service.detail(db, auth.user, form)


@router.get("/{form_id}/me")
async def my_state(form_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    service: FormService = request.app.state.forms
    form = await service.require_visible(db, auth.user, form_id)
    return await service.my_state(db, auth.user, form)


@router.patch("/{form_id}")
async def update_form(
    form_id: int,
    body: FormUpdateBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict:
    user = auth.user
    service: FormService = request.app.state.forms
    form = await service.require_visible(db, user, form_id)
    if not can_manage(user, form):
        raise AppError("form_manage_forbidden", 403)
    title = clean_title(body.title) if body.title is not None else None
    description = clean_description(body.description) if body.description is not None else None
    edited: list[str] = []
    if title is not None and title != form.title:
        form.title = title
        edited.append("title")
    if description is not None and description != form.description:
        form.description = description
        edited.append("description")
    if edited:
        audit.record(db, AuditAction.FORM_UPDATE, actor_id=user.id, target_type="form", target_id=form.id, details={"fields": edited, "title": form.title})
    switched = False
    if body.status is not None:
        status = FormStatus(body.status)
        if apply_status(form, status):
            switched = True
            action = AuditAction.FORM_CLOSE if status is FormStatus.CLOSED else AuditAction.FORM_REOPEN
            responses = await service.response_count(db, form.id)
            audit.record(db, action, actor_id=user.id, target_type="form", target_id=form.id, details={"title": form.title, "responses": responses})
    if edited or switched:
        audience = await service.audience_ids(db, form)
        service.broadcast(outbox, form.id, audience, user.id, form.creator_id)
    payload = await service.detail(db, user, form)
    await db.commit()
    await outbox.flush()
    return payload


@router.delete("/{form_id}")
async def delete_form(
    form_id: int,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict[str, str]:
    user = auth.user
    service: FormService = request.app.state.forms
    form = await service.require_visible(db, user, form_id)
    if not can_manage(user, form):
        raise AppError("form_manage_forbidden", 403)
    removed_id = form.id
    creator_id = form.creator_id
    audience = await service.audience_ids(db, form)
    responses = await service.response_count(db, form.id)
    audit.record(
        db,
        AuditAction.FORM_DELETE,
        actor_id=user.id,
        target_type="form",
        target_id=form.id,
        details={"title": form.title, "scope": form.target_scope, "class_id": sid(form.school_class_id), "responses": responses},
    )
    await service.purge(db, form)
    service.broadcast(outbox, removed_id, audience, user.id, creator_id)
    await db.commit()
    await outbox.flush()
    return {"status": "deleted"}


@router.post("/{form_id}/responses")
async def submit_form(
    form_id: int,
    body: FormSubmitBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict:
    user = auth.user
    service: FormService = request.app.state.forms
    form = await service.require_target(db, user, form_id)
    enforce(request, "form-submit", *SUBMIT_LIMIT, subject=str(user.id))
    answers = [AnswerInput(question_id=item.question_id, text=item.text, options=list(item.options)) for item in body.answers]
    response = await service.submit(db, form, user, answers)
    service.broadcast(outbox, form.id, [], user.id, form.creator_id)
    await db.commit()
    await outbox.flush()
    return {"form_id": sid(form.id), "submitted": True, "submitted_at": iso(response.submitted_at)}


@router.get("/{form_id}/responses")
async def form_results(
    form_id: int,
    request: Request,
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = auth.user
    service: FormService = request.app.state.forms
    form = await service.require_visible(db, user, form_id)
    if not can_view_results(user, form):
        raise AppError("form_results_forbidden", 403)
    enforce(request, "form-results", *LIST_LIMIT, subject=str(user.id))
    cursor = require_id(before)
    payload = await service.results(db, form, before=cursor, limit=limit)
    if cursor is None and form.creator_id != user.id:
        audit.record(db, AuditAction.FORM_RESULTS_VIEW, actor_id=user.id, target_type="form", target_id=form.id, details={"title": form.title, "responses": payload["total"]})
        await db.commit()
    return payload
