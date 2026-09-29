"""Read-only audit of backend logic using isolated in-memory API fixtures."""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'module2-backend'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'module2-backend/tests'))
from test_week3 import course, session, enrollment, ready, checkin_payload
from app.models import Session, Checkin, utc_now
from app.services.reporting import SINGAPORE, business_day


def test_explicit_session_export_matches_statistics_across_singapore_midnight(api, ready):
    # Valid custom early window remains open, scheduled start falls next SG day.
    tomorrow = business_day(utc_now()) + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time(), SINGAPORE).astimezone(timezone.utc)
    response = api.request('PATCH', f"/sessions/{ready['id']}", json={
        'scheduled_start':start.isoformat(),'scheduled_end':(start+timedelta(hours=1)).isoformat(),
        'checkin_opens_at':(utc_now()-timedelta(minutes=1)).isoformat(),
        'checkin_closes_at':(start+timedelta(minutes=30)).isoformat()})
    assert response.status_code==200, response.text
    checked = api.request('POST','/checkins/','student',json=checkin_payload(ready))
    assert checked.status_code==201, checked.text
    stats = api.request('GET', f"/stats/sessions/{ready['id']}").json()
    exported = api.request('GET', f"/export/session/{ready['id']}?format=json").json()
    print({'session_stats_count':stats['checked_in'],'export_total':exported['summary']['total'],
           'export_approved_attendance':exported['summary']['approved_attendance'],
           'export_records':len(exported['records']), 'export_denominator_available':exported['coverage']['denominator_available']})
    assert exported['summary']['total']==stats['checked_in']
    assert len(exported['records'])==1


def test_reactivation_adds_newly_eligible_student_to_active_roster(api, course, session):
    uid = api.users['other_student'].id
    # Entire setup uses supported APIs: enroll -> deactivate -> activate session.
    assert api.request('POST','/enrollments/',json={'course_id':course['id'],'student_id':uid}).status_code==201
    assert api.request('POST','/enrollments/',json={'course_id':course['id'],'student_id':api.users['student'].id}).status_code==201
    assert api.request('PATCH',f'/admin/users/{uid}/deactivate','admin').status_code==200
    assert api.request('PATCH',f"/sessions/{session['id']}",json={'status':'active'}).status_code==200
    assert api.request('PATCH',f'/admin/users/{uid}/activate','admin').status_code==200
    checked=api.request('POST','/checkins/','other_student',json=checkin_payload(session))
    assert checked.status_code==201, checked.text
    stats=api.request('GET', f"/stats/sessions/{session['id']}").json()
    print({'approved_submissions':stats['by_status']['approved'],'approved_attendance':stats['approved_attendance'],
           'eligible_roster':stats['total_enrolled'],'checkin_status':checked.json()['status']})
    assert stats['approved_attendance']==stats['by_status']['approved']


# The final reproduction uses independently migrated disposable PostgreSQL.
import pytest
from test_f00_postgresql import pg_database, canonical
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.db import get_db
from app.main import app
from app.models import User
from app.schemas import UserRole
from app.security import create_access_token

@pytest.fixture
def api(canonical):
    factory=sessionmaker(canonical,autoflush=False,expire_on_commit=False)
    with factory() as db:
        users={}
        for label in ['admin','instructor','other_instructor','student','other_student','ta']:
            user=User(email=label+'@example.com',full_name=label,role=label.removeprefix('other_'),
                      hashed_password='unused',camera_consent=True,geolocation_consent=True)
            db.add(user); db.flush(); users[label]=user
        db.commit()
    def override():
        with factory() as db:
            try: yield db
            except Exception:
                db.rollback(); raise
    app.dependency_overrides[get_db]=override
    try:
        with TestClient(app) as client:
            class API:
                def request(self,method,path,role='instructor',**kwargs):
                    user=users[role]
                    headers={'Authorization':'Bearer '+create_access_token(user.id,user.email,UserRole(user.role)),
                             'X-Forwarded-For':'127.0.0.1'}
                    return client.request(method,'/api/v1'+path,headers=headers,**kwargs)
            instance=API(); instance.users=users; instance.database=factory
            yield instance
    finally: app.dependency_overrides.pop(get_db,None)


def test_retention_clamping_does_not_return_an_inverted_supported_range(api, ready):
    start=(utc_now()-timedelta(days=60)).isoformat()
    end=(utc_now()-timedelta(days=45)).isoformat()
    response=api.request('GET', f"/stats/courses/{ready['course_id']}", params={'start_date':start,'end_date':end})
    if response.status_code==422:
        return
    assert response.status_code==200
    data=response.json()
    print({'coverage':data['coverage'],'attendance_rate':data['overall_attendance_rate']})
    assert data['coverage']['start'] <= data['coverage']['end']
    assert data['coverage']['denominator_available'] is False
    assert data['overall_attendance_rate'] is None
