"""Auditing must reject changed evidence and fake green receipts without game work."""
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

from tools import card_batch as b
from tools.card_worker_audit import archive_files, baseline_python, source_records


class WorkerAuditTests(unittest.TestCase):
    def test_exclusive_archive_preserves_original_bytes_and_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); worker=root/'worker'; worker.mkdir()
            source=worker/'outputs/body.json'; source.parent.mkdir(); source.write_bytes(b'{"actual":"raw bytes"}\r\n')
            pins={'outputs/body.json':b.sha(source)}
            result=archive_files(worker,root/'archive',pins)
            self.assertEqual((root/'archive/outputs/body.json').read_bytes(),source.read_bytes())
            self.assertEqual(result['file_count'],1)
            with self.assertRaisesRegex(ValueError,'fresh'):archive_files(worker,root/'archive',pins)
            source.write_text('changed',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'changed'):archive_files(worker,root/'other',pins)
            self.assertFalse((root/'other').exists())

    def test_archive_rejects_parent_escape_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);worker=root/'worker';worker.mkdir();source=root/'outside';source.write_text('outside')
            with self.assertRaises(ValueError):archive_files(worker,root/'archive',{'../outside':b.sha(source)})
            self.assertFalse((root/'archive').exists())

    def test_actual_git_baseline_accepts_only_line_ending_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for directory in ('hs_sim','tests','tools'):
                (root/directory).mkdir();(root/directory/'base.py').write_bytes(b'VALUE = 1\n')
            for args in (['init','--quiet'],['add','.'],['-c','user.name=Audit Fixture','-c','user.email=audit@example.invalid','commit','--quiet','-m','fixture']):
                subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True)
            baseline=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            (root/'hs_sim/base.py').write_bytes(b'VALUE = 1\r\n');(root/'tests/added.py').write_bytes(b'VALUE = 2\n')
            guard=b.source_guard(root)
            report=baseline_python(root,baseline,guard,{'tests/added.py'})
            self.assertEqual(report['old_protected_python'],3)
            (root/'hs_sim/base.py').write_bytes(b'VALUE = 2\r\n')
            with self.assertRaisesRegex(ValueError,'changed baseline'):baseline_python(root,baseline,b.source_guard(root),{'tests/added.py'})

    def test_rehashed_source_subset_cannot_replace_complete_original_record(self):
        raw=dict(id='card',text='whole rule',tags={'FULL':1});changed=dict(raw,text='partial rule')
        data=dict(cards=[dict(record=changed,record_sha256=b.canonical(changed))])
        with self.assertRaisesRegex(ValueError,'Incomplete'):source_records(data,[raw])
        data['cards'][0]=dict(record=raw,record_sha256=b.canonical(raw))
        self.assertEqual(source_records(data,[raw])[1],1)

    def test_success_flags_without_matching_actual_method_timings_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run=root/'run';group=run/'groups/g';group.mkdir(parents=True)
            guard={'tests/example.py':'a'*64};method='example.Tests.test_expected'
            inputs=dict(full_discovery=False,source_sha256=guard,selected=[method])
            result=dict(success=True,source_guard=True,exactly_once_coverage=True,selected=1,executed=1,
                        failures=[],errors=[],skipped=[],seconds=1.0)
            for path in (run,group):
                b.save_new(path/'inputs.json',inputs);b.save_new(path/'result.json',result)
            b.save_new(run/'groups.json',[dict(module='example',passed=True,exit_code=0,output=str(group))])
            (group/'test-times.jsonl').write_text('{"test":"example.Tests.test_wrong","status":"passed","seconds":1}\n')
            with self.assertRaises(ValueError):b.verify_run(root,run,['example'],guard,[method])


if __name__ == '__main__':unittest.main()
