from __future__ import annotations


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bob" in body
    assert "CHORE MANAGER" in body


def test_toggle_marks_done(client, app):
    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion

    resp = client.post("/toggle/dishes/bob")
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger-After-Swap") is not None

    with app.app_context():
        rows = db.session.query(ChoreCompletion).all()
        assert len(rows) == 1
        assert rows[0].chore_key == "dishes"
        assert rows[0].person_key == "bob"


def test_toggle_again_undoes(client, app):
    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion

    client.post("/toggle/dishes/bob")
    resp = client.post("/toggle/dishes/bob")
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger") is None

    with app.app_context():
        rows = db.session.query(ChoreCompletion).all()
        assert len(rows) == 0


def test_toggle_unknown_chore_returns_404(client):
    resp = client.post("/toggle/missing/bob")
    assert resp.status_code == 404


def test_toggle_unassigned_person_returns_404(client):
    resp = client.post("/toggle/dishes/alice")
    assert resp.status_code == 404


def test_view_as_sets_cookie(client):
    resp = client.post("/view-as", data={"viewer": "bob"})
    assert resp.status_code == 302
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("viewer=bob" in c for c in cookies)


def test_redeem_creates_pending(client, app):
    from datetime import date

    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion, Redemption

    with app.app_context():
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="bob",
                completed_on=date(2026, 4, 30),
                points_awarded=30,
            )
        )
        db.session.commit()

    resp = client.post("/redeem/screen/bob")
    assert resp.status_code == 302

    with app.app_context():
        redemptions = db.session.query(Redemption).all()
        assert len(redemptions) == 1
        assert redemptions[0].status == "pending"
