import base64
import json
import os
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from co_flow import preview_text,install
from co_regions import stores,region_label,cluster_label,clear_store_cache
from co_results import line_text_messages
from co_store_directory import validate,write,status,override_path
from import_store_directory import extract


def detail(code,name='Shop',region='Vùng Hà Nội +'):
    return [region,'Not imported',code,name,'TGD',None,None,'Phường mới','Tỉnh mới',None,'Huyện cũ','Tỉnh cũ']

def cluster(code,base,label,region='Vùng Hà Nội +'):
    return [None,region,code,'Shop '+str(code),label,base]

def directory():
    return dict(version=1,source='Sample.xlsx',source_sha256='a'*64,
                stores=extract([detail(1),detail(2),detail(3)],
                               [cluster(1,2,'Cụm 2'),cluster(2,2,'cụm 2'),cluster(3,3,'Cụm 3')]))


class StoreClusterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'co_store_directory.json'
        env=patch.dict(os.environ,{'CO_STORES_OVERRIDE_PATH':str(self.path),'CO_DB_PATH':str(Path(self.tmp.name)/'q.db')})
        env.start();self.addCleanup(env.stop);self.addCleanup(clear_store_cache)

    def test_import_fields_and_cluster_capitalization(self):
        rows=directory()['stores']
        self.assertEqual(rows['1']['province'],'Tỉnh mới')
        self.assertEqual(rows['1']['province_old'],'Tỉnh cũ')
        self.assertNotIn('RSM',rows['1'])
        self.assertEqual(rows['1']['clusters'],rows['2']['clusters'])
        self.assertEqual(rows['1']['clusters'][0]['name'],'Cụm 2')

    def test_warning_for_member_base_and_other_member(self):
        p=directory();p['stores']=extract([detail(n) for n in (1,2,3)],
                                      [cluster(1,2,'Cụm 2'),cluster(2,2,'Cụm 2'),cluster(3,2,'Cụm 2')])
        write(p)
        for source,destination in (('01','2'),('2','1'),('1','3')):
            self.assertEqual(cluster_label(dict(source=source,destination=destination)),'⚠️ CÙNG CỤM: Cụm 2')
        self.assertEqual(region_label(dict(source='1',destination='2'))[0],'same')

    def test_different_and_missing_clusters_have_no_extra_warning(self):
        write(directory())
        for destination in ('3','999'):
            self.assertEqual(cluster_label(dict(source='1',destination=destination)),'')

    def test_base_references_and_no_transitive_cluster_merge(self):
        rows=extract([detail(1),detail(2)], [cluster(1,2,'Cụm 2'),cluster(2,3,'Cụm 3')])
        self.assertEqual(rows['3']['record_type'],'base_reference')
        p=directory();p['stores']=rows;write(p)
        self.assertIn('Cụm 2',cluster_label(dict(source='1',destination='2')))
        self.assertIn('Cụm 3',cluster_label(dict(source='2',destination='3')))
        self.assertEqual(cluster_label(dict(source='1',destination='3')),'')

    def test_excluded_regions_and_ambiguous_bases(self):
        rows=extract([detail(1),detail(2,region='An Khang')],
                     [cluster(1,1,'Cụm 1'),cluster(2,2,'Cụm 2',region='An Khang')])
        self.assertEqual(set(rows),{'1'})
        with self.assertRaises(ValueError):
            extract([detail(1),detail(2)],[cluster(1,1,'Cụm A'),cluster(2,2,'Cụm A')])
        with self.assertRaises(ValueError):extract([detail(1),detail(1)],[])

    def test_private_update_overrides_stale_env_and_refreshes_cache(self):
        old={'1':dict(name='Old',region='Vùng Hồ Chí Minh',province='Old')}
        packed=base64.b64encode(zlib.compress(json.dumps(old).encode())).decode()
        with patch.dict(os.environ,{'CO_STORES_ZLIB':packed}):
            self.assertEqual(stores()['1']['name'],'Old')
            p=directory();write(p)
            self.assertEqual(stores()['1']['name'],'Shop')
            p['stores']['1']['name']='Updated';write(p)
            self.assertEqual(stores()['1']['name'],'Updated')
        self.assertTrue(self.path.with_suffix('.previous.json').exists())
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(status()['detail_stores'],3)

    def test_invalid_updates_leave_previous_data_intact(self):
        write(directory());before=self.path.read_bytes()
        for change in ('base','identifier','too_long','extra_field','conflict'):
            p=directory()
            if change=='base':p['stores']['1']['clusters'][0]['base']='999'
            elif change=='identifier':p['stores']['../x']=p['stores'].pop('1')
            elif change=='too_long':p['stores']['1']['name']='x'*601
            elif change=='extra_field':p['stores']['1']['secret']='Not permitted'
            else:p['stores']['2']['clusters'][0]['name']='Different cluster name'
            with self.subTest(change=change),self.assertRaises(ValueError):write(p)
            self.assertEqual(self.path.read_bytes(),before)

    def test_confirmation_batch_preserves_buttons_status_notes(self):
        write(directory())
        row=dict(source='1',destination='2',product='0131491005416',quantity=1,note='QL cho hàng',status='Đã sử dụng',product_name='iPhone')
        job=dict(id='0123456789',owner='user',payload=json.dumps(dict(items=[row,dict(row,destination='3')])))
        text=preview_text(job)
        self.assertEqual(text.count('⚠️ CÙNG CỤM:'),1)
        self.assertIn('Đã sử dụng',text);self.assertIn('QL cho hàng',text)
        self.assertEqual([x['action']['text'] for x in line_text_messages(text)[-1]['quickReply']['items']],
                         ['XACNHAN 0123456789','HUY 0123456789'])

    def test_authenticated_upload_and_metadata_never_return_private_directory(self):
        routes={}
        def route(path):
            def register(fn):routes[(fn.__name__,path)]=fn;return fn
            return register
        def abort(code):raise ValueError(code)
        request=types.SimpleNamespace(headers={'Authorization':'Bearer '+'x'*32},content_length=100,
                                      get_json=lambda **k:directory())
        flask=types.SimpleNamespace(request=request,jsonify=lambda **k:k,abort=abort)
        with patch.dict(os.environ,{'CO_ENABLED':'1','CO_WORKER_TOKEN':'x'*32,'CO_DATABASE_URL':''}),patch.dict('sys.modules',{'flask':flask}):
            install(types.SimpleNamespace(post=route,get=route),lambda *a:None,lambda *a:None)
            post=routes[('store_directory_update','/co/worker/store-directory')]
            get=routes[('store_directory_info','/co/worker/store-directory')]
            request.headers={}
            with self.assertRaisesRegex(ValueError,'401'):post()
            self.assertFalse(self.path.exists())
            request.headers={'Authorization':'Bearer '+'x'*32}
            info=post();self.assertTrue(info['ok']);self.assertEqual(info['stores'],3)
            self.assertEqual(get()['digest'],info['digest'])
            self.assertNotIn('Shop',json.dumps(get()))
            request.content_length=3000001
            with self.assertRaisesRegex(ValueError,'413'):post()

if __name__=='__main__':unittest.main()
