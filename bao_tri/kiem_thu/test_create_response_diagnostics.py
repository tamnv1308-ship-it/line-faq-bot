import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mac_worker as w
from mwg_result_contract import parse_created_rows, ResultContractError
from mwg_submit_capture import CreateCapture, CREATE_URL


ITEM=dict(source='1',destination='2',product='0131491005415',quantity=1)
ROW=dict(FROMSTOREID=1,TOSTOREID=2,PRODUCTID='0131491005415',QUANTITY=1,
         STORECHANGEORDERID='001CO123',ISERROR=False,ERRORNOTE='')


class CreateResponseDiagnosticsTests(unittest.TestCase):
    def capture(self,body,status=200,sink=None):
        page=MagicMock();capture=CreateCapture(page,[ITEM],on_diagnostic=sink)
        request=MagicMock(method='POST',url=CREATE_URL)
        request.response.return_value.status=status
        request.response.return_value.json.return_value=body
        capture.request(request);capture.finished(request)
        page.get_by_role.assert_not_called();page.reload.assert_not_called();page.close.assert_not_called()
        return capture

    def test_null_is_explicit_and_never_assumed_failed_or_succeeded(self):
        for success in (True,False):
            capture=self.capture({'Success':success,'Data':None,'Message':'private detail'})
            self.assertTrue(capture.done);self.assertIsNone(capture.rows)
            self.assertIn('Data=null',capture.problem)
            self.assertEqual(capture.diagnostic['code'],'data_null')
            self.assertEqual(capture.diagnostic['data_type'],'null')
            self.assertEqual(capture.diagnostic['success'],success)
            self.assertNotIn('private detail',json.dumps(capture.diagnostic))

    def test_missing_wrong_type_and_bad_row_have_distinct_fixed_reasons(self):
        cases=[([], 'body_type'),({},'data_missing'),({'Data':{}},'data_type'),
               ({'Data':[{}]},'identity_missing'),({'Data':[dict(ROW,PRODUCTID=131491005415)]},'product_type'),
               ({'Data':[dict(ROW,FROMSTOREID=99)]},'row_mismatch')]
        for body,code in cases:
            with self.subTest(code=code):
                capture=self.capture(body)
                self.assertEqual(capture.diagnostic['code'],code)
                self.assertIsNone(capture.rows)
                with self.assertRaises(ResultContractError):parse_created_rows(body,[ITEM])

    def test_valid_result_survives_diagnostic_disk_error(self):
        sink=MagicMock(side_effect=OSError('disk full'))
        capture=self.capture({'Success':True,'Data':[ROW]},sink=sink)
        self.assertEqual(capture.rows[0]['co'],'001CO123')
        self.assertEqual(capture.rows[0]['state'],'succeeded')
        sink.assert_called_once()

    def test_diagnostics_never_copy_body_rows_notes_messages_or_secrets(self):
        secret='DO_NOT_LOG_THIS'
        capture=self.capture({'Success':True,'Data':[dict(ROW,NOTE=secret)],
                              'Message':secret,'token':secret,'cookie':secret})
        text=json.dumps(capture.diagnostic)
        self.assertNotIn(secret,text);self.assertNotIn(ROW['PRODUCTID'],text)
        self.assertNotIn(ROW['STORECHANGEORDERID'],text)
        self.assertEqual(capture.diagnostic['row_count'],1)

    def test_invalid_json_and_http_error_are_not_contract_failures(self):
        page=MagicMock();capture=CreateCapture(page,[ITEM])
        request=MagicMock(method='POST',url=CREATE_URL)
        request.response.return_value.status=200
        request.response.return_value.json.side_effect=ValueError('secret raw HTML')
        capture.request(request);capture.finished(request)
        self.assertEqual(capture.diagnostic['code'],'invalid_json')
        self.assertNotIn('secret',capture.problem)
        capture=self.capture(None,status=503)
        self.assertEqual(capture.diagnostic['code'],'http_error')
        self.assertEqual(capture.diagnostic['http_status'],503)

    def test_saving_diagnostic_is_private_and_does_not_mutate_jobs(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(w,'ROOT',Path(tmp)),patch.object(w,'api') as api:
            capture=self.capture({'Success':True,'Data':None},
                sink=lambda d:w.save_create_diagnostic({'id':'test'},d))
            p=Path(tmp)/'diagnostics/test-create-response.json'
            self.assertEqual(json.loads(p.read_text())['code'],'data_null')
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            api.assert_not_called()

    def test_post_clock_is_fallback_when_click_clock_cannot_be_read(self):
        button=MagicMock();button.evaluate.side_effect=RuntimeError('DOM unavailable')
        capture=CreateCapture(MagicMock(),[ITEM]);capture.arm_click(button)
        request=MagicMock(method='POST',url=CREATE_URL)
        with patch('mwg_submit_capture.time.monotonic',return_value=100):capture.request(request)
        with patch('mwg_submit_capture.time.monotonic',return_value=107):
            self.assertEqual(capture.result_deadline(30),130)
        self.assertEqual(capture.diagnostic['timer_basis'],'observed_post')


if __name__=='__main__':unittest.main()
