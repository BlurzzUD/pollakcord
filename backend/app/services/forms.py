import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto.envelope import DecryptionError, Vault
from ..db.types import utcnow
from ..errors import AppError
from ..ids import new_id
from ..logging_config import get_logger
from ..models import Form, FormAnswer, FormQuestion, FormResponse, Notification, SchoolClass, User, UserSettings
from ..models.enums import STAFF_ROLES, AccountStatus, FormQuestionType, FormScope, FormStatus, NotificationType, PlatformRole
from ..realtime.outbox import Outbox
from . import people
from .notifications import notify
from .serializers import iso, sid

logger = get_logger("pollakcord.forms")
PURPOSE = "form-answer"
EVENT = "form.changed"
MAX_ID = 2**63 - 1
MAX_PAGE = 100
LIST_ROWS = 200
SETTINGS_CHUNK = 500
TITLE_MAX = 120
DESCRIPTION_MAX = 1000
MAX_QUESTIONS = 30
QUESTION_LABEL_MAX = 200
MIN_OPTIONS = 2
MAX_OPTIONS = 12
OPTION_LABEL_MAX = 100
SHORT_TEXT_MAX = 200
LONG_TEXT_MAX = 2000
CREATOR_ROLES = STAFF_ROLES | {PlatformRole.DOK_PRESIDENT.value}
TEXT_TYPES = frozenset({FormQuestionType.SHORT_TEXT.value, FormQuestionType.LONG_TEXT.value})
CHOICE_TYPES = frozenset({FormQuestionType.SINGLE_CHOICE.value, FormQuestionType.MULTIPLE_CHOICE.value})


@dataclass(frozen=True)
class Target:
    scope: FormScope
    school_class_id: int | None = None


@dataclass(frozen=True)
class QuestionSpec:
    type: str
    label: str
    required: bool
    options: list[str]


@dataclass(frozen=True)
class AnswerInput:
    question_id: str
    text: str | None
    options: list[str]


def parse_id(raw: str) -> int | None:
    if not raw.isascii() or not raw.isdigit() or len(raw) > 19:
        return None
    value = int(raw)
    return value if 0 < value <= MAX_ID else None


def require_id(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = parse_id(raw)
    if value is None:
        raise AppError("validation_error", 422)
    return value


def dedupe_key(form_id: int) -> str:
    return f"form:{form_id}"


def has_control(text: str, allow_newline: bool = False) -> bool:
    return any(unicodedata.category(char) == "Cc" and not (allow_newline and char == "\n") for char in text)


def clean_line(raw: str) -> str:
    return " ".join(raw.replace("\x00", "").split())


def clean_title(raw: str) -> str:
    title = clean_line(raw)
    if not title or len(title) > TITLE_MAX or has_control(title):
        raise AppError("form_title_invalid", 422, params={"max": TITLE_MAX})
    return title


def clean_description(raw: str) -> str:
    text = raw.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ").strip()
    if len(text) > DESCRIPTION_MAX or has_control(text, allow_newline=True):
        raise AppError("form_description_invalid", 422, params={"max": DESCRIPTION_MAX})
    return text


def clean_options(raw: list[str]) -> list[str]:
    options = [clean_line(option) for option in raw]
    valid = (
        MIN_OPTIONS <= len(options) <= MAX_OPTIONS
        and all(option and len(option) <= OPTION_LABEL_MAX and not has_control(option) for option in options)
        and len({option.casefold() for option in options}) == len(options)
    )
    if not valid:
        raise AppError("form_options_invalid", 422, params={"min": MIN_OPTIONS, "max": MAX_OPTIONS, "label_max": OPTION_LABEL_MAX})
    return options


def clean_questions(specs: list[QuestionSpec]) -> list[QuestionSpec]:
    if not 1 <= len(specs) <= MAX_QUESTIONS:
        raise AppError("form_questions_invalid", 422, params={"max": MAX_QUESTIONS})
    cleaned: list[QuestionSpec] = []
    for spec in specs:
        label = clean_line(spec.label)
        if not label or len(label) > QUESTION_LABEL_MAX or has_control(label):
            raise AppError("form_question_invalid", 422, params={"max": QUESTION_LABEL_MAX})
        options = clean_options(spec.options) if spec.type in CHOICE_TYPES else []
        cleaned.append(QuestionSpec(type=spec.type, label=label, required=spec.required, options=options))
    return cleaned


def can_create(user: User) -> bool:
    return user.platform_role in CREATOR_ROLES


def is_target(user: User, form: Form) -> bool:
    if user.school_class_id is None:
        return False
    return form.target_scope == FormScope.SCHOOL.value or form.school_class_id == user.school_class_id


def is_owner(user: User, form: Form) -> bool:
    return form.creator_id == user.id and user.platform_role in CREATOR_ROLES


def can_manage(user: User, form: Form) -> bool:
    return user.platform_role == PlatformRole.SCHOOL_ADMIN.value or is_owner(user, form)


def can_view_results(user: User, form: Form) -> bool:
    return user.platform_role in STAFF_ROLES or is_owner(user, form)


def can_view(user: User, form: Form) -> bool:
    return is_target(user, form) or can_view_results(user, form)


def target_dict(form: Form, school_class: SchoolClass | None) -> dict[str, Any]:
    if form.target_scope == FormScope.CLASS.value:
        return {"type": FormScope.CLASS.value, "class_id": sid(form.school_class_id), "code": school_class.code if school_class else None}
    return {"type": FormScope.SCHOOL.value}


def apply_status(form: Form, status: FormStatus) -> bool:
    if form.status == status.value:
        return False
    form.status = status.value
    form.closed_at = utcnow() if status is FormStatus.CLOSED else None
    return True


class FormService:
    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    @staticmethod
    def _aad(form_id: int, response_id: int, question_id: int) -> bytes:
        return f"form|{form_id}|{response_id}|{question_id}".encode()

    def _seal(self, form_id: int, response_id: int, question_id: int, value: dict[str, Any]) -> tuple[bytes, str]:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._vault.encrypt(PURPOSE, raw, self._aad(form_id, response_id, question_id))

    def _open(self, form_id: int, answer: FormAnswer) -> dict[str, Any] | None:
        try:
            raw = self._vault.decrypt(PURPOSE, answer.value_enc, self._aad(form_id, answer.response_id, answer.question_id), answer.key_id)
            value = json.loads(raw.decode("utf-8"))
        except (DecryptionError, ValueError):
            logger.error("form_decrypt_failed", extra={"form_id": form_id, "question_id": answer.question_id})
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    async def resolve_class(db: AsyncSession, class_id: int) -> SchoolClass:
        school_class = await db.get(SchoolClass, class_id) if 0 < class_id <= MAX_ID else None
        if school_class is None or not school_class.is_active:
            raise AppError("not_found", 404)
        return school_class

    @staticmethod
    async def load(db: AsyncSession, form_id: int) -> Form | None:
        return await db.get(Form, form_id) if 0 < form_id <= MAX_ID else None

    async def require_visible(self, db: AsyncSession, viewer: User, form_id: int) -> Form:
        form = await self.load(db, form_id)
        if form is None or not can_view(viewer, form):
            raise AppError("not_found", 404)
        return form

    async def require_target(self, db: AsyncSession, viewer: User, form_id: int) -> Form:
        form = await self.load(db, form_id)
        if form is None or not is_target(viewer, form):
            raise AppError("not_found", 404)
        return form

    @staticmethod
    async def questions_for(db: AsyncSession, form_ids: list[int]) -> dict[int, list[FormQuestion]]:
        if not form_ids:
            return {}
        statement = select(FormQuestion).where(FormQuestion.form_id.in_(form_ids)).order_by(FormQuestion.form_id, FormQuestion.position)
        grouped: dict[int, list[FormQuestion]] = {}
        for row in (await db.execute(statement)).scalars():
            grouped.setdefault(row.form_id, []).append(row)
        return grouped

    @staticmethod
    async def response_count(db: AsyncSession, form_id: int) -> int:
        statement = select(func.count()).select_from(FormResponse).where(FormResponse.form_id == form_id)
        return (await db.execute(statement)).scalar_one()

    @staticmethod
    async def _response_counts(db: AsyncSession, form_ids: list[int]) -> dict[int, int]:
        if not form_ids:
            return {}
        statement = select(FormResponse.form_id, func.count()).where(FormResponse.form_id.in_(form_ids)).group_by(FormResponse.form_id)
        return {form_id: count for form_id, count in (await db.execute(statement)).all()}

    @staticmethod
    async def create(
        db: AsyncSession,
        creator: User,
        target: Target,
        title: str,
        description: str,
        specs: list[QuestionSpec],
    ) -> tuple[Form, list[FormQuestion]]:
        form = Form(
            creator_id=creator.id,
            creator_role=creator.platform_role,
            title=title,
            description=description,
            target_scope=target.scope.value,
            school_class_id=target.school_class_id,
            status=FormStatus.OPEN.value,
        )
        db.add(form)
        await db.flush()
        questions: list[FormQuestion] = []
        for position, spec in enumerate(specs):
            question = FormQuestion(
                form_id=form.id,
                position=position,
                type=spec.type,
                label=spec.label,
                required=spec.required,
                options=[{"id": str(new_id()), "label": label} for label in spec.options],
            )
            db.add(question)
            questions.append(question)
        await db.flush()
        return form, questions

    @staticmethod
    async def audience_ids(db: AsyncSession, form: Form) -> list[int]:
        statement = select(User.id).where(User.status == AccountStatus.ACTIVE.value, User.is_bot.is_(False))
        if form.target_scope == FormScope.CLASS.value:
            statement = statement.where(User.school_class_id == form.school_class_id)
        else:
            statement = statement.where(User.school_class_id.is_not(None))
        return list((await db.execute(statement)).scalars())

    @staticmethod
    async def _prime_settings(db: AsyncSession, user_ids: list[int]) -> None:
        for start in range(0, len(user_ids), SETTINGS_CHUNK):
            await db.execute(select(UserSettings).where(UserSettings.user_id.in_(user_ids[start : start + SETTINGS_CHUNK])))

    @staticmethod
    def broadcast(outbox: Outbox, form_id: int, audience: list[int], *extra: int | None) -> None:
        recipients = {*audience, *(user_id for user_id in extra if user_id is not None)}
        outbox.users(recipients, EVENT, {"form_id": sid(form_id)})

    async def announce(
        self,
        db: AsyncSession,
        outbox: Outbox,
        form: Form,
        creator: User,
        audience: list[int],
        class_code: str | None,
    ) -> None:
        payload = {"form_id": sid(form.id), "title": form.title, "scope": form.target_scope, "class_code": class_code}
        recipients = [user_id for user_id in audience if user_id != creator.id]
        await self._prime_settings(db, recipients)
        for user_id in recipients:
            await notify(db, outbox, user_id, NotificationType.FORM_AVAILABLE, payload, dedupe_key=dedupe_key(form.id))
        self.broadcast(outbox, form.id, audience, creator.id)

    @staticmethod
    async def visible_forms(db: AsyncSession, viewer: User) -> list[Form]:
        statement = select(Form).order_by(Form.id.desc()).limit(LIST_ROWS)
        if viewer.platform_role not in STAFF_ROLES:
            condition = false()
            if viewer.school_class_id is not None:
                condition = or_(Form.target_scope == FormScope.SCHOOL.value, Form.school_class_id == viewer.school_class_id)
            if viewer.platform_role == PlatformRole.DOK_PRESIDENT.value:
                condition = or_(Form.creator_id == viewer.id, condition)
            statement = statement.where(condition)
        return list((await db.execute(statement)).scalars())

    @staticmethod
    def question_dict(question: FormQuestion) -> dict[str, Any]:
        return {
            "id": sid(question.id),
            "position": question.position,
            "type": question.type,
            "label": question.label,
            "required": question.required,
            "options": [{"id": option["id"], "label": option["label"]} for option in question.options],
        }

    async def summaries(self, db: AsyncSession, viewer: User, forms: list[Form]) -> list[dict[str, Any]]:
        if not forms:
            return []
        ids = [form.id for form in forms]
        class_ids = {form.school_class_id for form in forms if form.school_class_id is not None}
        classes = (
            {row.id: row for row in (await db.execute(select(SchoolClass).where(SchoolClass.id.in_(class_ids)))).scalars()} if class_ids else {}
        )
        submitted: dict[int, datetime] = {
            form_id: at
            for form_id, at in (
                await db.execute(select(FormResponse.form_id, FormResponse.submitted_at).where(FormResponse.user_id == viewer.id, FormResponse.form_id.in_(ids)))
            ).all()
        }
        question_counts = {
            form_id: count
            for form_id, count in (
                await db.execute(select(FormQuestion.form_id, func.count()).where(FormQuestion.form_id.in_(ids)).group_by(FormQuestion.form_id))
            ).all()
        }
        viewable = [form for form in forms if can_view_results(viewer, form)]
        response_counts = await self._response_counts(db, [form.id for form in viewable])
        creators = await people.load_cards(db, {form.creator_id for form in viewable if form.creator_id is not None})
        items = []
        for form in forms:
            targeted = is_target(viewer, form)
            may_view = can_view_results(viewer, form)
            at = submitted.get(form.id)
            items.append(
                {
                    "id": sid(form.id),
                    "title": form.title,
                    "description": form.description,
                    "target": target_dict(form, classes.get(form.school_class_id) if form.school_class_id is not None else None),
                    "status": form.status,
                    "creator_role": form.creator_role,
                    "created_at": iso(form.created_at),
                    "closed_at": iso(form.closed_at),
                    "question_count": question_counts.get(form.id, 0),
                    "targeted": targeted,
                    "submitted": at is not None,
                    "submitted_at": iso(at),
                    "can_fill": targeted and form.status == FormStatus.OPEN.value and at is None,
                    "can_manage": can_manage(viewer, form),
                    "can_view_results": may_view,
                    "response_count": response_counts.get(form.id, 0) if may_view else None,
                    "creator": creators.get(form.creator_id) if may_view and form.creator_id is not None else None,
                }
            )
        return items

    async def listing(self, db: AsyncSession, viewer: User) -> list[dict[str, Any]]:
        return await self.summaries(db, viewer, await self.visible_forms(db, viewer))

    async def detail(self, db: AsyncSession, viewer: User, form: Form, questions: list[FormQuestion] | None = None) -> dict[str, Any]:
        summary = (await self.summaries(db, viewer, [form]))[0]
        rows = questions if questions is not None else (await self.questions_for(db, [form.id])).get(form.id, [])
        return {**summary, "questions": [self.question_dict(question) for question in rows]}

    @staticmethod
    async def my_state(db: AsyncSession, viewer: User, form: Form) -> dict[str, Any]:
        statement = select(FormResponse.submitted_at).where(FormResponse.form_id == form.id, FormResponse.user_id == viewer.id)
        at = (await db.execute(statement)).scalar_one_or_none()
        targeted = is_target(viewer, form)
        return {
            "form_id": sid(form.id),
            "status": form.status,
            "targeted": targeted,
            "submitted": at is not None,
            "submitted_at": iso(at),
            "can_fill": targeted and form.status == FormStatus.OPEN.value and at is None,
        }

    @staticmethod
    def _clean_text(kind: str, raw: str | None) -> dict[str, Any] | None:
        if raw is None:
            return None
        text = raw.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return None
        single_line = kind == FormQuestionType.SHORT_TEXT.value
        if single_line and "\n" in text:
            raise AppError("form_answer_invalid", 422)
        limit = SHORT_TEXT_MAX if single_line else LONG_TEXT_MAX
        if len(text) > limit:
            raise AppError("form_answer_too_long", 422, params={"max": limit})
        return {"text": text}

    @staticmethod
    def _clean_choice(question: FormQuestion, selected: list[str]) -> dict[str, Any] | None:
        if not selected:
            return None
        known = {option["id"] for option in question.options}
        if any(option not in known for option in selected):
            raise AppError("form_option_unknown", 422)
        single = question.type == FormQuestionType.SINGLE_CHOICE.value
        if len(set(selected)) != len(selected) or (single and len(selected) != 1):
            raise AppError("form_answer_invalid", 422)
        chosen = set(selected)
        return {"options": [option["id"] for option in question.options if option["id"] in chosen]}

    def clean_answers(self, questions: list[FormQuestion], answers: list[AnswerInput]) -> dict[int, dict[str, Any]]:
        by_id = {question.id: question for question in questions}
        given: dict[int, AnswerInput] = {}
        for answer in answers:
            question_id = parse_id(answer.question_id)
            if question_id is None or question_id not in by_id or question_id in given:
                raise AppError("form_answer_invalid", 422)
            given[question_id] = answer
        values: dict[int, dict[str, Any]] = {}
        for question in questions:
            answer = given.get(question.id)
            value: dict[str, Any] | None = None
            if answer is not None and question.type in TEXT_TYPES:
                if answer.options:
                    raise AppError("form_answer_invalid", 422)
                value = self._clean_text(question.type, answer.text)
            elif answer is not None:
                if answer.text:
                    raise AppError("form_answer_invalid", 422)
                value = self._clean_choice(question, answer.options)
            if value is None:
                if question.required:
                    raise AppError("form_answer_required", 422)
                continue
            values[question.id] = value
        return values

    async def submit(self, db: AsyncSession, form: Form, user: User, answers: list[AnswerInput]) -> FormResponse:
        if form.status != FormStatus.OPEN.value:
            raise AppError("form_closed", 409)
        existing = (await db.execute(select(FormResponse.id).where(FormResponse.form_id == form.id, FormResponse.user_id == user.id))).first()
        if existing is not None:
            raise AppError("form_already_submitted", 409)
        questions = (await self.questions_for(db, [form.id])).get(form.id, [])
        values = self.clean_answers(questions, answers)
        response = FormResponse(id=new_id(), form_id=form.id, user_id=user.id)
        db.add(response)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise AppError("form_already_submitted", 409) from exc
        for question_id, value in values.items():
            value_enc, key_id = self._seal(form.id, response.id, question_id, value)
            db.add(FormAnswer(response_id=response.id, question_id=question_id, value_enc=value_enc, key_id=key_id))
        await db.flush()
        return response

    async def _answers_for(self, db: AsyncSession, form_id: int, response_ids: list[int]) -> dict[int, dict[int, dict[str, Any] | None]]:
        if not response_ids:
            return {}
        grouped: dict[int, dict[int, dict[str, Any] | None]] = {}
        rows = (await db.execute(select(FormAnswer).where(FormAnswer.response_id.in_(response_ids)))).scalars()
        for row in rows:
            grouped.setdefault(row.response_id, {})[row.question_id] = self._open(form_id, row)
        return grouped

    async def _summary(self, db: AsyncSession, form: Form, questions: list[FormQuestion]) -> list[dict[str, Any]]:
        if not questions:
            return []
        question_ids = [question.id for question in questions]
        counted = select(FormAnswer.question_id, func.count()).where(FormAnswer.question_id.in_(question_ids)).group_by(FormAnswer.question_id)
        answered = {question_id: count for question_id, count in (await db.execute(counted)).all()}
        tallies: dict[int, dict[str, int]] = {
            question.id: {option["id"]: 0 for option in question.options} for question in questions if question.type in CHOICE_TYPES
        }
        if tallies:
            rows = (await db.execute(select(FormAnswer).where(FormAnswer.question_id.in_(list(tallies))))).scalars()
            for row in rows:
                value = self._open(form.id, row)
                selected = value.get("options") if value else None
                if not isinstance(selected, list):
                    continue
                for option_id in selected:
                    if isinstance(option_id, str) and option_id in tallies[row.question_id]:
                        tallies[row.question_id][option_id] += 1
        return [
            {
                "question_id": sid(question.id),
                "type": question.type,
                "answered": answered.get(question.id, 0),
                "options": [
                    {"id": option["id"], "label": option["label"], "count": tallies.get(question.id, {}).get(option["id"], 0)}
                    for option in question.options
                ],
            }
            for question in questions
        ]

    async def results(self, db: AsyncSession, form: Form, *, before: int | None, limit: int) -> dict[str, Any]:
        limit = max(1, min(limit, MAX_PAGE))
        questions = (await self.questions_for(db, [form.id])).get(form.id, [])
        statement = select(FormResponse).where(FormResponse.form_id == form.id).order_by(FormResponse.id.desc()).limit(limit + 1)
        if before is not None:
            statement = statement.where(FormResponse.id < before)
        rows = list((await db.execute(statement)).scalars())
        has_more = len(rows) > limit
        rows = rows[:limit]
        cards = await people.load_cards(db, {row.user_id for row in rows})
        answers = await self._answers_for(db, form.id, [row.id for row in rows])
        return {
            "total": await self.response_count(db, form.id),
            "summary": await self._summary(db, form, questions),
            "responses": [
                {
                    "id": sid(row.id),
                    "user": cards.get(row.user_id),
                    "submitted_at": iso(row.submitted_at),
                    "answers": {sid(question_id): value for question_id, value in answers.get(row.id, {}).items()},
                }
                for row in rows
            ],
            "has_more": has_more,
        }

    @staticmethod
    async def purge(db: AsyncSession, form: Form) -> None:
        response_ids = select(FormResponse.id).where(FormResponse.form_id == form.id)
        await db.execute(delete(FormAnswer).where(FormAnswer.response_id.in_(response_ids)).execution_options(synchronize_session=False))
        await db.execute(delete(FormResponse).where(FormResponse.form_id == form.id).execution_options(synchronize_session=False))
        await db.execute(delete(FormQuestion).where(FormQuestion.form_id == form.id).execution_options(synchronize_session=False))
        notifications = delete(Notification).where(
            Notification.type == NotificationType.FORM_AVAILABLE.value,
            Notification.dedupe_key == dedupe_key(form.id),
        )
        await db.execute(notifications.execution_options(synchronize_session=False))
        await db.delete(form)
