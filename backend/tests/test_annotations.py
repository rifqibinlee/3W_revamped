from datetime import datetime, timedelta, timezone

from app.annotations import service
from app.annotations.models import TaskStatus
from app.auth import service as auth_service
from app.auth.models import Role
from app.chat import service as chat_service

GEOMETRY = {"type": "Point", "coordinates": [101.5, 3.1]}


def _user(db_session, username: str, role: Role = Role.STAFF):
    return auth_service.register_user(db_session, username, f"{username}@example.com", "password123", role)


def _due(days=1):
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_unassigned_project_is_a_plain_note(db_session) -> None:
    creator = _user(db_session, "creator")
    note = service.create_project(db_session, creator, "Pole down")
    assert note.assignee_id is None
    assert note.conversation_id is None


def test_assigned_project_gets_a_chat_room(db_session) -> None:
    creator = _user(db_session, "creator_chatroom")
    assignee = _user(db_session, "assignee_chatroom")

    project = service.create_project(db_session, creator, "Fix it", assignee_id=assignee.id)
    assert project.conversation_id is not None

    expected = chat_service.get_or_create_direct_conversation(db_session, creator.id, assignee.id)
    assert project.conversation_id == expected.id


def test_assigning_a_note_also_creates_a_chat_room(db_session) -> None:
    creator = _user(db_session, "creator_chatroom2")
    assignee = _user(db_session, "assignee_chatroom2")
    note = service.create_project(db_session, creator, "Just a note")
    assert note.conversation_id is None

    project = service.assign_project(db_session, note, assignee.id)
    assert project.conversation_id is not None
    assert project.assignee_id == assignee.id


def test_add_annotation_to_project(db_session) -> None:
    creator = _user(db_session, "creator_ann")
    project = service.create_project(db_session, creator, "Survey area")
    annotation = service.add_annotation(db_session, project, creator, GEOMETRY, label="pole 1")

    rows = service.list_annotations(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].id == annotation.id
    assert rows[0].label == "pole 1"


def test_multiple_annotations_under_one_project(db_session) -> None:
    creator = _user(db_session, "creator_multi")
    project = service.create_project(db_session, creator, "Survey area")
    service.add_annotation(db_session, project, creator, GEOMETRY)
    service.add_annotation(db_session, project, creator, {"type": "Point", "coordinates": [101.6, 3.2]})

    rows = service.list_annotations(db_session, project.id)
    assert len(rows) == 2


def test_cannot_create_task_under_a_note(db_session) -> None:
    creator = _user(db_session, "creator_note_task")
    assignee = _user(db_session, "assignee_note_task")
    note = service.create_project(db_session, creator, "Just a note")

    try:
        service.create_task(db_session, note, creator, "Do something", [assignee.id], _due())
        assert False, "expected NotAProjectError"
    except service.NotAProjectError:
        pass


def test_create_task_under_a_project(db_session) -> None:
    creator = _user(db_session, "creator_task1")
    assignee = _user(db_session, "assignee_task1")
    project = service.create_project(db_session, creator, "Fix antenna", assignee_id=assignee.id)

    task = service.create_task(db_session, project, creator, "Climb tower", [assignee.id], _due())
    assert task.status == TaskStatus.TODO
    assert task.project_id == project.id


def test_full_happy_path_to_done(db_session) -> None:
    creator = _user(db_session, "creator4")
    assignee = _user(db_session, "assignee4")
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())

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
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())
    task = service.start_progress(db_session, task, assignee)
    task = service.submit_for_review(db_session, task, assignee)

    task = service.reject(db_session, task, creator, "missing photos")
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.rejection_reason == "missing photos"


def test_assignee_cannot_approve_own_task(db_session) -> None:
    creator = _user(db_session, "creator6")
    assignee = _user(db_session, "assignee6")
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())
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
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())
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
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())
    task = service.start_progress(db_session, task, assignee)
    task = service.submit_for_review(db_session, task, assignee)

    task = service.approve(db_session, task, admin)
    assert task.status == TaskStatus.DONE


def test_cannot_approve_a_task_thats_still_todo(db_session) -> None:
    creator = _user(db_session, "creator9")
    assignee = _user(db_session, "assignee9")
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())

    try:
        service.approve(db_session, task, creator)
        assert False, "expected InvalidTransitionError"
    except service.InvalidTransitionError:
        pass


def test_only_assignee_can_start_progress(db_session) -> None:
    creator = _user(db_session, "creator10")
    assignee = _user(db_session, "assignee10")
    project = service.create_project(db_session, creator, "Repair project", assignee_id=assignee.id)
    task = service.create_task(db_session, project, creator, "Repair", [assignee.id], _due())

    try:
        service.start_progress(db_session, task, creator)
        assert False, "expected PermissionDeniedError"
    except service.PermissionDeniedError:
        pass


def test_gantt_rows_lists_tasks(db_session) -> None:
    creator = _user(db_session, "creator11")
    assignee = _user(db_session, "assignee11")
    project = service.create_project(db_session, creator, "Project", assignee_id=assignee.id)
    service.create_task(db_session, project, creator, "A real task", [assignee.id], _due())

    rows = service.gantt_rows(db_session)
    assert len(rows) == 1
    assert rows[0].title == "A real task"


def test_gantt_rows_filters_by_assignee(db_session) -> None:
    creator = _user(db_session, "creator11b")
    alice = _user(db_session, "alice11b")
    bob = _user(db_session, "bob11b")
    project = service.create_project(db_session, creator, "Project", assignee_id=alice.id)
    service.create_task(db_session, project, creator, "Alice's task", [alice.id], _due())
    service.create_task(db_session, project, creator, "Bob's task", [bob.id], _due())

    rows = service.gantt_rows(db_session, assignee_id=alice.id)
    assert len(rows) == 1
    assert rows[0].title == "Alice's task"


def test_task_can_have_multiple_assignees(db_session) -> None:
    creator = _user(db_session, "creator13")
    alice = _user(db_session, "alice13")
    bob = _user(db_session, "bob13")
    project = service.create_project(db_session, creator, "Project", assignee_id=alice.id)
    task = service.create_task(db_session, project, creator, "Joint task", [alice.id, bob.id], _due())

    assert {a.id for a in task.assignees} == {alice.id, bob.id}

    # either assignee can act on the shared task
    task = service.start_progress(db_session, task, bob)
    assert task.status == TaskStatus.IN_PROGRESS


def test_gantt_rows_filters_by_assignee_with_multiple_assignees(db_session) -> None:
    creator = _user(db_session, "creator13b")
    alice = _user(db_session, "alice13b")
    bob = _user(db_session, "bob13b")
    project = service.create_project(db_session, creator, "Project", assignee_id=alice.id)
    service.create_task(db_session, project, creator, "Joint task", [alice.id, bob.id], _due())

    assert len(service.gantt_rows(db_session, assignee_id=alice.id)) == 1
    assert len(service.gantt_rows(db_session, assignee_id=bob.id)) == 1


def test_gantt_rows_filters_by_project(db_session) -> None:
    creator = _user(db_session, "creator13c")
    alice = _user(db_session, "alice13c")
    project_a = service.create_project(db_session, creator, "Project A", assignee_id=alice.id)
    project_b = service.create_project(db_session, creator, "Project B", assignee_id=alice.id)
    service.create_task(db_session, project_a, creator, "A's task", [alice.id], _due())
    service.create_task(db_session, project_b, creator, "B's task", [alice.id], _due())

    rows = service.gantt_rows(db_session, project_id=project_a.id)
    assert [r.title for r in rows] == ["A's task"]


def test_add_comment_at_project_level(db_session) -> None:
    creator = _user(db_session, "creator12")
    project = service.create_project(db_session, creator, "Note")
    comment = service.add_comment(db_session, project, creator, "looks fine")
    assert comment.body == "looks fine"
    assert comment.project_id == project.id


def test_list_comments_returns_in_chronological_order(db_session) -> None:
    creator = _user(db_session, "creator14")
    project = service.create_project(db_session, creator, "Note")
    service.add_comment(db_session, project, creator, "first")
    service.add_comment(db_session, project, creator, "second")

    comments = service.list_comments(db_session, project.id)
    assert [c.body for c in comments] == ["first", "second"]
