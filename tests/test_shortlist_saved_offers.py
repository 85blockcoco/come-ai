import csv
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService


def test_dashboard_uses_saved_deadline_date_and_score(tmp_path):
    app = FastAPI()
    service = CareerService(tmp_path)
    app.include_router(create_career_router(service))
    deadline = (date.today() + timedelta(days=2)).isoformat()
    with TestClient(app) as http:
        job = http.post('/api/career/jobs/import', json={
            'company': 'Synthetic Bank', 'title': 'Finance Intern',
            'deadline_date': deadline, 'source_name': 'synthetic', 'source_id': 'saved-offer',
        }).json()
        http.post(f'/api/career/jobs/{job["id"]}/shortlist', json={'shortlisted': True})
        shortlist = http.get('/api/career/shortlist').json()['offers']
        assert shortlist[0]['deadline'] == deadline
        assert shortlist[0]['score'] == shortlist[0]['scoring']['score']
        text = http.get('/api/career/shortlist?fmt=text').json()['text']
        assert deadline in text
        assert 'urgent_72h' in text


def test_csv_treats_formula_cells_as_text_and_keeps_source_unchanged(tmp_path):
    service = CareerService(tmp_path)
    offers = [{'id': 'synthetic', 'title': '=1+1', 'company': '\t=2+2', 'score': -5}]
    result = service.export_shortlist(offers, 'csv', ['id', 'title', 'company', 'score'])
    assert result['ok'] is True
    with open(result['path'], encoding='utf-8', newline='') as handle:
        row = next(csv.DictReader(handle))
    assert row['title'].startswith("'")
    assert row['company'].startswith("'")
    assert row['score'] == '-5'
    assert offers[0]['title'] == '=1+1'


def test_export_refuses_existing_symlink(tmp_path):
    service = CareerService(tmp_path)
    original = tmp_path / 'original.json'
    original.write_text('preserve me', encoding='utf-8')
    (service.export_dir / 'shortlist.json').symlink_to(original)
    result = service.export_shortlist([{'id': 'synthetic'}], 'json', [])
    assert result['ok'] is False
    assert result['blockers']
    assert original.read_text(encoding='utf-8') == 'preserve me'
