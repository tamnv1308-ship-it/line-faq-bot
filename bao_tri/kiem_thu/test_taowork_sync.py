import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import taowork_sync as sync
class SyncTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'.automation').mkdir();self.line=self.root/'line';self.line.mkdir()
 def test_rejects_other_service_before_reading_or_sending(self):
  (self.line/'.env').write_text('CO_BOT_URL=https://other.example\nCO_WORKER_TOKEN='+'T'*40)
  with patch.object(sync,'collect') as collect,patch.object(sync,'build_opener') as opener:
   with self.assertRaises(ValueError):sync.sync(self.root,self.line)
  collect.assert_not_called();opener.assert_not_called()
 def test_receipt_hash_mismatch_never_marks_success(self):
  (self.line/'.env').write_text('CO_BOT_URL='+sync.SERVICE+'\nCO_WORKER_TOKEN='+'T'*40)
  response=Mock();response.__enter__=Mock(return_value=io.BytesIO(b'{"schema":1,"sha256":"wrong"}'));response.__exit__=Mock(return_value=False)
  opener=Mock();opener.open.return_value=response
  with patch.object(sync,'collect',return_value={'revenue':{'cutoff':'2026-11-01'}}),patch.object(sync,'build_opener',return_value=opener):
   with self.assertRaises(ValueError):sync.sync(self.root,self.line)
  self.assertFalse((self.root/'.automation/cloud-sync-status.json').exists())
 def test_redirects_are_not_followed_and_disabled_config_starts_nothing(self):
  self.assertIsNone(sync.NoRedirect().redirect_request(None,None,302,'m',{},'https://other.example'))
  with patch.object(sync.threading,'Thread') as thread:self.assertIsNone(sync.start(self.root));thread.assert_not_called()
