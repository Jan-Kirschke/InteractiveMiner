"""Live chat parsing against a recorded get_live_chat response (author renamed)."""

import json
from pathlib import Path

from quiz.ytchat import live_chat_token, parse_chat, parse_page

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "live_chat_response.json").read_text())


def test_chat_messages_authors_and_next_token():
    messages, token, wait = parse_chat(RECORDED)
    assert [(a, t) for _, a, t, _ in messages] == [("LifelongQuiz", "1"), ("Viewer_1", "1"), ("Viewer_1", "!crew  Night Owls")]
    assert all(mid and sent > 1.7e9 for mid, _, _, sent in messages)
    assert token.startswith("0ofMyAOR")
    assert wait == 10.0


def test_ended_chat_has_no_token():
    assert parse_chat({"continuationContents": {"liveChatContinuation": {"actions": []}}})[1] == ""
    assert parse_chat({}) == ([], "", 0.0)


def test_page_gives_video_version_and_token():
    data = {"contents": {"twoColumnWatchNextResults": {"conversationBar": {"liveChatRenderer": {
        "continuations": [{"reloadContinuationData": {"continuation": "TOKEN"}}]}}}}}
    html = ('<script>var ytInitialData = ' + json.dumps(data) + ';</script>'
            '"INNERTUBE_CLIENT_VERSION":"2.20261023.01.00"'
            '"currentVideoEndpoint":{"watchEndpoint":{"videoId":"_nNUB0vC7Yw"}}')
    assert parse_page(html) == ("_nNUB0vC7Yw", "2.20261023.01.00", "TOKEN")


def test_page_without_live_chat():
    assert parse_page('ytInitialData = {"contents": {}};"INNERTUBE_CLIENT_VERSION":"2.1"') is None
    assert parse_page("<html>offline</html>") is None


def test_a_message_delivered_twice_counts_once():
    from quiz.ytchat import LiveChat

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return RECORDED

    class Http:
        def post(self, *a, **k):
            return Resp()

    chat = LiveChat("url", session=Http())
    chat._token = "t"
    assert len(chat.poll()[0]) == 3
    assert chat.poll()[0] == []


def test_live_chat_token_switches_top_chat_to_all_messages():
    import base64
    # shape of the live page's token (2026-10-24), trimmed to the view-mode field: 4 = top chat
    top = base64.urlsafe_b64encode(b"\xd2\x87\xcc\xc8\x03\x16\x1a\x000\x01\x82\x01\x0c\x08\x04\x18\x02 \x00").decode()
    live = live_chat_token(top.replace("=", "%3D"))
    assert b"\x82\x01\x0c\x08\x01" in base64.urlsafe_b64decode(live)
    assert live_chat_token("not a token!") == "not a token!"
