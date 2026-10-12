import sqlite3

import pytest

from .conftest import database_dump, database_path, sql_rows
from .test_dok import class_id, class_member, collect_until, staff
from .test_messages import promote
from .test_websocket import ready, settle, types, wait_for

pytestmark = pytest.mark.timeout(60)

QUESTIONS = [
    {"type": "single_choice", "label": "Mikor jó az ebédszünet?", "required": True, "options": ["Korán", "Később"]},
    {"type": "multiple_choice", "label": "Mit főzzenek többet?", "required": False, "options": ["Tészta", "Leves", "Saláta"]},
    {"type": "short_text", "label": "Kedvenc étel", "required": False, "options": []},
    {"type": "long_text", "label": "Egyéb észrevétel", "required": True, "options": []},
]
ANONYMOUS_CALLS = (
    ("GET", "/forms", None),
    ("POST", "/forms", {}),
    ("GET", "/forms/1", None),
    ("GET", "/forms/1/me", None),
    ("PATCH", "/forms/1", {}),
    ("DELETE", "/forms/1", None),
    ("POST", "/forms/1/responses", {"answers": []}),
    ("GET", "/forms/1/responses", None),
)


def school_target():
    return {"type": "school"}


def class_target(user, code):
    return {"type": "class", "class_id": class_id(user, code)}


def make_form(user, target=None, **changes):
    body = {"title": "Menza felmérés", "description": "Pár gyors kérdés az ebédről.", "target": target or school_target(), "questions": QUESTIONS}
    body.update(changes)
    return user.post("/forms", body)


def create(user, target=None, **changes):
    response = make_form(user, target, **changes)
    assert response.status_code == 200, response.text
    return response.json()


def valid_answers(form, text="Tökéletes", skip=()):
    answers = []
    for question in form["questions"]:
        if question["label"] in skip:
            continue
        if question["type"] in ("single_choice", "multiple_choice"):
            answers.append({"question_id": question["id"], "options": [question["options"][0]["id"]]})
        else:
            answers.append({"question_id": question["id"], "text": f"{text} – {question['label']}"})
    return answers


def submit(user, form, answers=None):
    return user.post(f"/forms/{form['id']}/responses", {"answers": valid_answers(form) if answers is None else answers})


def error_code(response):
    return response.json()["error"]["code"]


def build_school(make_user):
    president = staff(make_user, "pres_dora", "dok_president")
    rep = class_member(make_user, "rep_eva", "9A")
    promote(rep.app, "rep_eva", "dok_representative")
    mate = class_member(make_user, "mate_anna", "9A")
    outsider = class_member(make_user, "out_bence", "10B")
    loner = make_user("loner_ede")
    return president, rep, mate, outsider, loner


def ids_of(user):
    return [item["id"] for item in user.get("/forms").json()["items"]]


def count(app, table):
    return sql_rows(app, f"SELECT COUNT(*) FROM {table}")[0][0]


def test_only_staff_and_the_dok_president_can_create_forms(make_user, api):
    president, rep, mate, outsider, loner = build_school(make_user)
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    for blocked in (rep, mate, loner):
        denied = make_form(blocked)
        assert denied.status_code == 403 and error_code(denied) == "form_create_forbidden"
    assert count(president.app, "forms") == 0
    expected = {"pres_dora": "dok_president", "mod_ilona": "school_moderator", "admin_vera": "school_admin"}
    for allowed in (president, moderator, admin):
        created = make_form(allowed)
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["status"] == "open" and body["creator_role"] == expected[allowed.username] and body["can_manage"] is True
    assert count(president.app, "forms") == 3
    assert make_form(api).status_code == 401


def test_created_forms_expose_ordered_questions_with_option_ids(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president, title="  Menza   felmérés ")
    assert form["title"] == "Menza felmérés" and form["target"] == {"type": "school"} and form["creator_role"] == "dok_president"
    assert [q["type"] for q in form["questions"]] == ["single_choice", "multiple_choice", "short_text", "long_text"]
    assert [q["position"] for q in form["questions"]] == [0, 1, 2, 3]
    assert [q["required"] for q in form["questions"]] == [True, False, False, True]
    options = form["questions"][0]["options"]
    assert [o["label"] for o in options] == ["Korán", "Később"] and len({o["id"] for o in options}) == 2 and all(o["id"].isdigit() for o in options)
    assert form["questions"][2]["options"] == []
    assert form["question_count"] == 4 and form["response_count"] == 0 and form["creator"]["username"] == "pres_dora"
    fetched = mate.get(f"/forms/{form['id']}")
    assert fetched.status_code == 200
    seen = fetched.json()
    assert seen["questions"] == form["questions"] and seen["creator"] is None and seen["response_count"] is None
    assert seen["creator_role"] == "dok_president" and seen["can_fill"] is True and seen["can_manage"] is False
    by_class = create(president, class_target(president, "9A"))
    assert by_class["target"] == {"type": "class", "class_id": class_id(president, "9A"), "code": "9A"}


def test_class_forms_are_only_open_to_that_class(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president, class_target(president, "9A"))
    for member in (rep, mate):
        assert member.get(f"/forms/{form['id']}").status_code == 200
        assert member.get(f"/forms/{form['id']}/me").json()["targeted"] is True
    assert submit(mate, form).status_code == 200
    assert submit(rep, form).status_code == 200
    for blocked in (outsider, loner, president):
        assert submit(blocked, form).status_code == 404
    for hidden in (outsider, loner):
        assert hidden.get(f"/forms/{form['id']}").status_code == 404
        assert hidden.get(f"/forms/{form['id']}/me").status_code == 404
        assert error_code(submit(hidden, form)) == "not_found"
    assert count(president.app, "form_responses") == 2


def test_school_forms_need_a_class_to_open_or_submit(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president, school_target())
    assert loner.get(f"/forms/{form['id']}").status_code == 404
    assert submit(loner, form).status_code == 404
    assert ids_of(loner) == []
    for member in (rep, mate, outsider):
        assert submit(member, form).status_code == 200
    assert president.get(f"/forms/{form['id']}/responses").json()["total"] == 3
    assert count(president.app, "form_responses") == 3


def test_a_second_submission_is_rejected(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    before = mate.get(f"/forms/{form['id']}/me").json()
    assert before["submitted"] is False and before["can_fill"] is True and before["submitted_at"] is None
    sent = submit(mate, form)
    assert sent.status_code == 200 and sent.json()["submitted"] is True and sent.json()["form_id"] == form["id"]
    again = submit(mate, form)
    assert again.status_code == 409 and error_code(again) == "form_already_submitted"
    after = mate.get(f"/forms/{form['id']}/me").json()
    assert after["submitted"] is True and after["can_fill"] is False and after["submitted_at"]
    assert count(president.app, "form_responses") == 1 and count(president.app, "form_answers") == 4
    assert president.get(f"/forms/{form['id']}/responses").json()["total"] == 1


def test_results_are_only_visible_to_the_creator_and_staff(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    second = class_member(make_user, "pres_gabor", "9A")
    promote(second.app, "pres_gabor", "dok_president")
    away = staff(make_user, "pres_hanna", "dok_president")
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    form = create(president, class_target(president, "9A"))
    assert submit(mate, form).status_code == 200
    url = f"/forms/{form['id']}/responses"
    for allowed in (president, moderator, admin):
        assert allowed.get(url).status_code == 200
    for visible in (mate, rep, second):
        denied = visible.get(url)
        assert denied.status_code == 403 and error_code(denied) == "form_results_forbidden"
    for hidden in (outsider, loner, away):
        assert hidden.get(url).status_code == 404
        assert hidden.get(f"/forms/{form['id']}").status_code == 404
    assert ids_of(second) == [form["id"]] and ids_of(away) == []
    listed = second.get("/forms").json()["items"][0]
    assert listed["can_view_results"] is False and listed["can_manage"] is False and listed["response_count"] is None and listed["creator"] is None


def test_a_creator_who_lost_the_role_loses_access(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    assert submit(mate, form).status_code == 200
    promote(president.app, "pres_dora", "user")
    assert president.get(f"/forms/{form['id']}/responses").status_code == 404
    assert president.patch(f"/forms/{form['id']}", {"status": "closed"}).status_code == 404
    assert ids_of(president) == []


def test_closed_forms_reject_submissions_but_keep_their_results(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    admin = staff(make_user, "admin_vera", "school_admin")
    form = create(president)
    assert submit(mate, form).status_code == 200
    closed = president.patch(f"/forms/{form['id']}", {"status": "closed"})
    assert closed.status_code == 200 and closed.json()["status"] == "closed" and closed.json()["closed_at"]
    late = submit(outsider, form)
    assert late.status_code == 409 and error_code(late) == "form_closed"
    assert outsider.get(f"/forms/{form['id']}").json()["can_fill"] is False
    assert outsider.get(f"/forms/{form['id']}/me").json()["can_fill"] is False
    for viewer in (president, admin):
        results = viewer.get(f"/forms/{form['id']}/responses")
        assert results.status_code == 200 and results.json()["total"] == 1
    reopened = president.patch(f"/forms/{form['id']}", {"status": "open"})
    assert reopened.status_code == 200 and reopened.json()["status"] == "open" and reopened.json()["closed_at"] is None
    assert submit(outsider, form).status_code == 200


def test_only_the_creator_and_admins_can_change_or_delete_a_form(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    second = class_member(make_user, "pres_gabor", "9A")
    promote(second.app, "pres_gabor", "dok_president")
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    form = create(president, class_target(president, "9A"))
    url = f"/forms/{form['id']}"
    for viewer in (mate, rep, second, moderator):
        denied = viewer.patch(url, {"status": "closed"})
        assert denied.status_code == 403 and error_code(denied) == "form_manage_forbidden"
        assert viewer.delete(url).status_code == 403
    for hidden in (outsider, loner):
        assert hidden.patch(url, {"status": "closed"}).status_code == 404
        assert hidden.delete(url).status_code == 404
    renamed = president.patch(url, {"title": "Új cím", "description": "Új leírás"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Új cím" and renamed.json()["description"] == "Új leírás"
    assert admin.patch(url, {"status": "closed"}).json()["status"] == "closed"
    assert admin.patch(url, {"status": "open"}).status_code == 200
    own = create(moderator)
    assert moderator.patch(f"/forms/{own['id']}", {"status": "closed"}).status_code == 200
    assert moderator.delete(f"/forms/{own['id']}").json() == {"status": "deleted"}
    assert president.delete(url).json() == {"status": "deleted"}
    assert mate.get(url).status_code == 404 and count(president.app, "forms") == 0


def test_deleting_a_form_removes_everything_it_owns(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    admin = staff(make_user, "admin_vera", "school_admin")
    doomed = create(president)
    kept = create(president, title="Marad")
    for user in (mate, outsider):
        assert submit(user, doomed).status_code == 200
    assert submit(mate, kept).status_code == 200
    assert count(president.app, "forms") == 2 and count(president.app, "form_questions") == 8
    assert count(president.app, "form_responses") == 3 and count(president.app, "form_answers") == 12
    doomed_key = f"form:{doomed['id']}"
    assert sql_rows(president.app, "SELECT COUNT(*) FROM notifications WHERE dedupe_key=?", (doomed_key,))[0][0] == 3
    assert admin.delete(f"/forms/{doomed['id']}").status_code == 200
    assert count(president.app, "forms") == 1 and count(president.app, "form_questions") == 4
    assert count(president.app, "form_responses") == 1 and count(president.app, "form_answers") == 4
    assert sql_rows(president.app, "SELECT COUNT(*) FROM notifications WHERE dedupe_key=?", (doomed_key,))[0][0] == 0
    assert sql_rows(president.app, "SELECT COUNT(*) FROM notifications WHERE dedupe_key=?", (f"form:{kept['id']}",))[0][0] == 3
    assert ids_of(mate) == [kept["id"]] and mate.get(f"/forms/{doomed['id']}").status_code == 404
    assert admin.delete(f"/forms/{doomed['id']}").status_code == 404


def test_form_validation(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    for title in ("", "   ", "x" * 121, "tab\u0007bell"):
        bad = make_form(president, title=title)
        assert bad.status_code == 422 and error_code(bad) == "form_title_invalid", title
    titled = make_form(president, title="x" * 121)
    assert titled.json()["error"]["params"] == {"max": 120} and "120" in titled.json()["error"]["message"]
    assert error_code(make_form(president, description="x" * 1001)) == "form_description_invalid"
    assert error_code(make_form(president, questions=[])) == "form_questions_invalid"
    crowd = [{"type": "short_text", "label": f"Kérdés {number}", "required": False, "options": []} for number in range(31)]
    assert error_code(make_form(president, questions=crowd)) == "form_questions_invalid"
    blank = [{"type": "short_text", "label": "   ", "required": False, "options": []}]
    assert error_code(make_form(president, questions=blank)) == "form_question_invalid"
    for options in ([], ["Csak ez"], ["Igen", "igen"], ["Igen", ""], ["x" * 101, "Nem"], [f"Lehetőség {n}" for n in range(13)]):
        bad = make_form(president, questions=[{"type": "multiple_choice", "label": "Választás", "required": True, "options": options}])
        assert bad.status_code == 422 and error_code(bad) == "form_options_invalid", options
    unknown_type = [{"type": "essay", "label": "Esszé", "required": False, "options": []}]
    assert error_code(make_form(president, questions=unknown_type)) == "validation_error"
    assert make_form(president, {"type": "class", "class_id": "123456789"}).status_code == 404
    assert make_form(president, {"type": "class", "class_id": "abc"}).status_code == 422
    assert make_form(president, {"type": "everyone"}).status_code == 422
    assert count(president.app, "forms") == 0
    ignored = make_form(president, questions=[{"type": "short_text", "label": "Név", "required": False, "options": ["felesleges"]}])
    assert ignored.status_code == 200 and ignored.json()["questions"][0]["options"] == []


def test_inactive_classes_cannot_be_targeted(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    retired = class_target(president, "10B")
    connection = sqlite3.connect(database_path(president.app))
    connection.execute("UPDATE school_classes SET is_active=0 WHERE code='10B'")
    connection.commit()
    connection.close()
    assert make_form(president, retired).status_code == 404
    assert count(president.app, "forms") == 0


def test_answer_validation(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    single, multiple, short, long_text = form["questions"]
    first, second = single["options"][0]["id"], single["options"][1]["id"]
    foreign = multiple["options"][0]["id"]

    def attempt(*answers):
        return mate.post(f"/forms/{form['id']}/responses", {"answers": list(answers)})

    pick = {"question_id": single["id"], "options": [first]}
    write = {"question_id": long_text["id"], "text": "Rendben"}
    assert error_code(attempt({"question_id": short["id"], "text": "csak ez"})) == "form_answer_required"
    assert error_code(attempt(pick)) == "form_answer_required"
    assert error_code(attempt(pick, {"question_id": long_text["id"], "text": "   "})) == "form_answer_required"
    assert error_code(attempt({"question_id": single["id"], "options": []}, write)) == "form_answer_required"
    bad_option = attempt({"question_id": single["id"], "options": ["999"]}, write)
    assert bad_option.status_code == 422 and error_code(bad_option) == "form_option_unknown"
    assert error_code(attempt({"question_id": single["id"], "options": [foreign]}, write)) == "form_option_unknown"
    assert error_code(attempt(pick, write, {"question_id": multiple["id"], "options": [foreign, "999"]})) == "form_option_unknown"
    assert error_code(attempt({"question_id": single["id"], "options": [first, second]}, write)) == "form_answer_invalid"
    assert error_code(attempt(pick, write, {"question_id": multiple["id"], "options": [foreign, foreign]})) == "form_answer_invalid"
    assert error_code(attempt(pick, write, {"question_id": "123", "text": "ismeretlen"})) == "form_answer_invalid"
    assert error_code(attempt(pick, write, {"question_id": "abc", "text": "x"})) == "form_answer_invalid"
    assert error_code(attempt(pick, pick, write)) == "form_answer_invalid"
    assert error_code(attempt({"question_id": single["id"], "text": "szöveg", "options": [first]}, write)) == "form_answer_invalid"
    assert error_code(attempt(pick, {"question_id": long_text["id"], "text": "x", "options": [first]})) == "form_answer_invalid"
    assert error_code(attempt(pick, write, {"question_id": short["id"], "text": "két\nsor"})) == "form_answer_invalid"
    too_long_short = attempt(pick, write, {"question_id": short["id"], "text": "é" * 201})
    assert too_long_short.status_code == 422 and error_code(too_long_short) == "form_answer_too_long"
    assert too_long_short.json()["error"]["params"] == {"max": 200}
    assert error_code(attempt(pick, {"question_id": long_text["id"], "text": "é" * 2001})) == "form_answer_too_long"
    assert mate.post(f"/forms/{form['id']}/responses", {}).status_code == 422
    assert count(president.app, "form_responses") == 0 and count(president.app, "form_answers") == 0
    assert mate.get(f"/forms/{form['id']}/me").json()["submitted"] is False
    accepted = attempt(pick, write)
    assert accepted.status_code == 200, accepted.text
    assert count(president.app, "form_responses") == 1 and count(president.app, "form_answers") == 2


def test_optional_questions_can_be_skipped_and_text_is_trimmed(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    single, multiple, short, long_text = form["questions"]
    answers = [
        {"question_id": single["id"], "options": [single["options"][1]["id"]]},
        {"question_id": short["id"], "text": "   "},
        {"question_id": long_text["id"], "text": "  két\r\nsor  "},
    ]
    assert submit(mate, form, answers).status_code == 200
    results = president.get(f"/forms/{form['id']}/responses").json()
    stored = results["responses"][0]["answers"]
    assert set(stored) == {single["id"], long_text["id"]} and stored[long_text["id"]] == {"text": "két\nsor"}
    summary = {entry["question_id"]: entry for entry in results["summary"]}
    assert summary[short["id"]]["answered"] == 0 and summary[multiple["id"]]["answered"] == 0 and summary[long_text["id"]]["answered"] == 1


def test_results_aggregate_choices_and_identify_respondents_by_platform_name(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    single, multiple, short, long_text = form["questions"]
    korán, később = (option["id"] for option in single["options"])
    tészta, leves, saláta = (option["id"] for option in multiple["options"])
    write = {"question_id": long_text["id"], "text": "Nincs panasz"}
    assert submit(mate, form, [{"question_id": single["id"], "options": [korán]}, {"question_id": multiple["id"], "options": [tészta, saláta]}, write]).status_code == 200
    assert submit(outsider, form, [{"question_id": single["id"], "options": [később]}, {"question_id": multiple["id"], "options": [saláta]}, {"question_id": short["id"], "text": "Gulyás"}, write]).status_code == 200
    assert submit(rep, form, [{"question_id": single["id"], "options": [korán]}, write]).status_code == 200
    results = president.get(f"/forms/{form['id']}/responses").json()
    assert results["total"] == 3 and results["has_more"] is False and len(results["responses"]) == 3
    summary = {entry["question_id"]: entry for entry in results["summary"]}
    assert {o["label"]: o["count"] for o in summary[single["id"]]["options"]} == {"Korán": 2, "Később": 1}
    assert {o["label"]: o["count"] for o in summary[multiple["id"]]["options"]} == {"Tészta": 1, "Leves": 0, "Saláta": 2}
    assert summary[single["id"]]["answered"] == 3 and summary[multiple["id"]]["answered"] == 2
    assert summary[short["id"]]["answered"] == 1 and summary[short["id"]]["options"] == [] and summary[long_text["id"]]["answered"] == 3
    by_user = {response["user"]["username"]: response for response in results["responses"]}
    assert set(by_user) == {"mate_anna", "out_bence", "rep_eva"}
    assert all(set(response["user"]) == {"id", "username", "display_name", "avatar_url", "staff"} for response in results["responses"])
    assert by_user["mate_anna"]["user"]["display_name"] == "Mate_Anna" and by_user["mate_anna"]["user"]["id"] == mate.uid
    assert by_user["mate_anna"]["answers"][single["id"]] == {"options": [korán]}
    assert by_user["mate_anna"]["answers"][multiple["id"]] == {"options": [tészta, saláta]}
    assert by_user["out_bence"]["answers"][short["id"]] == {"text": "Gulyás"}
    assert short["id"] not in by_user["rep_eva"]["answers"]
    dump = str(results)
    for real_name in ("Kiss", "Tóth", "Szabó", "Teszt Elek", "real_name"):
        assert real_name not in dump


def test_results_paginate_newest_first(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    extra = class_member(make_user, "mate_zsolt", "9A")
    form = create(president)
    for user in (rep, mate, outsider, extra):
        assert submit(user, form).status_code == 200
    url = f"/forms/{form['id']}/responses"
    first = president.get(f"{url}?limit=2").json()
    assert first["total"] == 4 and first["has_more"] is True
    assert [r["user"]["username"] for r in first["responses"]] == ["mate_zsolt", "out_bence"]
    second = president.get(f"{url}?limit=2&before={first['responses'][-1]['id']}").json()
    assert second["has_more"] is False and [r["user"]["username"] for r in second["responses"]] == ["mate_anna", "rep_eva"]
    assert second["total"] == 4 and second["summary"] == first["summary"]
    assert president.get(f"{url}?before=abc").status_code == 422
    assert president.get(f"{url}?limit=0").status_code == 422
    assert president.get(f"{url}?limit=101").status_code == 422


def test_listing_shows_each_viewer_only_what_they_may_see(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    away = staff(make_user, "pres_hanna", "dok_president")
    school = create(president, school_target(), title="Iskolai felmérés")
    class_form = create(president, class_target(president, "9A"), title="9A felmérés")
    newest_first = [class_form["id"], school["id"]]
    assert ids_of(mate) == ids_of(rep) == ids_of(president) == ids_of(moderator) == ids_of(admin) == newest_first
    assert ids_of(outsider) == [school["id"]] and ids_of(loner) == [] and ids_of(away) == []
    seen = mate.get("/forms").json()["items"][0]
    assert seen["title"] == "9A felmérés" and seen["targeted"] is True and seen["can_fill"] is True and seen["submitted"] is False
    assert seen["can_manage"] is False and seen["can_view_results"] is False and seen["response_count"] is None and seen["creator"] is None
    assert seen["creator_role"] == "dok_president" and seen["question_count"] == 4 and seen["target"]["code"] == "9A"
    assert submit(mate, class_form).status_code == 200
    again = mate.get("/forms").json()["items"][0]
    assert again["submitted"] is True and again["can_fill"] is False and again["submitted_at"]
    own = president.get("/forms").json()["items"][0]
    assert own["can_manage"] is True and own["can_view_results"] is True and own["response_count"] == 1 and own["targeted"] is False
    assert own["can_fill"] is False and own["creator"]["username"] == "pres_dora"
    reviewed = moderator.get("/forms").json()["items"][0]
    assert reviewed["can_manage"] is False and reviewed["can_view_results"] is True and reviewed["response_count"] == 1
    assert admin.get("/forms").json()["items"][0]["can_manage"] is True


def test_eligible_users_are_notified_once_and_can_mute_form_notifications(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    assert mate.get("/me").json()["settings"]["notification_prefs"]["forms"] is True
    connection = sqlite3.connect(database_path(rep.app))
    connection.execute("UPDATE user_settings SET notification_prefs='{\"sounds\": true}'")
    connection.commit()
    connection.close()
    assert mate.get("/me").json()["settings"]["notification_prefs"]["forms"] is True
    assert outsider.patch("/me/settings", {"notification_prefs": {"forms": False}}).status_code == 200
    assert outsider.patch("/me/settings", {"notification_prefs": {"formz": False}}).status_code == 422
    form = create(president, class_target(president, "9A"), title="9A kérdőív")
    for member in (rep, mate):
        notes = member.get("/notifications").json()
        assert notes["unread"] == 1
        assert notes["items"][0]["type"] == "form_available"
        assert notes["items"][0]["payload"] == {"form_id": form["id"], "title": "9A kérdőív", "scope": "class", "class_code": "9A"}
    for silent in (president, outsider, loner):
        assert silent.get("/notifications").json()["unread"] == 0
    school = create(president, school_target(), title="Iskolai kérdőív")
    assert outsider.get("/notifications").json()["unread"] == 0 and school["id"] in ids_of(outsider)
    assert mate.get("/notifications").json()["unread"] == 2
    assert president.get("/notifications").json()["unread"] == 0
    assert sql_rows(president.app, "SELECT COUNT(*) FROM notifications WHERE type='form_available'")[0][0] == 4


def test_suspended_accounts_are_not_notified(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    classmate = class_member(make_user, "mate_gabor", "9A")
    admin = staff(make_user, "admin_vera", "school_admin")
    admin.post(f"/moderation/users/{classmate.uid}/status", {"status": "suspended", "reason": "teszt felfüggesztés"})
    create(president, class_target(president, "9A"))
    assert sql_rows(president.app, "SELECT COUNT(*) FROM notifications WHERE user_id=? AND type='form_available'", (int(classmate.uid),))[0][0] == 0
    assert mate.get("/notifications").json()["unread"] == 1


def test_form_lifecycle_is_audited_without_answers(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    form = create(president, class_target(president, "9A"), title="Auditált űrlap")
    url = f"/forms/{form['id']}"
    assert submit(mate, form, valid_answers(form, text="soha ne kerüljön a naplóba")).status_code == 200
    assert moderator.get(f"{url}/responses").status_code == 200
    assert president.get(f"{url}/responses").status_code == 200
    assert president.patch(url, {"status": "closed"}).status_code == 200
    assert president.patch(url, {"status": "closed"}).status_code == 200
    assert president.patch(url, {"status": "open"}).status_code == 200
    assert president.patch(url, {"title": "Átnevezve"}).status_code == 200
    assert president.delete(url).status_code == 200
    entries = [e for e in admin.get("/moderation/audit").json()["entries"] if e["action"].startswith("form.")]
    by_action = {}
    for entry in entries:
        by_action.setdefault(entry["action"], []).append(entry)
    assert sorted((action, len(items)) for action, items in by_action.items()) == [
        ("form.close", 1),
        ("form.create", 1),
        ("form.delete", 1),
        ("form.reopen", 1),
        ("form.results_view", 1),
        ("form.update", 1),
    ]
    assert all(e["target_type"] == "form" and e["target_id"] == form["id"] for e in entries)
    assert by_action["form.create"][0]["actor"]["username"] == "pres_dora"
    assert by_action["form.create"][0]["details"] == {
        "title": "Auditált űrlap",
        "scope": "class",
        "class_id": class_id(president, "9A"),
        "questions": 4,
        "audience": 2,
    }
    assert by_action["form.close"][0]["details"] == {"title": "Auditált űrlap", "responses": 1}
    assert by_action["form.reopen"][0]["details"] == {"title": "Auditált űrlap", "responses": 1}
    assert by_action["form.update"][0]["details"] == {"fields": ["title"], "title": "Átnevezve"}
    assert by_action["form.results_view"][0]["actor"]["username"] == "mod_ilona"
    assert by_action["form.results_view"][0]["details"] == {"title": "Auditált űrlap", "responses": 1}
    assert by_action["form.delete"][0]["details"] == {"title": "Átnevezve", "scope": "class", "class_id": class_id(president, "9A"), "responses": 1}
    assert "naplóba" not in str(entries)
    assert sql_rows(president.app, "SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'form.%' AND server_id IS NULL")[0][0] == 6


def test_answers_are_encrypted_and_bound_to_their_row(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    assert submit(mate, form, valid_answers(form, text="titkos velemeny")).status_code == 200
    assert submit(outsider, form, valid_answers(form, text="masik velemeny")).status_code == 200
    dump = database_dump(president.app)
    assert "titkos velemeny" not in dump and "masik velemeny" not in dump
    rows = sql_rows(president.app, "SELECT value_enc FROM form_answers")
    assert len(rows) == 8 and all(b"velemeny" not in bytes(blob) and b"options" not in bytes(blob) for (blob,) in rows)
    long_id = form["questions"][3]["id"]
    single_id = form["questions"][0]["id"]
    url = f"/forms/{form['id']}/responses"
    readable = president.get(url).json()["responses"]
    assert sorted(r["answers"][long_id]["text"] for r in readable) == ["masik velemeny – Egyéb észrevétel", "titkos velemeny – Egyéb észrevétel"]
    pair = sql_rows(president.app, "SELECT response_id, value_enc FROM form_answers WHERE question_id=?", (int(long_id),))
    assert len(pair) == 2
    connection = sqlite3.connect(database_path(president.app))
    connection.execute("UPDATE form_answers SET value_enc=? WHERE response_id=? AND question_id=?", (pair[1][1], pair[0][0], int(long_id)))
    connection.execute("UPDATE form_answers SET value_enc=? WHERE response_id=? AND question_id=?", (pair[0][1], pair[1][0], int(long_id)))
    connection.commit()
    connection.close()
    swapped = president.get(url).json()
    assert [r["answers"][long_id] for r in swapped["responses"]] == [None, None]
    assert all(r["answers"][single_id] is not None for r in swapped["responses"])


def test_form_endpoints_require_authentication(api):
    for method, path, body in ANONYMOUS_CALLS:
        response = api.request(method, path, json=body) if body is not None else api.request(method, path)
        assert response.status_code in (401, 403), (method, path, response.status_code)


def test_create_submit_and_list_are_rate_limited(make_user, monkeypatch):
    president, rep, mate, outsider, loner = build_school(make_user)
    form = create(president)
    president.app.state.limiter.enabled = True
    monkeypatch.setattr("app.api.v1.forms.CREATE_LIMIT", (2, 60))
    monkeypatch.setattr("app.api.v1.forms.SUBMIT_LIMIT", (1, 60))
    monkeypatch.setattr("app.api.v1.forms.LIST_LIMIT", (3, 60))
    for _ in range(5):
        assert make_form(mate).status_code == 403
    assert make_form(president).status_code == 200
    assert make_form(president).status_code == 200
    limited = make_form(president)
    assert limited.status_code == 429 and error_code(limited) == "rate_limited" and "retry-after" in limited.headers
    assert submit(mate, form).status_code == 200
    again = submit(mate, form)
    assert again.status_code == 429 and error_code(again) == "rate_limited"
    assert submit(rep, form).status_code == 200
    for _ in range(3):
        assert outsider.get("/forms").status_code == 200
    blocked = outsider.get("/forms")
    assert blocked.status_code == 429 and error_code(blocked) == "rate_limited"
    for _ in range(3):
        assert president.get(f"/forms/{form['id']}/responses").status_code == 200
    assert president.get(f"/forms/{form['id']}/responses").status_code == 429


def test_error_messages_follow_the_requested_language(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    body = {"title": "x", "description": "", "target": school_target(), "questions": QUESTIONS}
    for language, fragment in (("hu", "Űrlapot csak"), ("en", "Only school administrators"), ("de", "Formulare können nur")):
        denied = mate.post("/forms", body, headers={"Accept-Language": language})
        assert denied.status_code == 403 and fragment in denied.json()["error"]["message"]
    bad = {**body, "title": "x" * 121}
    german = president.post("/forms", bad, headers={"Accept-Language": "de"})
    assert german.json()["error"]["message"] == "Der Titel muss 1–120 Zeichen lang sein und darf keine Steuerzeichen enthalten."


def test_form_events_reach_the_audience_without_content(make_user):
    president, rep, mate, outsider, loner = build_school(make_user)
    with president.websocket() as wp, mate.websocket() as wm, outsider.websocket() as wo:
        for socket in (wp, wm, wo):
            ready(socket)
        form = create(president, class_target(president, "9A"), title="Élő űrlap")
        seen = collect_until(wm, "form.changed")
        assert seen[-1]["d"] == {"form_id": form["id"]}
        notes = [e for e in seen if e["t"] == "notification.create"]
        assert len(notes) == 1 and notes[0]["d"]["type"] == "form_available"
        assert wait_for(wp, "form.changed")["d"] == {"form_id": form["id"]}
        assert "form.changed" not in types(settle(wo))
        assert submit(mate, form).status_code == 200
        assert wait_for(wm, "form.changed")["d"] == {"form_id": form["id"]}
        assert wait_for(wp, "form.changed")["d"] == {"form_id": form["id"]}
        assert "form.changed" not in types(settle(wo))
        assert president.patch(f"/forms/{form['id']}", {"status": "closed"}).status_code == 200
        closing = wait_for(wm, "form.changed")
        assert closing["d"] == {"form_id": form["id"]}
        for secret in ("pres_dora", "mate_anna", "Tökéletes", mate.uid):
            assert secret not in str(seen) and secret not in str(closing)
        assert "form.changed" not in types(settle(wo))
