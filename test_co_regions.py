import json
import unittest
from unittest.mock import patch
from co_regions import region_label
from co_flow import preview_text

class RegionTests(unittest.TestCase):
    def test_same_different_unknown_and_excluded(self):
        mapping={'1':{'region':'Vùng Hà Nội +'},'2':{'region':'Vùng Hà Nội +'},'3':{'region':'Vùng Hồ Chí Minh'},'4':{'region':'An Khang'},'5':{'region':'AvaWorld'}}
        with patch('co_regions.stores',return_value=mapping):
            self.assertEqual(region_label({'source':'01','destination':'2'})[0],'same')
            self.assertEqual(region_label({'source':'1','destination':'3'})[0],'different')
            for code in ('4','5','6'):
                state,label=region_label({'source':'1','destination':code})
                self.assertEqual(state,'unknown');self.assertIn('kho nhận',label)
    def test_batch_summary_and_commands_preserved(self):
        rows=[dict(source='1',destination=str(d),product='0131491005418',quantity=1,note='',status='Mới') for d in (2,3,4)]
        mapping={'1':{'region':'Vùng Hà Nội +'},'2':{'region':'Vùng Hà Nội +'},'3':{'region':'Vùng Hồ Chí Minh'}}
        with patch('co_regions.stores',return_value=mapping):
            text=preview_text({'id':'abc','payload':json.dumps({'items':rows})})
        for expected in ('1 cùng vùng','1 khác vùng','1 chưa rõ','XACNHAN abc','HUY abc','Hiệu lực: 1 phút'):
            self.assertIn(expected,text)
