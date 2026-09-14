from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.brain_api import main
from emerald.journal import SQLiteJournal
from emerald.market import TickQuote, TickStore


@pytest.fixture
def api(monkeypatch, tmp_path):
    journal = SQLiteJournal(tmp_path / 'clock.db')
    journal.initialize()
    monkeypatch.setattr(main, 'journal', journal)
    monkeypatch.setattr(main, 'tick_store', TickStore())
    return TestClient(main.app), {'Authorization': f'Bearer {main.settings.api_token}'}


def batch(at, *, observed=None, contract=False):
    data = {
        'broker_id': 'clock-test', 'point': 0.01,
        'ticks': [{'symbol': 'XAUUSD', 'bid': 2500, 'ask': 2500.2,
                   'broker_time': at.isoformat(), 'observed_at': (observed or at).isoformat()}],
    }
    if contract:
        data.update(timestamp_contract='utc-v1', broker_utc_offset_seconds=10800)
    return data


def test_future_broker_clock_rejected_before_storage_or_label_and_incident_recovers(api):
    client, headers = api
    now = datetime.now(UTC)
    response = client.post('/market/ticks', headers=headers, json=batch(now + timedelta(hours=3)))
    assert response.status_code == 422
    assert response.json()['detail'] == 'MARKET_TIMESTAMP_AHEAD_OF_SERVER'
    assert not main.tick_store.stream_statuses()
    incidents = client.get('/incidents', headers=headers).json()['incidents']
    assert [r['code'] for r in incidents] == ['MARKET_TIMESTAMP_AHEAD_OF_SERVER']
    # Offset metadata documents normalization already performed by EA, not a second shift.
    ok = client.post('/market/ticks', headers=headers, json=batch(now, contract=True))
    assert ok.status_code == 200
    assert main.tick_store.snapshot('clock-test', 'XAUUSD')[-1].broker_time == now
    assert not client.get('/incidents', headers=headers).json()['incidents']


def test_historical_tick_cannot_be_observed_before_it_occurred(api):
    client, headers = api
    at = datetime.now(UTC) - timedelta(days=1)
    response = client.post('/market/ticks', headers=headers,
                           json=batch(at, observed=at - timedelta(hours=3)))
    assert response.status_code == 422


def test_backlog_receipt_does_not_make_old_quotes_healthy(api):
    client, headers = api
    now = datetime.now(UTC)
    assert client.post('/market/ticks', headers=headers,
                       json=batch(now - timedelta(hours=1), observed=now, contract=True)).status_code == 200
    stream = client.get('/telemetry/readiness', headers=headers).json()['tick_streams'][0]
    assert not stream['healthy']
    assert stream['tick_age_seconds'] >= 3600


def test_future_quote_in_memory_never_becomes_healthy_by_clamping_age(api):
    client, headers = api
    future = datetime.now(UTC) + timedelta(hours=3)
    main.tick_store.append_many('clock-test', [TickQuote('XAUUSD', 2500, 2500.2, future, future)])
    stream = client.get('/telemetry/readiness', headers=headers).json()['tick_streams'][0]
    assert not stream['healthy']
    assert stream['tick_age_seconds'] < -10000


def test_incomplete_timestamp_contract_is_rejected(api):
    client, headers = api
    payload = batch(datetime.now(UTC), contract=True)
    del payload['broker_utc_offset_seconds']
    assert client.post('/market/ticks', headers=headers, json=payload).status_code == 422


def test_normalized_stream_records_separate_cohort_and_offset_evidence(api, monkeypatch):
    client, headers = api
    monkeypatch.setattr(main.calendar_client, 'context_for',
                        lambda *_a, **_kw: {'source_health': 'HEALTHY', 'matched_event': None})
    at = datetime(2026, 9, 2, tzinfo=UTC)
    bids = [2500, 2500.01, 2500, 2499.99, 2500, 2500.01, 2490, 2494, 2497]
    payload = batch(at, contract=True)
    payload['ticks'] = [dict(batch(at + timedelta(seconds=i))['ticks'][0], bid=p, ask=p + 0.2)
                        for i, p in enumerate(bids)]
    assert client.post('/market/ticks', headers=headers, json=payload).status_code == 200
    event = client.get('/shadow/events', headers=headers).json()['events'][0]
    assert event['detector_version'] == 'mismatch-v0.5.0-utc'
    assert event['payload']['timestamp_contract'] == 'utc-v1'
    assert event['payload']['broker_utc_offset_seconds'] == 10800
