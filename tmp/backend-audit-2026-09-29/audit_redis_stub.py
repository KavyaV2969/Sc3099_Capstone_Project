"""Audit-only Redis double. Does not validate Redis connectivity or atomic Lua."""
import time
import pytest

class MemoryRedis:
    def __init__(self):
        self.values={}
        self.expires={}
    def get(self,key):
        if self.expires.get(key,float('inf'))<=time.monotonic():
            self.values.pop(key,None)
        return self.values.get(key)
    def incr(self,key):
        self.values[key]=int(self.get(key) or 0)+1
        return self.values[key]
    def expire(self,key,seconds):
        self.expires[key]=time.monotonic()+seconds
    def ttl(self,key):
        return max(0,int(self.expires.get(key,time.monotonic())-time.monotonic()))
    def setex(self,key,seconds,value):
        self.values[key]=value
        self.expire(key,seconds)
    def ping(self):
        return True

@pytest.fixture(autouse=True)
def audit_redis_double(monkeypatch):
    from app import rate_limit
    stub=MemoryRedis()
    monkeypatch.setattr(rate_limit,'get_redis_client',lambda:stub)
