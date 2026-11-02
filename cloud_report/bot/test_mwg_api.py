import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import mwg_api as api


class ApiExportTests(unittest.TestCase):
    def test_exact_filters_and_deduplicated_authorized_stores(self):
        body = api.export_body(date(2026, 10, 15), [{'id': 7}, {'id': 8}, {'id': 7}],
                               [{'id': 233, 'name': 'BI MỖI NGÀY', 'mode': 'flat'}])
        self.assertEqual(body['STOREIDS'], '7,8')
        self.assertEqual(body['FROMDATE'], 20261015)
        self.assertEqual(body['TODATE'], 20261015)
        self.assertEqual(body['MAINGROUPIDS'], '13,16,22,23,244,364')
        self.assertEqual((body['BRANDIDS'], body['INVENTORYSTATUSIDS']), ('136', '1'))
        self.assertEqual(body['TEMPLATE_ID'], 233)

    def test_no_stores_or_ambiguous_template_does_not_export(self):
        template = {'id': 233, 'name': 'BI MỖI NGÀY', 'mode': 'flat'}
        for stores, templates in [([], [template]), ([{'id': 1}], []),
                                  ([{'id': 1}], [template, template])]:
            with self.assertRaises(RuntimeError):
                api.export_body(date(2026, 10, 15), stores, templates)

    def test_wrong_job_never_downloads_an_older_file(self):
        results = [
            {'templates': [{'id': 233, 'name': 'BI MỖI NGÀY', 'mode': 'flat'}]},
            {'success': True, 'data': [{'id': 1}]}, {'job_id': 'newjob'},
            {'job_id': 'oldjob', 'state': 'done'},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(api, 'api', side_effect=results) as call:
            output = Path(directory) / 'source.xlsx'
            with self.assertRaises(RuntimeError):
                api.export_file(date(2026, 10, 15), output)
            self.assertFalse(output.exists())
            self.assertEqual(call.call_count, 4)

class HistoricalFilterTests(unittest.TestCase):
    def test_history_requests_only_missing_group_and_locally_filters_statuses(self):
        results=[{'templates':[{'id':233,'name':'BI MỖI NGÀY','mode':'flat'}]},
                 {'success':True,'data':[{'id':1}]},{'job_id':'newjob'},
                 {'job_id':'wrongjob','state':'done'}]
        with tempfile.TemporaryDirectory() as directory,patch.object(api,'api',side_effect=results) as call:
            with self.assertRaises(RuntimeError):
                api.export_file(date(2026,10,15),Path(directory)/'source.xlsx',inventory_status_ids=None,main_group_ids='16')
        body=call.call_args_list[2].args[1]
        self.assertIsNone(body['INVENTORYSTATUSIDS']);self.assertEqual(body['MAINGROUPIDS'],'16');self.assertEqual(body['BRANDIDS'],'136')


if __name__ == '__main__':
    unittest.main()
