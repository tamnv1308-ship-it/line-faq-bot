"""Offline regression checks: all HTTP/browser objects are mocks."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mwg_api_worker as api
import mwg_import_api as importer
import co_results
from mwg_result_contract import row_identity, expected_identities, parse_created_rows
from mwg_submit_capture import CreateCapture, parse_created_rows as browser_parse


def item(source='100', **overrides):
    return dict(source=source, destination='200', product='000001', quantity=1,
                note='Mọi thắc mắc liên hệ Người thử', product_name='Sản phẩm thử',
                **overrides)


def remote(source=100, **overrides):
    row=dict(FROMSTOREID=source, TOSTOREID=200, PRODUCTID='000001', QUANTITY=1,
             INVENTORYSTATUSID=1, STORECHANGEORDERTYPEID=0, ISURGENT=0,
             CONTENT='', NOTE='Mọi thắc mắc liên hệ Người thử',
             PRODUCTNAME='Sản phẩm thử', FROMSTORENAME='Kho thử A', TOSTORENAME='Kho thử B',
             STORECHANGEORDERID='100CO1', ISERROR=False, ERRORNOTE='')
    row.update(overrides)
    return row


class ContractTests(unittest.TestCase):
    def test_result_wire_format_is_accepted_by_existing_queue_consumer(self):
        records=[item(),item('101')]
        state,rows=api.outcomes({'Data':[remote()]},records)
        decoded=co_results.decode_results({'items':records},json.dumps(rows))
        self.assertEqual(decoded,rows)
        self.assertEqual(state,'unknown')

    def test_failed_rows_release_only_their_own_protection(self):
        records=[item(),item('101'),item('102')]
        state,rows=api.outcomes({'Data':[remote(),remote(101,STORECHANGEORDERID='',
                                      ISERROR=True,ERRORNOTE='Lỗi thử')]},records)
        job=dict(state=state,payload=json.dumps({'items':records}),result=json.dumps(rows))
        self.assertEqual([r['source'] for r in co_results.protected_items(job)],['100','102'])
        self.assertEqual([r['source'] for r in co_results.protected_items(job,stock_only=True)],['102'])

    def test_line_result_keeps_partial_counts_and_unknown_notice(self):
        records=[item(),item('101'),item('102')]
        state,rows=api.outcomes({'Data':[remote(),remote(101,STORECHANGEORDERID='',
                                      ISERROR=True,ERRORNOTE='Lỗi thử')]},records)
        message=co_results.result_text(dict(id='offline',state=state,
            payload=json.dumps({'items':records}),result=json.dumps(rows)))
        self.assertIn('1/3 có mã CO',message)
        self.assertIn('Lỗi thử',message)
        self.assertIn('Có dòng chưa rõ kết quả',message)

    def test_import_api_and_browser_share_identity_and_parser(self):
        self.assertIs(api.identity, row_identity)
        self.assertIs(api.parse_created_rows, browser_parse)

    def test_product_padding_is_ignored_but_leading_zeroes_preserved(self):
        result=api.outcomes({'Data':[remote(PRODUCTID='000001    ')]}, [item()])
        self.assertEqual(result[0], 'succeeded')
        self.assertEqual(row_identity(item())[2], '000001')
        for product in ('1', 1, None, True):
            with self.subTest(product=product), self.assertRaises(ValueError):
                api.outcomes({'Data':[remote(PRODUCTID=product)]}, [item()])

    def test_co_format_matches_existing_browser_and_queue_contract(self):
        state,rows=api.outcomes({'Data':[remote(STORECHANGEORDERID='A100CO12')]}, [item()])
        self.assertEqual(state, 'succeeded')
        self.assertEqual(rows, browser_parse({'Data':[remote(STORECHANGEORDERID='A100CO12')]}, [item()]))

    def test_fractional_or_nonfinite_quantities_never_match_by_truncation(self):
        for quantity in (1.5, '1.5', 'NaN', 'Infinity', 0, -1, True, None):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                api.outcomes({'Data':[remote(QUANTITY=quantity)]}, [item()])

    def test_integral_decimal_identity_is_supported_without_losing_zeroes(self):
        state,_=api.outcomes({'Data':[remote(FROMSTOREID='100.0', QUANTITY='1.00')]}, [item()])
        self.assertEqual(state, 'succeeded')

    def test_duplicate_expected_rows_are_ambiguous(self):
        with self.assertRaises(ValueError):
            api.outcomes({'Data':[remote()]}, [item(), item()])

    def test_duplicate_or_unrelated_result_rows_are_ambiguous(self):
        for rows in ([remote(),remote()], [remote(999)]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                api.outcomes({'Data':rows}, [item()])

    def test_missing_rows_preserve_known_success_and_remain_unknown(self):
        state,rows=api.outcomes({'Success':True,'Data':[remote()]}, [item(),item('101')])
        self.assertEqual(state, 'unknown')
        self.assertEqual([r['state'] for r in rows], ['succeeded','unknown'])
        self.assertEqual(rows[0]['co'], '100CO1')

    def test_partial_batch_keeps_each_rows_explicit_outcome(self):
        body={'Data':[remote(101,STORECHANGEORDERID='',ISERROR=True,ERRORNOTE='Lỗi thử'),remote()]}
        state,rows=api.outcomes(body, [item(),item('101')])
        # Preserve queue protocol: resolved batch with any CO is succeeded,
        # while UI/stock protection must read the per-row states.
        self.assertEqual(state, 'succeeded')
        self.assertEqual([r['state'] for r in rows], ['succeeded','failed'])

    def test_success_flag_without_row_evidence_is_not_success(self):
        for body in ({'Success':True}, {'Data':'[]'}, None):
            with self.subTest(body=body), self.assertRaises(ValueError):
                api.outcomes(body,[item()])
        for row in (remote(STORECHANGEORDERID=''),remote(STORECHANGEORDERID='bad'),
                    remote(ISERROR=True,ERRORNOTE='Lỗi thử'),remote(ISERROR='false')):
            self.assertEqual(api.outcomes({'Success':True,'Data':[row]},[item()])[0],'unknown')

    def test_empty_expected_batch_is_rejected(self):
        with self.assertRaises(ValueError):api.outcomes({'Data':[]},[])

    def test_invalid_row_shapes_fail_closed(self):
        for row in (None, [], {}, {'FROMSTOREID':100}):
            with self.subTest(row=row),self.assertRaises(ValueError):
                api.outcomes({'Data':[row]},[item()])

    def test_import_supports_padding_and_preserves_order(self):
        rows=[remote(101,PRODUCTID='000001   '),remote()]
        body={'Success':True,'Data':{'Data':json.dumps(rows)}}
        matched=importer.validate_import(body,[item(),item('101')])
        self.assertEqual([r['FROMSTOREID'] for r in matched],[100,101])

    def test_invalid_input_is_rejected_before_import_request(self):
        request=MagicMock()
        for records in ([], [item(),item()], [dict(item(),quantity=1.5)]):
            with self.subTest(records=len(records)),self.assertRaises(ValueError):
                importer.probe_import(request,'test-only-token','/unused.xlsx',records)
        request.post.assert_not_called()

    def test_import_post_explicitly_disables_retries_and_redirects(self):
        request=MagicMock()
        request.post.return_value.status=200
        request.post.return_value.json.return_value={'Success':True,'Data':{'Data':[remote()]}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mock.xlsx';path.write_bytes(b'fake file; no HTTP')
            importer.probe_import(request,'test-only-token',path,[item()])
        request.post.assert_called_once()
        self.assertEqual(request.post.call_args.kwargs['max_retries'],0)
        self.assertEqual(request.post.call_args.kwargs['max_redirects'],0)

    def test_capture_observes_one_request_without_sending(self):
        page=MagicMock();capture=CreateCapture(page,[item()])
        request=MagicMock(method='POST',url=api.CREATE_URL)
        request.response.return_value.status=200
        request.response.return_value.json.return_value={'Data':[remote(PRODUCTID='000001   ')]}
        capture.request(request);capture.finished(request)
        self.assertEqual(capture.rows[0]['state'],'succeeded')
        capture.request(MagicMock(method='POST',url=api.CREATE_URL))
        self.assertIsNone(capture.rows)
        page.get_by_role.assert_not_called()
        page.context.request.post.assert_not_called()
        capture.close()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.page=MagicMock()
        self.worker=SimpleNamespace(
            ROOT=Path(self.tmp.name),URL='https://example.invalid',TEMPLATE=Path('/unused.xlsx'),
            items=lambda data:data.get('items') or [data],
            normalize_status=lambda label:'Mới' if label in ('Mới','1 - Mới') else label,
            progress=MagicMock(),report=MagicMock(),fill_template=MagicMock(),
            prepare_import_controls=MagicMock())
        self.job=dict(id='offline',mode='create',payload=dict(item(),status='Mới'))
        self.service=api.ApiWorker()
        self.service.prepared=('offline',api.fingerprint([item()],'Mới'),[remote()],
                               'test-only-token',self.page)

    def process(self):
        return self.service.process(self.page,self.job,'offline',self.worker)

    def test_confirmed_create_uses_prepared_data_without_second_import_or_navigation(self):
        with patch.object(api,'create',return_value={'Data':[remote()]}) as send,\
             patch.object(api,'probe_import') as upload:
            self.process()
        send.assert_called_once();upload.assert_not_called()
        self.page.goto.assert_not_called();self.page.reload.assert_not_called()
        self.assertEqual([c.args[1] for c in self.worker.report.call_args_list],['submitting','succeeded'])
        self.assertIsNone(self.service.prepared)

    def test_timeout_after_checkpoint_is_unknown_and_cannot_replay(self):
        with patch.object(api,'create',side_effect=TimeoutError('fake secret never log')) as send:
            self.process()
            first_result=self.worker.report.call_args.args
            self.process()
        send.assert_called_once()
        self.assertEqual(first_result[1],'unknown')
        self.assertEqual(json.loads(first_result[2])[0]['state'],'unknown')
        self.assertNotIn('fake secret',first_result[2])

    def test_checkpoint_failure_prevents_create(self):
        def report(job,state,*args,**kwargs):
            if state=='submitting':raise RuntimeError('Mock database failure')
        self.worker.report.side_effect=report
        with patch.object(api,'create') as send:self.process()
        send.assert_not_called()

    def test_changed_confirmation_snapshot_blocks_create(self):
        self.job['payload']['note']='Nội dung đã đổi'
        with patch.object(api,'create') as send:self.process()
        send.assert_not_called()
        self.assertEqual(self.worker.report.call_args.args[1],'failed')

    def test_changed_product_name_blocks_create(self):
        self.job['payload']['product_name']='Tên khác'
        with patch.object(api,'create') as send:self.process()
        send.assert_not_called()

    def test_duplicate_input_never_navigates_or_imports(self):
        self.job.update(mode='preview',payload={'items':[item(),item()]})
        with patch.object(api,'probe_import') as upload:self.process()
        upload.assert_not_called();self.page.goto.assert_not_called()

    def test_create_request_still_sends_exactly_once_with_retries_disabled(self):
        request=MagicMock()
        request.post.return_value.status=200
        request.post.return_value.json.return_value={'Data':[remote()]}
        api.create(request,'test-only-token',[remote()])
        request.post.assert_called_once()
        kwargs=request.post.call_args.kwargs
        self.assertEqual(kwargs['max_retries'],0)
        self.assertEqual(kwargs['max_redirects'],0)
        data=json.loads(kwargs['data']['Json'])[0]
        self.assertEqual(data['PRODUCTID'],'000001')
        self.assertEqual(data['NOTE'],item()['note'])


if __name__=='__main__':
    unittest.main()
