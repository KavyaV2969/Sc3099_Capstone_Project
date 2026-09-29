"""Isolated audit reproductions; no changes to application or live database."""
import os
import sys
import json
import importlib.util
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'module2-backend'))
os.environ.setdefault('SECRET_KEY', 'audit-only-placeholder-secret-over-32-characters')
os.environ['RETENTION_CLEANUP_ENABLED'] = 'false'

import pytest
from sqlalchemy import select
from app.models import User, Course, Device, Enrollment, Session, AuditLog, Checkin, utc_now
from app.face_service import FaceResult
from app.schemas import UserRole
from app.security import create_access_token

spec = importlib.util.spec_from_file_location('week3_audit_fixture', root / 'module2-backend/tests/test_week3.py')
week3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(week3)
results = []

def record(case, **data):
    results.append({'case': case, **data})
    print(json.dumps(results[-1], default=str))

@contextmanager
def isolated():
    patcher = pytest.MonkeyPatch()
    patcher.setattr('app.routers.checkins.enforce_checkin_limit', lambda _: None)
    generator = week3.api.__wrapped__(patcher)
    api = next(generator)
    try:
        yield api, patcher
    finally:
        generator.close()
        patcher.undo()

def setup(api):
    course = week3.course.__wrapped__(api)
    session = week3.session.__wrapped__(api, course)
    enrollment = week3.enrollment.__wrapped__(api, course)
    ready = week3.ready.__wrapped__(api, session, enrollment)
    return course, ready

with isolated() as (api, patcher):
    course, session = setup(api)
    with api.database() as db:
        db.get(Session, session['id']).risk_threshold = 0
        db.commit()
    r = api.request('POST', '/checkins/', 'student', json=week3.checkin_payload(session, location_accuracy_meters=10000))
    record('required_liveness_omitted_threshold_zero_accuracy_10000', http=r.status_code,
           status=r.json().get('status'), risk_score=r.json().get('risk_score'),
           liveness_passed=r.json().get('liveness_passed'), risk_factors=r.json().get('risk_factors'))

for known in [False, True]:
    with isolated() as (api, patcher):
        course, session = setup(api)
        if known:
            api.request('POST', '/devices/register', 'student', json={
                'device_fingerprint': 'test-device', 'device_name': 'Phone', 'platform': 'web', 'public_key': 'arbitrary-text'})
        r = api.request('POST', '/checkins/', 'student', json=week3.checkin_payload(session, latitude=1.34965))
        record('geofence_150m_known_device_' + str(known), http=r.status_code,
               status=r.json().get('status'), risk_score=r.json().get('risk_score'))

with isolated() as (api, patcher):
    course, session = setup(api)
    with api.database() as db:
        db.get(Session, session['id']).require_face_match = True
        student = db.get(User, api.users['student'].id)
        student.face_enrolled = True
        student.face_embedding_hash = 'a' * 64
        db.commit()
    async def empty_service(path, payload):
        return {}
    patcher.setattr('app.face_service._post', empty_service)
    r = api.request('POST', '/checkins/', 'student', json=week3.checkin_payload(session, liveness_challenge_response='image'))
    record('required_face_and_liveness_service_returns_empty_object', http=r.status_code,
           status=r.json().get('status'), liveness_passed=r.json().get('liveness_passed'), face_match_passed=r.json().get('face_match_passed'))

with isolated() as (api, patcher):
    async def malformed_service(path, payload):
        return {'enrollment_successful': True, 'face_template_hash': 'invalid'}
    patcher.setattr('app.face_service._post', malformed_service)
    try:
        api.request('POST', '/users/me/face/enroll', 'student', json={'image': 'image'})
    except Exception as exc:
        record('malformed_face_service_schema', exception=type(exc).__name__)

with isolated() as (api, patcher):
    async def low_quality(path, payload):
        return {'enrollment_successful': True, 'face_template_hash': 'b'*64, 'quality_score': 0.1}
    patcher.setattr('app.face_service._post', low_quality)
    r = api.request('POST', '/users/me/face/enroll', 'student', json={'image': 'image'})
    record('low_quality_face_enrollment', http=r.status_code, face_enrolled=r.json().get('face_enrolled'), quality=r.json().get('quality_score'))

with isolated() as (api, patcher):
    r = api.request('POST', '/devices/register', 'student', json={
        'device_fingerprint': 'key-device', 'device_name': 'Phone', 'platform': 'web', 'public_key': 'invalid-key'})
    did = r.json()['id']
    api.request('PATCH', '/devices/' + did, 'admin', json={'is_trusted': True})
    api.request('DELETE', '/devices/' + did, 'admin')
    r = api.request('POST', '/devices/register', 'student', json={
        'device_fingerprint': 'key-device', 'device_name': 'New Phone', 'platform': 'web', 'public_key': None})
    with api.database() as db:
        device = db.get(Device, did)
        first_log = db.scalar(select(AuditLog).where(AuditLog.action == 'device_registered').order_by(AuditLog.timestamp))
        record('owner_reactivates_admin_revoked_device_and_removes_key', http=r.status_code,
               active=device.is_active, trusted=device.is_trusted, public_key=device.public_key,
               initial_audit_resource_id=first_log.resource_id, initial_audit_device_id=first_log.device_id)

with isolated() as (api, patcher):
    r = api.request('POST', '/courses/', 'admin', json={'code': 'UNASSIGNED', 'name': 'Unassigned', 'semester': 'AY26',
        'venue_latitude': 1.3483, 'venue_longitude': 103.6831})
    course = r.json()
    session = api.request('POST', '/sessions/', json=week3.session_payload(course)).json()
    api.request('POST', '/enrollments/', json={'course_id':course['id'], 'student_id':api.users['student'].id})
    record('session_owner_unassigned_course_relationship',
           roster=api.request('GET', '/enrollments/course/' + course['id']).status_code,
           user_detail=api.request('GET', '/users/' + api.users['student'].id).status_code,
           student_statistics=api.request('GET', '/stats/students/' + api.users['student'].id).status_code)
    other = api.request('POST', '/sessions/', 'other_instructor', json=week3.session_payload(course)).json()
    record('course_permissions_have_different_scope',
           other_session_detail=api.request('GET', '/sessions/' + other['id']).status_code,
           other_session_checkins=api.request('GET', '/checkins/session/' + other['id']).status_code,
           own_session_list_count=api.request('GET', '/sessions/').json()['total'])

with isolated() as (api, patcher):
    course, session = setup(api)
    foreign_course = api.request('POST', '/courses/', 'admin', json={'code':'OTHER','name':'Other', 'semester':'AY26',
        'instructor_id':api.users['other_instructor'].id, 'venue_latitude':1.3483,'venue_longitude':103.6831}).json()
    api.request('POST', '/admin/enrollments/', 'admin', json={'course_id':foreign_course['id'],'student_id':api.users['student'].id})
    r = api.request('GET', '/stats/students/' + api.users['student'].id)
    record('student_stats_include_unrelated_course', http=r.status_code,
           course_codes=[c['course_code'] for c in r.json()['courses']])
    api.request('DELETE', '/courses/' + course['id'], 'admin')
    r = api.request('POST', '/admin/enrollments/', 'admin', json={'course_id':course['id'], 'student_id':api.users['other_student'].id})
    record('admin_enrollment_inactive_course', http=r.status_code)

with isolated() as (api, patcher):
    course, session = setup(api)
    api.request('POST', '/checkins/', 'student', json=week3.checkin_payload(session))
    api.request('PATCH', '/sessions/' + session['id'], json={'status': 'closed'})
    api.request('PATCH', '/admin/sessions/' + session['id'] + '/status', 'admin', json={'status': 'scheduled'})
    try:
        api.request('DELETE', '/sessions/' + session['id'])
    except Exception as exc:
        record('admin_rescheduled_session_with_checkin_then_delete', exception=type(exc).__name__)

with isolated() as (api, patcher):
    from sqlalchemy.exc import IntegrityError
    original = __import__('sqlalchemy.orm', fromlist=['Session']).Session.flush
    def race_flush(self, *args, **kwargs):
        if any(isinstance(obj, User) and obj.email == 'race@example.com' for obj in self.new):
            raise IntegrityError('simulated concurrent email conflict', {}, Exception('unique'))
        return original(self, *args, **kwargs)
    patcher.setattr('sqlalchemy.orm.Session.flush', race_flush)
    try:
        api.request('POST', '/admin/users/bulk', 'admin', json={'users':[
            {'email':'race@example.com','password':'password123','full_name':'Race'}]})
    except Exception as exc:
        record('bulk_user_integrity_error_handler', exception=type(exc).__name__, message=str(exc))

with isolated() as (api, patcher):
    course, session = setup(api)
    # Registration and login are not needed to confirm standard error/CORS shapes.
    r = api.request('GET', '/users/me', None, headers={'Origin':'http://localhost:3000'})
    record('cors_exposed_headers', http=r.status_code, exposed=r.headers.get('access-control-expose-headers'))
    # The token generator has no nonce, so identical claims within one second produce identical JWTs.
    user = api.users['student']
    one = create_access_token(user.id, user.email, UserRole.STUDENT)
    two = create_access_token(user.id, user.email, UserRole.STUDENT)
    record('token_pair_generated_same_second', tokens_identical=one == two)

(root / 'tmp/backend-audit/probe-results.json').write_text(json.dumps(results, indent=2, default=str), encoding='utf-8')

for mutation in ['close_session', 'deactivate_user', 'enable_face_match']:
    with isolated() as (api, patcher):
        api.database.configure(expire_on_commit=True)
        course, session = setup(api)
        async def change_while_awaiting(image):
            with api.database() as db:
                if mutation == 'close_session':
                    db.get(Session, session['id']).status = 'closed'
                elif mutation == 'deactivate_user':
                    db.get(User, api.users['student'].id).is_active = False
                else:
                    db.get(Session, session['id']).require_face_match = True
                    student = db.get(User, api.users['student'].id)
                    student.face_enrolled, student.face_embedding_hash = True, 'c'*64
                db.commit()
            return FaceResult(liveness_passed=True, liveness_score=.9)
        patcher.setattr('app.routers.checkins.check_liveness', change_while_awaiting)
        r = api.request('POST', '/checkins/', 'student', json=week3.checkin_payload(session, liveness_challenge_response='image'))
        record('state_change_during_biometrics_' + mutation, http=r.status_code, status=r.json().get('status'),
               face_match_passed=r.json().get('face_match_passed'))

(root / 'tmp/backend-audit/probe-results.json').write_text(json.dumps(results, indent=2, default=str), encoding='utf-8')
