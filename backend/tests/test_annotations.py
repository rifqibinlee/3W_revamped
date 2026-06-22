from datetime import datetime, timedelta, timezone

from app.annotations import service
from app.annotations.models import TaskStatus
from app.auth import service as auth_service
from app.auth.models import Role

GEOMETRY = {"type": "Point", "coordinates": [101.5, 3.1]}


def _user(db_session, username: str, role: Role = Role.STAFF):
    return auth_service.register_user(db_session, username, f"{username}@example.com", "password123", role)


def test_unassigned_annotation_is_a_plain_note(db_session) -> None:
    creator = _user(db_session, "creator")
    note = service.create_annotation(db_session, creator, "Pole down", GEOMETRY)
    assert note.assignee_id is None
    assert note.status is None


def test_creating_with_assignee_starts_as_task_todo(db_session) -> None:
    creator = _user(db_session, "creator2")
    assignee = _user(db_session, "assignee2")
    due = datetime.now(timezone.utc) + timedelta(days=3)
    task = service.create_annotation(db_session, creator, "Fix antenna", GEOMETRY, assignee_id=assignee.id, due_date=due)
    assert task.status == TaskStatus.TODO
    assert task.assignee_id == assignee.id


def test_assigning_a_note_converts_it_to_a_task(db_session) -> None:
    creator = _user(db_session, "creator3")
    assignee = _user(db_session, "assignee3")
    note = service.create_annotation(db_session, creator, "Check signal", GEOMETRY)

    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.assign_task(db_session, note, assignee.id, due)
    assert task.status == TaskStatus.TODO
    assert task.assignee_id == assignee.id


def test_full_happy_path_to_done(db_session) -> None:
    creator = _user(db_session, "creator4")
    assignee = _user(db_session, "assignee4")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)

    task = service.start_progress(db_session, task, assignee)
    assert task.status == TaskStatus.IN_PROGRESS

    task = service.submit_for_review(db_session, task, assignee)
    assert task.status == TaskStatus.PENDING_REVIEW

    task = service.approve(db_session, task, creator)
    assert task.status == TaskStatus.DONE
    assert task.reviewed_by_id == creator.id


def test_reject_sends_task_back_to_in_progress_with_reason(db_session) -> None:
    creator = _user(db_session, "creator5")
    assignee = _user(db_session, "assignee5")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)
    task = service.start_progress(db_session, task, assignee)
    task = service.submit_for_review(db_session, task, assignee)

    task = service.reject(db_session, task, creator, "missing photos")
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.rejection_reason == "missing photos"


def test_assignee_cannot_approve_own_task(db_session) -> None:
    creator = _user(db_session, "creator6")
    assignee = _user(db_session, "assignee6")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)
    task = service.start_progress(db_session, task, assignee)
    task = service.submit_for_review(db_session, task, assignee)

    try:
        service.approve(db_session, task, assignee)
        assert False, "expected PermissionDeniedError"
    except service.PermissionDeniedError:
        pass


def test_non_creator_non_admin_cannot_approve(db_session) -> None:
    creator = _user(db_session, "creator7")
    assignee = _user(db_session, "assignee7")
    bystander = _user(db_session, "bystander7")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)
    task = service.start_progress(db_session, task, assignee)
    task = service.submit_for_review(db_session, task, assignee)

    try:
        service.approve(db_session, task, bystander)
        assert False, "expected PermissionDeniedError"
    except service.PermissionDeniedError:
        pass


def test_admin_can_approve_even_if_not_creator(db_session) -> None:
    creator = _user(db_session, "creator8")
    assignee = _user(db_session, "assignee8")
    admin = _user(db_session, "admin8", role=Role.ADMIN)
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)
    task = service.start_progress(db_session, task, assignee)
    task = service.submit_for_review(db_session, task, assignee)

    task = service.approve(db_session, task, admin)
    assert task.status == TaskStatus.DONE


def test_cannot_approve_a_task_thats_still_todo(db_session) -> None:
    creator = _user(db_session, "creator9")
    assignee = _user(db_session, "assignee9")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)

    try:
        service.approve(db_session, task, creator)
        assert False, "expected InvalidTransitionError"
    except service.InvalidTransitionError:
        pass


def test_only_assignee_can_start_progress(db_session) -> None:
    creator = _user(db_session, "creator10")
    assignee = _user(db_session, "assignee10")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = service.create_annotation(db_session, creator, "Repair", GEOMETRY, assignee_id=assignee.id, due_date=due)

    try:
        service.start_progress(db_session, task, creator)
        assert False, "expected PermissionDeniedError"
    except service.PermissionDeniedError:
        pass


def test_gantt_rows_only_include_tasks_not_notes(db_session) -> None:
    creator = _user(db_session, "creator11")
    assignee = _user(db_session, "assignee11")
    due = datetime.now(timezone.utc) + timedelta(days=1)
    service.create_annotation(db_session, creator, "Just a note", GEOMETRY)
    service.create_annotation(db_session, creator, "A real task", GEOMETRY, assignee_id=assignee.id, due_date=due)

    rows = service.gantt_rows(db_session)
    assert len(rows) == 1
    assert rows[0].title == "A real task"


def test_add_comment(db_session) -> None:
    creator = _user(db_session, "creator12")
    note = service.create_annotation(db_session, creator, "Note", GEOMETRY)
    comment = service.add_comment(db_session, note, creator, "looks fine")
    assert comment.body == "looks fine"
    assert comment.annotation_id == note.id
