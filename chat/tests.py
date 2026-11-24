"""Event chat (section 11, Phase 7)."""

import pytest
from django.urls import reverse

from core.models import AuditLog
from events import registration
from events.models import Registration

from . import services
from .models import ChatMessage, ChatReport

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def room(make_event, make_user):
    """An event with two registered players."""
    event = make_event()
    alice, bob = make_user("alice"), make_user("bob")
    registration.join(event, alice.player)
    registration.join(event, bob.player)
    return event, alice, bob


# --- Who can chat ----------------------------------------------------------

def test_registered_players_and_admins_can_chat(room, admin_user, make_user):
    event, alice, _ = room
    assert services.can_chat(alice, event)
    assert services.can_chat(admin_user, event)
    assert not services.can_chat(make_user(), event)


def test_withdrawn_players_cannot_chat(room):
    event, alice, _ = room
    Registration.objects.filter(event=event, player=alice.player).update(status=Registration.Status.WITHDRAWN)
    assert not services.can_chat(alice, event)
    with pytest.raises(services.ChatError):
        services.post(event, alice, "hi")


def test_outsiders_are_sent_to_join(client, room, make_user):
    event, _, _ = room
    client.force_login(make_user())
    assert client.get(reverse("chat:room", args=[event.pk])).status_code == 302
    assert client.get(reverse("chat:poll", args=[event.pk])).status_code == 403
    client.post(reverse("chat:post", args=[event.pk]), {"body": "sneaky"})
    assert not ChatMessage.objects.exists()


def test_signed_out_people_go_to_sign_in(client, room):
    event, _, _ = room
    response = client.get(reverse("chat:room", args=[event.pk]))
    assert response.status_code == 302 and reverse("accounts:login") in response.url


def test_spectators_never_see_chat(client, room):
    event, alice, _ = room
    services.post(event, alice, "secret plans")
    page = client.get(reverse("events:watch", args=[event.spectator_code])).content.decode()
    assert "secret plans" not in page
    assert reverse("chat:room", args=[event.pk]) not in page


# --- Posting ---------------------------------------------------------------

def test_post_and_validation(room):
    event, alice, _ = room
    msg = services.post(event, alice, "  See you at 6!  ")
    assert msg.body == "See you at 6!"
    with pytest.raises(services.ChatError, match="Type a message"):
        services.post(event, alice, "   ")
    with pytest.raises(services.ChatError, match="under 500"):
        services.post(event, alice, "x" * 501)


def test_post_through_the_page(client, room):
    event, alice, bob = room
    client.force_login(alice)
    response = client.post(reverse("chat:post", args=[event.pk]), {"body": "Hello <b>all</b>"}, **HX)
    html = response.content.decode()
    assert response.status_code == 200 and 'id="chat-box"' in html
    assert "Hello &lt;b&gt;all&lt;/b&gt;" in html, "message text is escaped"

    client.force_login(bob)
    page = client.get(reverse("chat:room", args=[event.pk])).content.decode()
    assert "Hello &lt;b&gt;all&lt;/b&gt;" in page and "Alice Tester" in page


def test_empty_post_shows_error_in_place(client, room):
    event, alice, _ = room
    client.force_login(alice)
    html = client.post(reverse("chat:post", args=[event.pk]), {"body": ""}, **HX).content.decode()
    assert "Type a message first." in html
    assert not ChatMessage.objects.exists()


def test_post_without_javascript_redirects(client, room):
    event, alice, _ = room
    client.force_login(alice)
    response = client.post(reverse("chat:post", args=[event.pk]), {"body": "plain form"})
    assert response.url == reverse("chat:room", args=[event.pk])
    assert ChatMessage.objects.get().body == "plain form"


# --- Polling ---------------------------------------------------------------

def test_poll_says_no_change_until_something_happens(client, room):
    event, alice, bob = room
    client.force_login(alice)
    url = reverse("chat:poll", args=[event.pk])
    v = services.version(event)
    assert client.get(url, {"v": v}).status_code == 204
    services.post(event, bob, "new one")
    response = client.get(url, {"v": v})
    assert response.status_code == 200 and b"new one" in response.content
    new_v = services.version(event)
    assert new_v != v
    assert f"?v={new_v}" in response.content.decode(), "next poll asks with the new version"
    assert client.get(url, {"v": new_v}).status_code == 204


def test_version_changes_when_a_message_is_removed_or_reported(room, admin_user):
    event, alice, bob = room
    msg = services.post(event, alice, "hmm")
    v1 = services.version(event)
    services.report(msg, bob)
    v2 = services.version(event)
    services.delete(msg, admin_user)
    assert len({v1, v2, services.version(event)}) == 3


def test_latest_keeps_the_newest_and_puts_them_in_order(room):
    event, alice, _ = room
    for i in range(5):
        services.post(event, alice, f"m{i}")
    rows, has_older = services.latest(event, alice, limit=3)
    assert [m.body for m in rows] == ["m2", "m3", "m4"] and has_older
    rows, has_older = services.latest(event, alice, limit=10)
    assert len(rows) == 5 and not has_older


def test_poll_query_count_is_flat(client, room, make_user, django_assert_max_num_queries):
    event, alice, _ = room
    for i in range(30):
        user = make_user()
        registration.admin_add(event, user.player, override=True)
        services.post(event, user, f"hello {i}")
    client.force_login(alice)
    with django_assert_max_num_queries(10):
        assert client.get(reverse("chat:poll", args=[event.pk])).status_code == 200


# --- Reporting -------------------------------------------------------------

def test_players_can_report_others_but_not_themselves(room):
    event, alice, bob = room
    msg = services.post(event, alice, "rude")
    with pytest.raises(services.ChatError):
        services.report(msg, alice)
    services.report(msg, bob)
    services.report(msg, bob)  # twice is fine, counts once
    assert ChatReport.objects.filter(message=msg).count() == 1
    assert services.open_report_count(event) == 1


def test_reporter_sees_thanks_and_admin_sees_the_flag(client, room, admin_user):
    event, alice, bob = room
    msg = services.post(event, alice, "rude")
    client.force_login(bob)
    html = client.post(reverse("chat:report", args=[msg.pk]), **HX).content.decode()
    assert "You reported this" in html

    client.force_login(alice)
    html = client.get(reverse("chat:room", args=[event.pk])).content.decode()
    assert "Reported" not in html.split('id="chat-list"')[1], "players don't see report counts"

    client.force_login(admin_user)
    manage = client.get(reverse("events:manage_event", args=[event.pk])).content.decode()
    assert "1 reported message" in manage
    html = client.get(reverse("chat:room", args=[event.pk])).content.decode()
    assert "It&#x27;s fine, keep it" in html or "It's fine, keep it" in html


def test_admin_keeps_a_reported_message(room, admin_user):
    event, alice, bob = room
    msg = services.post(event, alice, "it was a joke")
    services.report(msg, bob)
    services.keep(msg, admin_user)
    assert services.open_report_count(event) == 0
    assert not ChatMessage.objects.get(pk=msg.pk).is_deleted
    assert AuditLog.objects.filter(action="chat.keep").exists()


# --- Removing --------------------------------------------------------------

def test_admin_removes_a_message(client, room, admin_user):
    event, alice, bob = room
    msg = services.post(event, alice, "bad words")
    services.report(msg, bob)
    client.force_login(admin_user)
    html = client.post(reverse("chat:delete", args=[msg.pk]), **HX).content.decode()
    assert "bad words" not in html and "An organizer removed this message." in html
    msg.refresh_from_db()
    assert msg.deleted_by == admin_user
    assert services.open_report_count(event) == 0, "removing clears its reports"
    log = AuditLog.objects.get(action="chat.delete")
    assert log.old_value == "bad words" and log.event == event


def test_players_cannot_remove_messages(client, room):
    event, alice, bob = room
    msg = services.post(event, alice, "mine")
    client.force_login(bob)
    assert client.post(reverse("chat:delete", args=[msg.pk])).status_code == 403
    client.force_login(alice)
    assert client.post(reverse("chat:delete", args=[msg.pk])).status_code == 403
    assert not ChatMessage.objects.get(pk=msg.pk).is_deleted


# --- Navigation ------------------------------------------------------------

def test_chat_tab_on_player_pages(client, room):
    event, alice, _ = room
    client.force_login(alice)
    html = client.get(reverse("events:event_detail", args=[event.pk])).content.decode()
    assert reverse("chat:room", args=[event.pk]) in html
    page = client.get(reverse("chat:room", args=[event.pk])).content.decode()
    assert "No messages yet" in page and "chat.js" in page
    assert 'hx-trigger="every 4s' in page
