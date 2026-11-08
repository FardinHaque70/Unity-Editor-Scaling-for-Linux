"""Durable update recovery: no daily installation, network, or Editor needed."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unity_scale import updates


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='unity-update-recovery-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.store = SimpleNamespace(data_dir=self.base)
        self.target = self.base / 'application.AppImage'
        self.old = b'previous working image';self.new = b'signed candidate image'
        self.target.write_bytes(self.new)
        self.target.chmod(0o700)
        self.rollback = self.base / 'application.AppImage.rollback'
        self.rollback.write_bytes(self.old)
        self.rollback.chmod(0o700)
        self.stage = self.base / '.update-fixture';self.stage.mkdir(mode=0o700)
        self.token = 'a' * 64
        self.record = dict(schema=1, old_sha256=hashlib.sha256(self.old).hexdigest(),
                           new_sha256=hashlib.sha256(self.new).hexdigest(), version='0.5.0', token=self.token)
        (self.stage / 'transaction.json').write_text(json.dumps(self.record))
        self.manifest = dict(schema=1, version='0.5.0', channel='stable', architecture='x86_64',
                             filename=updates.FILENAME, size=len(self.new), sha256=self.record['new_sha256'])
        (self.stage / 'release.json').write_text(json.dumps(self.manifest))
        (self.stage / 'release.json.sig').write_bytes(b's' * 64)
        self.executions=[];self.preflights=[]

    def recover(self, **kwargs):
        return updates.recover_interrupted_update(store=self.store,
            execute=lambda *v:self.executions.append(v), verifier=lambda *v:None,
            preflight=lambda *v:self.preflights.append(v), **kwargs)

    def test_interrupted_after_swap_restores_and_reinstalls_old(self):
        self.assertEqual(self.recover()['state'], 'restored')
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertFalse(self.rollback.exists());self.assertFalse(self.stage.exists())
        self.assertEqual(len(self.preflights), 1)
        self.assertEqual(self.executions[0][1], [str(self.target), '--install-user', '--recover-update'])

    def test_acknowledged_candidate_finishes_cleanup_without_restart(self):
        (self.stage / 'healthy').write_text(self.token)
        self.assertEqual(self.recover()['state'], 'committed')
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.executions, []);self.assertEqual(self.preflights, [])
        self.assertFalse(self.stage.exists());self.assertFalse(self.rollback.exists())

    def test_prepared_or_linked_before_swap_cancels_cleanly(self):
        for rollback in (False, True):
            with self.subTest(rollback=rollback):
                self.target.write_bytes(self.old)
                if not rollback:self.rollback.unlink()
                self.assertEqual(self.recover()['state'], 'cancelled')
                self.assertEqual(self.target.read_bytes(), self.old)
                self.assertEqual(self.executions, [])
                if not rollback:
                    self.setUp()

    def test_unknown_or_changed_rollback_preserved(self):
        self.rollback.write_bytes(b'unrelated')
        with self.assertRaises(updates.UpdateError):self.recover()
        self.assertTrue(self.rollback.exists());self.assertTrue(self.stage.exists())
        self.assertEqual(self.target.read_bytes(), self.new)

    def test_signature_failure_never_restores(self):
        def reject(*_):raise updates.UpdateError('bad signature')
        with self.assertRaises(updates.UpdateError):
            updates.recover_interrupted_update(store=self.store, verifier=reject)
        self.assertEqual(self.target.read_bytes(), self.new)

    def test_running_editor_preflight_blocks_rollback(self):
        def blocked(*_):raise updates.UpdateError('Editor running')
        with self.assertRaises(updates.UpdateError):
            updates.recover_interrupted_update(store=self.store, verifier=lambda *_:None,preflight=blocked)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertTrue(self.rollback.exists());self.assertTrue(self.stage.exists())

    def test_live_helper_lock_defers_recovery(self):
        lock=os.open(self.base, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.recover()['state'], 'active')
            self.assertEqual(self.target.read_bytes(), self.new)
            self.assertTrue(self.stage.exists())
        finally:os.close(lock)

    def test_orphan_rollback_without_record_is_not_deleted(self):
        (self.stage / 'transaction.json').unlink()
        with self.assertRaises(updates.UpdateError):self.recover()
        self.assertTrue(self.rollback.exists())

    @unittest.skipUnless(shutil.which('cc') and shutil.which('openssl'), 'native verifier toolchain unavailable')
    def test_actual_helper_killed_after_atomic_swap_recovers(self):
        # Use only disposable signing material. The production key is unchanged.
        self.rollback.unlink();self.target.write_bytes(self.old)
        (self.stage / 'transaction.json').unlink()
        source=Path(__file__).resolve().parents[1] / 'packaging/update_helper.c'
        interrupted=self.base / 'interrupted-helper.c'
        interrupted.write_text(source.read_text().replace('syncdir(base);pid_t child=launch(target,ack,token);',
            'syncdir(base);kill(getpid(),SIGKILL);pid_t child=launch(target,ack,token);'))
        helper=self.base / 'helper'
        subprocess.run(['cc','-Wall','-Wextra','-Werror',str(interrupted),'-lcrypto','-o',str(helper)],check=True)
        key=self.base / 'private.pem';public=self.stage / 'public-key.pem'
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(public)],check=True,capture_output=True)
        manifest=self.stage / 'release.json';sig=self.stage / 'release.json.sig'
        subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(manifest),'-out',str(sig)],check=True,capture_output=True)
        staged=self.stage / 'new.AppImage';staged.write_bytes(self.new);staged.chmod(0o700)
        result=subprocess.run([str(helper),'apply','2147483647',str(self.target),str(staged),str(manifest),str(sig),
            str(public),str(self.stage / 'healthy'),self.token,'0.5.0'],timeout=5,check=False)
        self.assertEqual(result.returncode, -9)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.rollback.read_bytes(), self.old)
        record=json.loads((self.stage / 'transaction.json').read_text())
        self.assertEqual(record,self.record)
        def verify(data,signature):
            updates.verify_signature(data,signature,helper=helper,public_key=public)
        result=updates.recover_interrupted_update(store=self.store,verifier=verify,
            execute=lambda *v:self.executions.append(v),preflight=lambda *_:None)
        self.assertEqual(result['state'],'restored')
        self.assertEqual(self.target.read_bytes(),self.old)


class AbandonedDownloadTests(unittest.TestCase):
    def owner(self, directory, target, *, boot=None, pid=None, start=None):
        (directory / 'owner.json').write_text(json.dumps(dict(schema=1,
            pid=os.getpid() if pid is None else pid,
            boot_id=updates._boot_id() if boot is None else boot,
            start_time=updates._process_start(os.getpid()) if start is None else start,
            target=str(target))))
        (directory / 'new.AppImage').write_bytes(b'interrupted partial download')

    def test_active_owner_preserved_dead_or_reboot_reused_pid_cleaned(self):
        with tempfile.TemporaryDirectory(prefix='unity-download-owner-') as temporary:
            base=Path(temporary);target=base/'application.AppImage';target.write_bytes(b'working image')
            store=SimpleNamespace(data_dir=base)
            active=base/'.update-active';active.mkdir(mode=0o700);self.owner(active,target)
            dead=base/'.update-dead';dead.mkdir(mode=0o700);self.owner(dead,target,pid=2147483647,start='1')
            reboot=base/'.update-reboot';reboot.mkdir(mode=0o700)
            self.owner(reboot,target,boot='00000000-0000-0000-0000-000000000000')
            # Even the same numerical PID/start is stale across a different boot.
            result=updates.recover_interrupted_update(store=store)
            self.assertEqual(result,dict(state='none',abandoned_downloads_removed=2))
            self.assertTrue(active.exists());self.assertFalse(dead.exists());self.assertFalse(reboot.exists())
            self.assertEqual(target.read_bytes(),b'working image')

    def test_unknown_or_unowned_stage_is_never_removed(self):
        with tempfile.TemporaryDirectory(prefix='unity-download-unknown-') as temporary:
            base=Path(temporary);target=base/'application.AppImage';target.write_bytes(b'working image')
            stage=base/'.update-dead';stage.mkdir(mode=0o700)
            self.owner(stage,target,pid=2147483647,start='1')
            unknown=stage/'user-file';unknown.write_text('retain')
            with self.assertRaises(updates.UpdateError):
                updates.recover_interrupted_update(store=SimpleNamespace(data_dir=base))
            self.assertTrue(unknown.exists());self.assertTrue((stage/'new.AppImage').exists())
            self.assertEqual(target.read_bytes(),b'working image')


if __name__ == '__main__':unittest.main()
