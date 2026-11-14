"""Automatic key selection and the Anthropic adapter, without network calls."""
import json
import time

import httpx
import pytest

from canary.assistant import providers, tools
from canary.assistant.contracts import ToolContext, ToolResult
from canary.config import settings


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for key in ('GEMINI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings, 'llm_provider', 'auto')
    monkeypatch.setattr(settings, 'llm_model', '')


@pytest.mark.parametrize('gemini,anthropic,expected', [
    ('', '', 'none'), ('g', '', 'gemini'), ('', 'a', 'anthropic'),
    ('g', 'a', 'gemini'), ('  ', 'a', 'anthropic'), ('', '  ', 'none'),
])
def test_auto_selection(monkeypatch, gemini, anthropic, expected):
    monkeypatch.setenv('GEMINI_API_KEY', gemini)
    monkeypatch.setenv('ANTHROPIC_API_KEY', anthropic)
    result = providers.status()
    assert result['provider'] == expected
    assert result['selection'] == 'auto'
    assert result['configured'] == (expected != 'none')
    assert result['model'] == {'none': None, 'gemini': settings.gemini_model,
                               'anthropic': settings.anthropic_model}[expected]


@pytest.mark.parametrize('selection', ['none', 'gemini', 'anthropic', 'local'])
def test_explicit_selection_wins(monkeypatch, selection):
    monkeypatch.setenv('GEMINI_API_KEY', 'g')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'a')
    monkeypatch.setattr(settings, 'llm_provider', selection)
    assert providers.get_provider().name == selection


def test_explicit_missing_key_does_not_switch(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'g')
    monkeypatch.setattr(settings, 'llm_provider', 'anthropic')
    provider = providers.get_provider()
    assert provider.name == 'anthropic' and not provider.configured


def test_key_changes_are_seen_on_next_selection(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'g')
    assert providers.get_provider().name == 'gemini'
    monkeypatch.delenv('GEMINI_API_KEY')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'a')
    assert providers.get_provider().name == 'anthropic'


def test_models_are_independent(monkeypatch):
    monkeypatch.setattr(settings, 'gemini_model', 'gemini-custom')
    monkeypatch.setattr(settings, 'anthropic_model', 'claude-custom')
    assert providers.GeminiProvider().model == 'gemini-custom'
    assert providers.AnthropicProvider().model == 'claude-custom'
    monkeypatch.setattr(settings, 'llm_model', 'explicit-override')
    assert providers.AnthropicProvider().model == 'explicit-override'
    assert providers.GeminiProvider().model == 'explicit-override'


def native(content, reason='end_turn'):
    return {'model': 'claude-test', 'stop_reason': reason, 'content': content,
            'usage': {'input_tokens': 10, 'cache_read_input_tokens': 3,
                      'cache_creation_input_tokens': 2, 'output_tokens': 5}}


def text(data):
    return {'type': 'text', 'text': json.dumps(data)}


def req(task='chat'):
    return providers.ProviderRequest(task=task, system='rules', question='sleep',
        ctx=ToolContext(crew_id='h', viewer='h', medical=False, mission={}))


def test_anthropic_tool_loop_preserves_signatures_and_validates_arguments(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    calls, executed = [], []
    signed = [{'type': 'thinking', 'thinking': 'private', 'signature': 'signed'},
              {'type': 'tool_use', 'id': 'one', 'name': 'get_indicator', 'input': {'ind': 'sleep'}},
              {'type': 'tool_use', 'id': 'two', 'name': 'get_indicator', 'input': {'ind': 'sleep', 'crew_id': 'k'}}]
    def run(ctx, name, args):
        executed.append((ctx.crew_id, name, args))
        return ToolResult(data={'value': 6}, sources=['telemetry:h:sleep:day147'])
    monkeypatch.setattr(tools, 'run_tool', run)
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer test-key'
        assert request.headers['anthropic-version'] == '2026-10-21'
        assert request.url == 'https://api.anthropic.com/v1/messages'
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            assert body['model'] == settings.anthropic_model
            assert body['thinking'] == {'type': 'adaptive'}
            assert body['output_config']['format']['type'] == 'json_schema'
            assert all(t['strict'] for t in body['tools'])
            assert body['fallbacks'] == 'default'
            return httpx.Response(200, json=native(signed, 'tool_use'))
        assert body['messages'][1]['content'] == signed
        results = body['messages'][2]['content']
        assert [r['tool_use_id'] for r in results] == ['one', 'two']
        assert results[1]['is_error'] and 'crew_id' in results[1]['content']
        return httpx.Response(200, json=native([text({'answer': 'Rest'})]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = providers.AnthropicProvider(client).complete(req())
    assert out.ok and out.steps == 2 and out.model == 'claude-test'
    assert executed == [('h', 'get_indicator', {'ind': 'sleep'})]
    assert out.sources == ['telemetry:h:sleep:day147']
    assert out.input_tokens == 30 and out.output_tokens == 10


@pytest.mark.parametrize('task', ['briefing', 'suggestions'])
def test_anthropic_entries_without_tools(task):
    data = {'items': [{'id': 'rest', 'why': 'Rest'}]} if task == 'suggestions' else {'sections': []}
    def handler(request):
        body = json.loads(request.content)
        assert 'tools' not in body and 'tool_choice' not in body
        assert 'Computed facts' in body['messages'][0]['content']
        return httpx.Response(200, json=native([text(data)]))
    request = req(task)
    request.context = [{'sleep': 6}]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = providers.AnthropicProvider(client).complete(request)
    assert out.ok and json.loads(out.answer) == (data['items'] if task == 'suggestions' else data)


@pytest.mark.parametrize('reason,flag', [('refusal', 'model:refusal'), ('max_tokens', 'model:max_tokens'),
                                       ('pause_turn', 'model:bad_output')])
def test_anthropic_stop_reasons(reason, flag):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=native([], reason)))) as client:
        out = providers.AnthropicProvider(client).complete(req())
    assert not out.ok and out.guard_exit == flag


def test_anthropic_deadline():
    request = req()
    request.deadline = time.monotonic() - 1
    out = providers.AnthropicProvider().complete(request)
    assert out.guard_exit == 'loop:timeout'


@pytest.mark.parametrize('cls', [providers.GeminiProvider, providers.AnthropicProvider])
def test_transport_failure_never_calls_other_provider(monkeypatch, cls):
    monkeypatch.setenv('GEMINI_API_KEY', 'g')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'a')
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429, json={'error': {'message': 'secret'}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = cls(client).complete(req())
    assert out.guard_exit == 'api:rate_limit' and len(calls) == 1
    assert 'secret' not in out.error


@pytest.mark.parametrize('cls', [providers.GeminiProvider, providers.AnthropicProvider])
def test_unavailable_retries_then_recovers(monkeypatch, cls):
    clock = [0.0]
    waits, requests = [], []
    monkeypatch.setattr(providers.time, 'monotonic', lambda: clock[0])
    def sleep(delay):
        waits.append(delay)
        clock[0] += delay
    monkeypatch.setattr(providers.time, 'sleep', sleep)
    def handler(request):
        requests.append(request)
        if len(requests) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={'ok': True})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = cls(client)._post('https://example.test/generate', {'prompt': 'test'}, {}, 10)
    assert result == {'ok': True} and waits == [1, 2]
    assert len(requests) == 3
    assert len({r.content for r in requests}) == 1
    assert [r.extensions['timeout']['read'] for r in requests] == [10, 9, 7]


@pytest.mark.parametrize('budget,retry_after,expected', [(60, '', 3), (0.5, '', 1), (10, '20', 1)])
def test_unavailable_retries_are_bounded(monkeypatch, budget, retry_after, expected):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(providers.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(providers.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    def handler(request):
        calls.append(request)
        return httpx.Response(503, headers={'retry-after': retry_after})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            providers.GeminiProvider(client)._post('https://example.test/generate', {}, {}, budget)
    assert caught.value.response.status_code == 503 and len(calls) == expected


def test_timeouts_are_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout', request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):
            providers.GeminiProvider(client)._post('https://example.test/generate', {}, {}, 10)
    assert len(calls) == 1
