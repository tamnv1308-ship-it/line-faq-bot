import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import mac_worker as w
from mwg_submit_capture import CreateCapture, parse_created_rows, merge_results, CREATE_URL


def item(source='3945'):
    return dict(source=source,destination='447',product='0131491005415',quantity=1)


def remote(source=3945,co='3945CO123',error='',**extra):
    return dict(FROMSTOREID=source,TOSTOREID=447,PRODUCTID='0131491005415',QUANTITY=1,
                STORECHANGEORDERID=co,ISERROR=bool(error),ERRORNOTE=error,**extra)


class SubmitCaptureTests(unittest.TestCase):
    def run_process(self,late,finish_at=0):
        page=MagicMock();page.url=w.URL;clock=[0.0];callbacks={}
        page.on.side_effect=lambda event,fn:callbacks.setdefault(event,fn)
        page.get_by_role.return_value.input_value.return_value='1 - Mới'
        page.locator.return_value.get_attribute.return_value='brands'
        page.locator.return_value.all_text_contents.return_value=['1 - thegioididong','2 - dienmayxanh','16 - TopZone']
        request=MagicMock(method='POST',url=CREATE_URL)
        request.response.return_value.status=200
        request.response.return_value.json.return_value={'Data':[remote()]}
        def click():
            if late=='request':return
            callbacks['request'](request)
            if not late and not finish_at:callbacks['requestfinished'](request)
        page.get_by_role.return_value.click.side_effect=click
        finished=[False]
        def wait(ms):
            clock[0]=round(clock[0]+ms/1000,6)
            if finish_at and clock[0]>=finish_at and not finished[0]:
                callbacks['requestfinished'](request);finished[0]=True
        page.wait_for_timeout.side_effect=wait
        def report(job,state,*args,**kwargs):
            # A response can arrive while the timeout report itself is being delivered.
            if state=='unknown' and late!='request':callbacks['requestfinished'](request)
        row=['1','3945 - Xuất','447 - Nhận','0131491005415','iPhone','1','','','','','']
        job=dict(id='test',mode='create',lease='lease',payload=dict(item(),status='Mới',product_name='iPhone'))
        guard=MagicMock();guard.late_submissions=[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(w,'ROOT',Path(tmp)),\
             patch.object(w,'wait_matched_rows',return_value=[row]),patch.object(w,'data_rows',return_value=[]),\
             patch.object(w,'progress'),patch.object(w,'capture_failure'),\
             patch.object(w.time,'monotonic',side_effect=lambda:clock[0]),patch.object(w,'report',side_effect=report) as send:
            w.process(page,job,'test',guard)
            if late:
                self.assertGreaterEqual(clock[0],30)
                self.assertLess(clock[0],30.31)
                self.assertEqual(send.call_args.args[1],'unknown')
                self.assertIn('sau 30 giây',send.call_args.args[2])
                self.assertEqual(len(guard.late_submissions),1)
                if late=='request':
                    callbacks['request'](request)
                    callbacks['requestfinished'](request)
                w.reconcile_late_submissions(guard)
            else:
                self.assertEqual([call.args[1] for call in send.call_args_list],['submitting','succeeded'])
                self.assertAlmostEqual(clock[0],finish_at)
            self.assertEqual(send.call_args.args[1],'succeeded')
            self.assertEqual(json.loads(send.call_args.args[2])[0]['co'],'3945CO123')
        page.get_by_role.return_value.click.assert_called_once();page.reload.assert_not_called()
        page.goto.assert_not_called();page.close.assert_not_called()

    def test_process_uses_response_when_dom_has_no_rows(self):self.run_process(False)

    def test_result_at_twenty_seconds_succeeds_without_timeout_or_reload(self):self.run_process(False,20.1)

    def test_result_just_before_thirty_seconds_succeeds_without_timeout_or_reload(self):self.run_process(False,29.7)

    def test_process_retains_result_arriving_during_timeout_reporting(self):self.run_process(True)

    def test_delayed_post_is_still_observed_without_second_click(self):self.run_process('request')

    def test_mixed_results_reordered_and_missing_rows(self):
        rows=parse_created_rows({'Data':[remote(2,co='',error='Không đủ tồn'),remote()]},[item(),item('2'),item('3')])
        self.assertEqual([r['state'] for r in rows],['succeeded','failed','unknown'])
        self.assertEqual(rows[0]['co'],'3945CO123')
        self.assertIn('Không đủ tồn',rows[1]['error'])

    def test_http_success_does_not_prove_creation(self):
        for row in (remote(co=''),remote(co='not-a-co'),remote(error='Lỗi với mã CO')):
            self.assertEqual(parse_created_rows({'Success':True,'Data':[row]},[item()])[0]['state'],'unknown')
        for body in ({'Success':True},{'Data':[remote(),remote()]},{'Data':[remote(99)]},
                     {'Data':[dict(remote(),QUANTITY=1.5)]},{'Data':[dict(remote(),PRODUCTID='131491005415')]}):
            with self.assertRaises(ValueError):parse_created_rows(body,[item()])

    def test_only_matching_finished_post_is_read_and_duplicate_is_ambiguous(self):
        page=MagicMock();capture=CreateCapture(page,[item()])
        unrelated=MagicMock(method='GET',url=CREATE_URL)
        capture.request(unrelated);capture.finished(unrelated)
        unrelated.response.assert_not_called()
        request=MagicMock(method='POST',url=CREATE_URL)
        request.response.return_value.status=200
        request.response.return_value.json.return_value={'Data':[remote()]}
        capture.request(request)
        self.assertIsNone(capture.rows)
        capture.finished(request)
        self.assertEqual(capture.rows[0]['co'],'3945CO123')
        capture.request(MagicMock(method='POST',url=CREATE_URL))
        self.assertIsNone(capture.rows)
        self.assertIn('nhiều lượt',capture.problem)
        capture.close();self.assertEqual(page.remove_listener.call_count,3)

    def test_conflicts_stay_unknown_and_keep_the_first_co(self):
        old=[dict(co='3945CO1',error='',state='succeeded')]
        conflict=merge_results(old,[dict(co='3945CO2',error='',state='succeeded')])
        self.assertEqual(conflict[0]['state'],'unknown')
        self.assertEqual(merge_results(conflict,old),conflict)
        self.assertEqual(merge_results(old,[dict(co='',error='Waiting',state='unknown')]),old)

    def test_late_result_reports_without_click_or_reload(self):
        page=MagicMock();capture=CreateCapture(page,[item()])
        request=MagicMock(method='POST',url=CREATE_URL)
        request.response.return_value.status=200
        request.response.return_value.json.return_value={'Data':[remote()]}
        capture.request(request)
        job=dict(id='late',lease='lease')
        guard=MagicMock(uncertain_job='late')
        guard.late_submissions=[(job,capture,[dict(co='',error='Waiting',state='unknown')])]
        with patch.object(w,'report') as report,patch.object(w,'progress'):
            page.is_closed.return_value=False
            w.reconcile_late_submissions(guard);report.assert_not_called()
            capture.finished(request)
            w.reconcile_late_submissions(guard)
            report.assert_called_once()
            self.assertEqual(report.call_args.args[1],'succeeded')
            self.assertEqual(json.loads(report.call_args.args[2])[0]['co'],'3945CO123')
            self.assertIsNone(guard.uncertain_job)
            w.reconcile_late_submissions(guard);report.assert_called_once()
        page.get_by_role.assert_not_called();page.reload.assert_not_called()


if __name__=='__main__':unittest.main()
