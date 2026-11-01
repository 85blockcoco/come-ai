"""Malformed inputs must not break the local HTTP server or produce non-finite JSON."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from academics.router import create_academics_router


@pytest.fixture
def http():
    app = FastAPI()
    app.include_router(create_academics_router())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize('operation,args', [
    ('mean', {'values': [True, False]}),
    ('mean', {'values': [1, 'bad']}),
    ('binomial_pmf', {'n': 2.5, 'k': 1, 'p': 0.5}),
    ('mean', {'values': [1] * 1000}),
    ('normal_cdf', {'x': 1, 'sigma': 0}),
    ('linear_fit', {'xs': [1, 2, 3], 'ys': [1, 2]}),
])
def test_invalid_numeric_inputs_have_explicit_blockers(http, operation, args):
    response = http.post('/api/academics/math/calculate', json={'operation': operation, 'arguments': args})
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()['result'] is None
        assert response.json()['blockers']


def test_complex_roots_are_valid_json(http):
    response = http.post('/api/academics/math/calculate', json={
        'operation': 'roots_quadratic', 'arguments': {'a': 1, 'b': 0, 'c': 1},
    })
    assert response.status_code == 200
    roots = response.json()['result']['roots_raw']
    assert roots == [{'real': 0.0, 'imag': 1.0}, {'real': 0.0, 'imag': -1.0}]


def test_overflow_returns_a_blocker(http):
    response = http.post('/api/academics/finance/calculate', json={
        'operation': 'future_value', 'arguments': {'pv': 1e12, 'rate': 10000, 'periods': 10000},
    })
    assert response.status_code == 200
    assert response.json()['result'] is None
    assert response.json()['blockers']


@pytest.mark.parametrize('task', [
    {'title': 'Bad estimate', 'due': '2026-11-03', 'estimate_minutes': 'many'},
    {'title': 'Negative estimate', 'due': '2026-11-03', 'estimate_minutes': -10},
    {'title': 'Unknown date', 'due': 'not-a-date', 'estimate_minutes': 20},
    {'title': 'Impossible date', 'due': '2026-02-31', 'estimate_minutes': 20},
])
def test_bad_daily_task_does_not_crash_server(http, task):
    response = http.post('/api/academics/daily/plan', json={'tasks': [task]})
    assert response.status_code == 422


def test_large_bond_schedule_is_refused_before_allocating(http, monkeypatch):
    def forbidden_allocation(*args, **kwargs):
        raise AssertionError('The oversized schedule must be refused before allocation')
    monkeypatch.setattr('academics.finance_core._bond_cashflows', forbidden_allocation)
    # Validation precedes a fixed operation call: no massive cashflow list is built.
    response = http.post('/api/academics/finance/calculate', json={
        'operation': 'bond_price', 'arguments': {'face': 100, 'coupon_rate': .05, 'ytm': .04, 'years': 10000, 'freq': 10000},
    })
    assert response.status_code == 200
    assert response.json()['blockers']
