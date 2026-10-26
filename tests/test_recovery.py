import sqlite3
import tempfile
from pathlib import Path
import unittest

from charisma.core import CharismaError
from charisma.recovery import backup_sqlite,restore_sqlite,checksum,register_static_release,activate_static_release

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_backup_restore_retains_pre_restore_database(self):
        db=self.root/'app.sqlite3'
        with sqlite3.connect(db) as c:c.execute('CREATE TABLE items(value TEXT)');c.execute("INSERT INTO items VALUES('original')")
        backup=self.root/'backup.sqlite3';backup_sqlite(db,backup)
        with sqlite3.connect(db) as c:c.execute("INSERT INTO items VALUES('newer')")
        before=checksum(db)
        with self.assertRaises(CharismaError):restore_sqlite(backup,db,before,False)
        with self.assertRaises(CharismaError):restore_sqlite(backup,db,'stale',True)
        result=restore_sqlite(backup,db,before,True)
        with sqlite3.connect(db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM items').fetchone()[0],1)
        with sqlite3.connect(result['previous_backup']) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM items').fetchone()[0],2)

    def test_modified_backup_and_wal_refuse_restore(self):
        db=self.root/'app.sqlite3'
        with sqlite3.connect(db) as c:c.execute('CREATE TABLE items(value TEXT)')
        backup=self.root/'backup.sqlite3';backup_sqlite(db,backup)
        wal=Path(str(db)+'-wal');wal.write_bytes(b'')
        with self.assertRaises(CharismaError):restore_sqlite(backup,db,checksum(db),True)
        wal.unlink();backup.write_bytes(b'changed')
        with self.assertRaises(CharismaError):restore_sqlite(backup,db,checksum(db),True)

    def test_static_release_atomic_switch_and_rollback(self):
        source=self.root/'built';source.mkdir();(source/'index.html').write_text('version one')
        releases=self.root/'deploy';register_static_release(source,releases,'v1')
        activate_static_release(releases,'v1','')
        (source/'index.html').write_text('version two');register_static_release(source,releases,'v2')
        activate_static_release(releases,'v2','v1')
        self.assertEqual((releases/'current/index.html').read_text(),'version two')
        activate_static_release(releases,'v1','v2')
        self.assertEqual((releases/'current/index.html').read_text(),'version one')
        with self.assertRaises(CharismaError):activate_static_release(releases,'v2','v2')
        (releases/'releases/v2/index.html').write_text('modified')
        with self.assertRaises(CharismaError):activate_static_release(releases,'v2','v1')
