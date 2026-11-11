"""Model failures reach the user as one plain line, never a traceback."""

import anthropic
import httpx2
import pytest

from director import cli
from director.models.anthropic_model import NO_CREDENTIALS, NO_CREDITS, AnthropicModel
from director.models.base import ModelError, ModelSetupError

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code, message="boom"):
    return cls(message, response=httpx2.Response(code, request=REQUEST), body=None)


class FailingClient:
    """Stands in for anthropic.Anthropic; every request raises `error`."""

    def __init__(self, error):
        def create(**kwargs):
            raise error

        self.beta = type("Beta", (), {"messages": type("Messages", (), {"create": staticmethod(create)})})()


def conversation(error):
    return AnthropicModel(client=FailingClient(error)).start("system", [])


@pytest.mark.parametrize(
    "error, kind, text",
    [
        (TypeError('"Could not resolve authentication method. Expected one of api_key"'),
         ModelSetupError, NO_CREDENTIALS),
        (status_error(anthropic.AuthenticationError, 401), ModelSetupError, "rejected your credentials"),
        (status_error(anthropic.APIStatusError, 402), ModelSetupError, NO_CREDITS),
        (status_error(anthropic.BadRequestError, 400, "Your credit balance is too low"),
         ModelSetupError, NO_CREDITS),
        (status_error(anthropic.NotFoundError, 404), ModelSetupError, "wasn't found"),
        (anthropic.APIConnectionError(request=REQUEST), ModelError, "Couldn't reach"),
        (status_error(anthropic.RateLimitError, 429), ModelError, "rate-limiting"),
        (status_error(anthropic.InternalServerError, 500), ModelError, "(500)"),
    ],
)
def test_sdk_errors_become_plain_messages(error, kind, text):
    with pytest.raises(kind) as caught:
        conversation(error).send_user("hi")
    assert text in str(caught.value)


def test_retryable_errors_are_not_setup_errors():
    with pytest.raises(ModelError) as caught:
        conversation(anthropic.APIConnectionError(request=REQUEST)).send_user("hi")
    assert not isinstance(caught.value, ModelSetupError)


def test_unrelated_type_error_still_raises():
    with pytest.raises(TypeError):
        conversation(TypeError("something else")).send_user("hi")


def test_failed_request_is_rolled_back():
    convo = conversation(anthropic.APIConnectionError(request=REQUEST))
    convo.messages = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    with pytest.raises(ModelError):
        convo.send_user("this one fails")
    assert [m["content"] for m in convo.messages] == ["earlier", "ok"]


def test_cli_prints_one_line_and_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_model", lambda *a, **k: AnthropicModel(
        client=FailingClient(status_error(anthropic.APIStatusError, 402))))
    monkeypatch.setattr(cli, "ensure_not_root", lambda: None)
    assert cli.main(["hello"]) == 1
    err = capsys.readouterr().err
    assert err == f"director: {NO_CREDITS}\n"


def test_cli_local_backend_without_ollama_is_friendly(monkeypatch, capsys):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("OLLAMA_HOST", f"127.0.0.1:{port}")
    monkeypatch.setattr(cli, "ensure_not_root", lambda: None)
    assert cli.main(["--backend", "local", "hello"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("director: Can't reach Ollama at")
    assert "Traceback" not in err
