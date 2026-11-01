"""Approval belongs to one private store and one exact reviewed document."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService


BODY = "Dear Sir or Madam,\n\nI am applying for the Finance Intern position.\n\nYours sincerely,\nSynthetic Candidate"


def make_client(root):
    app = FastAPI()
    app.include_router(create_career_router(CareerService(root)))
    return TestClient(app)


def approve(http, **overrides):
    return http.post('/api/career/letter/approve', json={
        'letter_id': 'reviewed', 'approved': True, 'letter_body': BODY,
        'language': 'en', **overrides,
    }).json()


def export(http, **overrides):
    return http.post('/api/career/letter/export', json={
        'title': 'reviewed', 'letter_body': BODY, 'language': 'en',
        'fmt': 'md', 'approved': True, 'target': '/ignored/client.md', **overrides,
    })


def test_unbound_approval_does_not_authorize_any_content(tmp_path):
    with make_client(tmp_path) as http:
        response = http.post('/api/career/letter/approve', json={'letter_id': 'reviewed', 'approved': True}).json()
        assert response['approved'] is False
        assert response['blockers']


@pytest.mark.parametrize('change', [{'letter_body': BODY + '\nChanged'}, {'language': 'de'}])
def test_edited_document_must_be_reviewed_again(tmp_path, change):
    with make_client(tmp_path) as http:
        assert approve(http)['approved'] is True
        response = export(http, **change)
        assert response.status_code == 200
        assert response.json()['ok'] is False


def test_approval_persists_restart_and_export_download_matches(tmp_path):
    with make_client(tmp_path) as http:
        assert approve(http)['approved'] is True
    with make_client(tmp_path) as http:
        response = export(http)
        assert response.status_code == 200
        assert response.json()['ok'] is True
        downloaded = http.get(response.json()['download_url'])
        assert downloaded.status_code == 200
        assert BODY in downloaded.text
        assert 'attachment' in downloaded.headers['content-disposition']


def test_store_approval_isolation_and_revocation(tmp_path):
    with make_client(tmp_path / 'one') as one, make_client(tmp_path / 'two') as two:
        assert approve(one)['approved'] is True
        assert export(two).json()['ok'] is False
        assert approve(one, approved=False)['approved'] is False
        assert export(one).json()['ok'] is False


@pytest.mark.parametrize('fmt', ['txt', 'md', 'docx', 'pdf'])
def test_all_export_formats_require_review_and_create_private_files(tmp_path, fmt):
    with make_client(tmp_path) as http:
        assert export(http, fmt=fmt).json()['ok'] is False
        assert approve(http)['approved'] is True
        response = export(http, fmt=fmt).json()
        assert response['ok'] is True
        from pathlib import Path
        path = Path(response['path'])
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
        assert http.get(response['download_url']).status_code == 200


def test_reset_forgets_approval_and_deletes_letter_exports(tmp_path):
    from career.service import DELETE_CONFIRMATION
    service = CareerService(tmp_path)
    service.approve_letter(letter_id='reviewed', approved=True, letter_body=BODY, language='en')
    result = service.export_letter(title='reviewed', letter_body=BODY, language='en', fmt='md')
    assert result['ok'] is True
    service.reset_personal_data(DELETE_CONFIRMATION)
    assert service.export_letter(title='reviewed', letter_body=BODY, language='en', fmt='md')['ok'] is False
    assert list(service.export_dir.glob('career_letter_*')) == []


@pytest.mark.parametrize('fmt', ['../../escape', '../outside/pdf', 'html', ''])
def test_invalid_format_cannot_choose_a_path(tmp_path, fmt):
    with make_client(tmp_path) as http:
        assert approve(http)['approved'] is True
        response = export(http, fmt=fmt)
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            assert response.json()['ok'] is False
