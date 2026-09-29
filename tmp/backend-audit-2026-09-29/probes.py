"""Audit-only synthetic SQLite reproductions. Never touches the live database."""
import os
import sys
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'module2-backend'), str(ROOT / 'module2-backend/tests')]
os.environ.setdefault('SECRET_KEY', 'audit-only-secret-with-more-than-32-characters')
os.environ['RETENTION_CLEANUP_ENABLED'] = 'false'

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from app.models import User, Course, Device, Enrollment, Session, AuditLog, Checkin, utc_now
from app.main import app
import test_week3 as fixtures

results = []
def record(case, **values):
    results.append(dict(case=case, **values))
    print(json.dumps(results[-1], default=str))

@contextmanager
def isolated():
    patch = pytest.MonkeyPatch()
    patch.setattr('app.routers.checkins.enforce_checkin_limit', lambda _: None)
    generator = fixtures.api.__wrapped__(patch)
    api = next(generator)
    try:
        yield api, patch
    finally:
        generator.close()
        patch.undo()

def setup(api):
    course = fixtures.course.__wrapped__(api)
    session = fixtures.session.__wrapped__(api, course)
    enrollment = fixtures.enrollment.__wrapped__(api, course)
    return course, fixtures.ready.__wrapped__(api, session, enrollment)

with isolated() as (api, patch):
    course = api.request('POST', '/courses/', 'admin', json={
        'code':'UNASSIGNED','name':'Unassigned','semester':'AY26',
        'venue_latitude':1.3483,'venue_longitude':103.6831}).json()
    first = api.request('POST', '/sessions/', json=fixtures.session_payload(course)).json()
    api.request('POST','/enrollments/',json={'course_id':course['id'],'student_id':api.users['student'].id})
    record('session_owner_relationship',
        roster=api.request('GET','/enrollments/course/'+course['id']).status_code,
        profile=api.request('GET','/users/'+api.users['student'].id).status_code,
        stats=api.request('GET','/stats/students/'+api.users['student'].id).status_code)
    other=api.request('POST','/sessions/','other_instructor',json=fixtures.session_payload(course)).json()
    record('same_course_different_session_owner',
        own_list=api.request('GET','/sessions/').json()['total'],
        other_session_roster=api.request('GET','/checkins/session/'+other['id']).status_code,
        other_session_export=api.request('GET','/export/session/'+other['id']).status_code)

with isolated() as (api, patch):
    course, session = setup(api)
    other=api.request('POST','/courses/','admin',json={'code':'PRIVATE','name':'Other Course','semester':'AY26',
        'instructor_id':api.users['other_instructor'].id,'venue_latitude':1.3483,'venue_longitude':103.6831}).json()
    api.request('POST','/admin/enrollments/','admin',json={'course_id':other['id'],'student_id':api.users['student'].id})
    r=api.request('GET','/stats/students/'+api.users['student'].id)
    record('student_stats_cross_course',http=r.status_code,courses=[c['course_code'] for c in r.json()['courses']])
    api.request('DELETE','/courses/'+course['id'],'admin')
    r=api.request('POST','/enrollments/bulk',json={'course_id':course['id'],
        'student_emails':[api.users['other_student'].email]})
    record('bulk_enrollment_inactive_course',http=r.status_code,body=r.json())

with isolated() as (api, patch):
    payload={'device_fingerprint':'audit-device','device_name':'Phone','platform':'web','public_key':'not-a-key'}
    r=api.request('POST','/devices/register','student',json=payload)
    did=r.json()['id']
    trusted=api.request('PATCH','/devices/'+did,'admin',json={'is_trusted':True})
    api.request('DELETE','/devices/'+did,'admin')
    payload['public_key']='different-not-a-key'
    r=api.request('POST','/devices/register','student',json=payload)
    record('revoked_device_reregistered_with_changed_key',initial_trust_http=trusted.status_code,
        http=r.status_code,active=r.json()['is_active'],trusted=r.json()['is_trusted'])

with isolated() as (api, patch):
    course, session=setup(api)
    r=api.request('POST','/checkins/','student',json=fixtures.checkin_payload(session,latitude=1.351))
    stats=api.request('GET','/stats/sessions/'+session['id']).json()
    exported=api.request('GET','/export/session/'+session['id']+'?format=json').json()
    record('rejected_attendance_denominator',http=r.status_code,status=r.json()['status'],
        stats_attendance_rate=stats['attendance_rate'],export_attendance_rate=exported['summary']['attendance_rate'])
    api.request('PATCH','/sessions/'+session['id'],json={'status':'closed'})
    api.request('PATCH','/admin/sessions/'+session['id']+'/status','admin',json={'status':'scheduled'})
    try:
        api.request('DELETE','/sessions/'+session['id'])
    except Exception as exc:
        record('delete_admin_rescheduled_with_checkin',exception=type(exc).__name__)

with isolated() as (api, patch):
    course, session=setup(api)
    r=api.request('POST','/enrollments/bulk',json={'course_id':course['id'],
        'student_emails':['new@example.com'],'create_accounts':True})
    record('documented_bulk_account_creation',http=r.status_code,body=r.json())
    with api.database() as db:
        event=db.scalar(select(AuditLog))
        event.action='audit_tampered'
        db.commit()
        eid=event.id
        db.delete(event)
        db.commit()
        record('audit_update_delete',deleted=db.get(AuditLog,eid) is None)

for target in ['register','bulk_users','enroll','bulk_enroll','admin_enroll']:
    with isolated() as (api, patch):
        course, session=setup(api)
        original=DBSession.flush
        def conflict(self,*args,**kwargs):
            for obj in self.new:
                if (isinstance(obj,User) and obj.email=='race@example.com') or (
                    isinstance(obj,Enrollment) and obj.student_id==api.users['other_student'].id):
                    raise IntegrityError('synthetic concurrent unique conflict',{},Exception('unique'))
            return original(self,*args,**kwargs)
        patch.setattr(DBSession,'flush',conflict)
        new_user={'email':'race@example.com','password':'password123','full_name':'Race'}
        enrollment={'course_id':course['id'],'student_id':api.users['other_student'].id}
        path,payload,role={
            'register':('/auth/register',new_user,None),
            'bulk_users':('/admin/users/bulk',{'users':[new_user]},'admin'),
            'enroll':('/enrollments/',enrollment,'instructor'),
            'bulk_enroll':('/enrollments/bulk',{'course_id':course['id'],'student_emails':[api.users['other_student'].email]},'instructor'),
            'admin_enroll':('/admin/enrollments/',enrollment,'admin'),
        }[target]
        patch.setattr('app.routers.auth.enforce_registration_limit',lambda _:None)
        try:
            r=api.request('POST',path,role,json=payload)
            record('injected_unique_conflict_'+target,http=r.status_code)
        except Exception as exc:
            record('injected_unique_conflict_'+target,exception=type(exc).__name__)

with isolated() as (api, patch):
    course, session=setup(api)
    with api.database() as db:
        db.get(User,api.users['student'].id).full_name='=1+1'
        db.commit()
    api.request('POST','/checkins/','student',json=fixtures.checkin_payload(session))
    r=api.request('GET','/export/session/'+session['id'],headers={'Origin':'http://localhost:3000'})
    record('csv_and_cors',formula_unescaped='=1+1' in r.text,
        exposed_headers=r.headers.get('access-control-expose-headers'))
    record('route_inventory',backend_operations=sum(len([m for m in methods if m in {'get','put','post','patch','delete'}])
        for path,methods in app.openapi()['paths'].items() if path.startswith('/api/v1')),
        metrics_present='/metrics' in app.openapi()['paths'])

(Path(__file__).parent/'probe-results.json').write_text(json.dumps(results,indent=2,default=str),encoding='utf-8')
