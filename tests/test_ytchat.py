"""Live chat parsing against a recorded get_live_chat response (author renamed)."""

import json
from pathlib import Path

from quiz.ytchat import parse_chat, parse_page

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "live_chat_response.json").read_text())


def test_chat_messages_authors_and_next_token():
    messages, token, wait = parse_chat(RECORDED)
    assert messages == [("LifelongQuiz", "1"), ("Viewer_1", "1"), ("Viewer_1", "!crew  Night Owls")]
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
