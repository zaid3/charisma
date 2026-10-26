import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from charisma.core import CharismaError
from charisma.monitor import EventStore, make_server, validate_event, valid_origin, RateLimit

EVENT = {'code':'script-error','error':'TypeError','file':'app.js','line':12,'column':3,'count':1,'page':'checkout'}
TOKEN = 'test-only-dashboard-token-123456789'
SITE_KEY = 'public-fixture-key'
ORIGIN = 'https://website.example'


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=EventStore(Path(self.temp.name)/'events.db')

    def test_aggregate_review_reopen_and_retention(self):
        self.store.record(EVENT); self.store.record(EVENT)
        event=self.store.list()[0]; self.assertEqual(event['count'],2)
        self.assertTrue(self.store.review(event['id'])); self.assertTrue(self.store.list()[0]['reviewed'])
        self.store.record(EVENT); self.assertFalse(self.store.list()[0]['reviewed'])
        with patch('charisma.monitor.time.time',return_value=time.time()+31*86400): self.assertEqual(self.store.list(),[])

    def test_schema_rejects_extra_private_fields_and_invalid_types(self):
        for key,value in [('message','private user input'),('page','https://example.com/?email=x'),('file','../a.js'),('line',True),('count',0),('error',[]),('code',[]),('file','<script>')]:
            with self.subTest(key=key),self.assertRaises(CharismaError): validate_event({**EVENT,key:value})

    def test_origins_are_exact_and_public_http_is_rejected(self):
        self.assertEqual(valid_origin('https://example.com/'),'https://example.com')
        self.assertEqual(valid_origin('http://localhost:1234'),'http://localhost:1234')
        for origin in ['https://*','http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com:99999','https://example.com?x=1']:
            with self.subTest(origin=origin),self.assertRaises(CharismaError): valid_origin(origin)

    def test_request_limiter_has_a_bounded_window(self):
        limiter=RateLimit()
        with patch('charisma.monitor.time.monotonic',return_value=1):
            for _ in range(60): self.assertTrue(limiter.allow('fixture'))
            self.assertFalse(limiter.allow('fixture'))
        with patch('charisma.monitor.time.monotonic',return_value=62): self.assertTrue(limiter.allow('fixture'))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.server=make_server('127.0.0.1',0,Path(self.temp.name)/'events.db',[ORIGIN],SITE_KEY,TOKEN)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            connection.request(method,path,body=body,headers=headers or {})
            response=connection.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally: connection.close()

    def ingest(self,event=EVENT,**headers):
        return self.request('POST','/ingest',json.dumps(event),{'Origin':ORIGIN,'X-Charisma-Site-Key':SITE_KEY,'Content-Type':'application/json',**headers})

    def test_browser_report_to_authenticated_dashboard_and_review(self):
        code,headers,_=self.ingest(); self.assertEqual(code,202); self.assertEqual(headers['Access-Control-Allow-Origin'],ORIGIN)
        code,_,_=self.request('GET','/api/events'); self.assertEqual(code,401)
        auth={'Authorization':'Bearer '+TOKEN}
        code,headers,body=self.request('GET','/api/events',headers=auth)
        self.assertEqual(code,200); self.assertNotIn('Access-Control-Allow-Origin',headers)
        event=json.loads(body)['events'][0]; self.assertEqual(event['file'],'app.js')
        self.assertEqual(self.request('POST',f"/api/events/{event['id']}/review")[0],401)
        self.assertEqual(self.request('POST',f"/api/events/{event['id']}/review",headers=auth)[0],200)
        self.assertTrue(json.loads(self.request('GET','/api/events',headers=auth)[2])['events'][0]['reviewed'])

    def test_ingest_rejects_unknown_origins_private_data_and_oversized_payload(self):
        self.assertEqual(self.ingest(**{'Origin':'https://attacker.invalid'})[0],403)
        self.assertEqual(self.ingest(**{'X-Charisma-Site-Key':'wrong-key'})[0],403)
        self.assertEqual(self.ingest({**EVENT,'message':'private'})[0],400)
        self.assertEqual(self.ingest({**EVENT,'file':'a'*5000})[0],400)
        self.assertEqual(self.ingest(**{'Content-Type':'text/plain'})[0],400)

    def test_static_routes_headers_and_preflight(self):
        for path in ['/','/dashboard.js','/dashboard.css','/monitor.js']:
            code,headers,body=self.request('GET',path)
            self.assertEqual(code,200); self.assertGreater(len(body),100)
            self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
            self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET','/../../etc/passwd')[0],404)
        self.assertEqual(self.request('OPTIONS','/ingest',headers={'Origin':ORIGIN})[0],200)
        self.assertEqual(self.request('OPTIONS','/ingest',headers={'Origin':'https://elsewhere.example'})[0],403)


if __name__ == '__main__': unittest.main()
