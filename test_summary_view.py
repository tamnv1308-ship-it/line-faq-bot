import unittest,json,tempfile
from pathlib import Path
from datetime import datetime
from PIL import Image
from co_summary import TZ,period,render
from co_summary_view import details
class DashboardTests(unittest.TestCase):
 def job(self,co='12CO1',state='succeeded',qty=1,owner='u',hour=10):
  p=dict(source='1',destination='2',product='001',product_name='Sản phẩm thử',quantity=qty,requester_name='Tên thử')
  return dict(id=owner,owner=owner,payload=json.dumps(p),created=datetime(2026,10,2,hour,tzinfo=TZ).timestamp(),state=state,result=co)
 def test_distinct_codes_and_quantities(self):
  data=details([self.job(qty=1),self.job(qty=2),self.job(qty=1)],{},TZ)
  self.assertEqual(data['ranked']['source'],[('1',1,3)])
  self.assertEqual(sum(data['hours']),1)
 def test_unknown_failed_excluded_and_top_five(self):
  jobs=[self.job('12CO'+str(i),owner='u'+str(i)) for i in range(8)]
  jobs.extend([self.job('',state='unknown'),self.job('',state='failed')])
  data=details(jobs,{},TZ)
  self.assertEqual(len(data['ranked']['people']),5)
  self.assertEqual(sum(data['hours']),8)
 def test_empty_image_and_long_labels(self):
  with tempfile.TemporaryDirectory() as tmp:
   for jobs in ([],[self.job()]):
    name=render(jobs,{'1':{'name':'Tên rất dài '*50,'province':'Tỉnh thử','region':'Vùng thử'}},*period(),Path(tmp))
    with Image.open(Path(tmp)/name) as image:self.assertEqual(image.size,(2400,1800))
    self.assertLess((Path(tmp)/name).stat().st_size,10*1024*1024)
