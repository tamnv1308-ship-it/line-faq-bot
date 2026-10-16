import json
import time
import unittest
from unittest.mock import patch

import tao_compose as compose
import tao_portal as portal
import bao_tri.kiem_thu.test_tao_portal as fixtures
from co_results import items


def row(**changes):
    return dict(dict(source='3945',destination='447',product='0131491005415',quantity='1',status='Mới',note='QL cho hàng: Tư 24261'),**changes)


class EditableParsingTests(unittest.TestCase):
    def test_previous_customer_message_formats(self):
        # Regressions from actual pasted layouts; contact names/IMEI are anonymized.
        cases=[
            ('''Em chào Anh, nhờ anh tạo lệnh giúp em với ạ :&#x20;
Apple Studio Display Standard 27"Retina 5K/60Hz/600cd2/Thunderbolt 3/USB-C/ (MKOU3SA/A)bạc
MSP : 3641273000143
Imei : TESTSERIAL123
Trạng thái : đã sử dụng
Kho Xuất : 15078
Kho Nhận :  1537
Hình thức vận chuyển nội bộ
QLST đã liên hệ và đồng ý cho hàng nhờ anh tạo giúp ạ''',
             [('15078','1537','3641273000143','1','Đã sử dụng')]),
            ('''St trả cọc cho KH ạ&#x20;
Mã đơn trả cọc :
10336SO26090063520
Điện thoại iPhone 18 Pro Max 256GB Slive
0131491005413  &#x20;
Kho xuất : 114
Kho nhận : 10336

St trả cọc cho KH ạ&#x20;
Mã đơn trả cọc : YC xuất: 10336SO26090063420
Điện thoại iPhone 18 Pro Max 256GB Burgundy
0131491005411  &#x20;
Kho xuất : 2184
Kho nhận : 10336''',
             [('114','10336','0131491005413','1','Mới'),('2184','10336','0131491005411','1','Mới')]),
            ('''🛑 FORM mẫu XIN HÀNG :
Khác Tỉnh
- Mã kho xuất: 10323 - AAR_CTH_NKI - Số 08 Hoà Bình
- Mã kho nhận: 1759 ĐML Giồng Riềng
- MSP:0131491004725
- Tên sp: Điện thoại iPhone 17 Pro Max 256GB Silver
  (:)
- Trạng thái: mới
- Số Lượng:  1
- Lý do: KH mua mới
- QL xin hàng :
- Hình thức lấy hàng: NV lấy
Nhờ chị hỗ trợ tạo lệnh giúp em với ạ!''',
             [('10323','1759','0131491004725','1','Mới')]),
            ('''Nhờ anh/chị NH tạo lệnh giúp em
Điện thoại iPhone 18 Pro Max 256GB Black
KD bình thường 0131491005414  &#x20;
kho xuât : 1093
kho nhận : 7246
SL : 1
QL cho hàng: Người phụ trách
Nhờ @DM xác nhận giúp ST''',
             [('1093','7246','0131491005414','1','Mới')]),
            ('''Nhờ ngành hàng tạo lệnh điều chuyển iPhone 18 pro max 512GB Xanh .
1. MSP: 0131491005416
2. Tên SP: Điện thoại iPhone 18 Pro Max 512GB Xanh.
Kho xuất: 5108 Gia Trấn
Kho nhận: 1149- Nho Quan
Số lượng: 1
Trả đơn preoder:01149SO26090552643
QL cho hàng: @Người phụ trách
Em nhờ anh duyệt giúp em ạ.''',
             [('5108','1149','0131491005416','1','Mới')]),
            ('''Em Nhờ NH tạo lệnh xin hàng giúp ST ạ!
- 18prm 256gb : đen
- Kho chuyển:  8902
- Kho nhận: 12563
  Sp 1
- Msp: 0131491005414
Qlst cho hàng: Người phụ trách
Nhờ ac DM vùng hỗ trợ xác nhận giúp em ạ!''',
             [('8902','12563','0131491005414','1','Mới')]),
            ('- \ufeff\ufeffMã kho xuất: 9469\n\n- \ufeff\ufeffMã kho nhận: 7298\n\n- \ufeff\ufeffMSP: 0131491005416\n\n- \ufeff\ufeffTên sp: Điện thoại iPhone 18 Pro Max 512GB Glacier\n(Barcode: 195951411699)\n\n- Số Lượng : 1',
             [('9469','7298','0131491005416','1','Mới')]),
            ('''msp 0131491005418
Điện thoại iPhone 18 Pro Max 512GB Black
Kho xuất : 2869
Kho nhập : 10838
QL cho hàng : Người A
\\================
msp 0131491005418    &#x20;
Sl : 1&#x20;
Kho xuất : 377
Kho nhập : 3978
QL cho hàng : Người B
\\==============
Điện thoại iPhone 18 Pro Max 1TB Black
ma san pham 0131491005422
Kho xuất: 1814&#x20;
Kho nhận: 11494
Số lượng: 1
Ql cho hàng Người C

Điện thoại iPhone 18 Pro Max 1TB Black
msp 0131491005422
Kho xuất: 13910
Kho nhận: 11494
QL cho hàng Người D
Có khách mua ở siêu thị
\\==============
Kho chuyển : 308
Kho nhận : 4360
Số lượng : 1
&#x20;SP : 0131491005397
@Người phụ trách em ơi, tạo giúp a nha''',
             [('2869','10838','0131491005418','1','Mới'),('377','3978','0131491005418','1','Mới'),
              ('1814','11494','0131491005422','1','Mới'),('13910','11494','0131491005422','1','Mới'),
              ('308','4360','0131491005397','1','Mới')])]
        for text,expected in cases:
            with self.subTest(expected=expected):
                result=compose.parse_editable(text)
                actual=[tuple(row[key] for key in ('source','destination','product','quantity','status')) for row in result['rows']]
                self.assertEqual(actual,expected)
                self.assertTrue(result['valid'],result)

    def test_aliases_copy_markers_and_defaults(self):
        result=compose.parse_editable('- \ufeffMã kho chuyển: 3945 - Shop A\nKho nhập: 447-Shop B\nMã code: 0131491005415&#x20;\nQL cho hàng: Tư 24261')
        self.assertTrue(result['valid'],result)
        self.assertEqual(result['rows'],[row()])

    def test_numeric_product_does_not_take_imei_or_barcode(self):
        text='0131491005415\nImei: 1234567890123\n(Barcode: 195951411699)\nKho xuất: 3945\nKho nhận: 447'
        result=compose.parse_editable(text)
        self.assertEqual(result['rows'][0]['product'],'0131491005415')
        self.assertEqual(len(result['rows']),1);self.assertTrue(result['valid'])

    def test_incomplete_record_is_not_merged_into_next(self):
        result=compose.parse_editable('MSP: 0131491005415\nKho xuất: 3945\n===\nMSP: 0131491005416\nKho xuất: 789\nKho nhận: 2670')
        self.assertEqual(len(result['rows']),2);self.assertFalse(result['valid'])
        self.assertIn('destination',result['errors'][0]);self.assertEqual(result['errors'][1],{})

    def test_bad_product_rows_are_editable_not_discarded(self):
        result=compose.parse_editable('MSP: 131491005415\nKho xuất: 3945\nKho nhận: 447\n===\nMSP: 0131491005415\nKho xuất: 789\nKho nhận: 2670')
        self.assertEqual(len(result['rows']),2);self.assertEqual(result['rows'][0]['product'],'131491005415')
        self.assertIn('product',result['errors'][0])

    def test_quantity_alias_status_and_notes(self):
        result=compose.parse_editable('Kho chuyển: 3945\nNhập: 447\nSP 2\nMSP: 0131491005415\nNote: đã sử dụng\nDM xác nhận: Nam')
        record=result['rows'][0]
        self.assertEqual(record['quantity'],'2');self.assertEqual(record['status'],'Đã sử dụng')
        self.assertEqual(record['note'],'đã sử dụng\nDM xác nhận: Nam')

    def test_duplicate_retained_with_warning(self):
        result=compose.validate_rows([row(),row()])
        self.assertTrue(result['valid']);self.assertEqual(len(result['rows']),2)
        self.assertEqual(result['warnings'][0]['row'],1)

    def test_limits_mixed_status_and_unknown_status(self):
        self.assertFalse(compose.validate_rows([row()]*8)['valid'])
        self.assertFalse(compose.validate_rows([row(),row(status='Đã sử dụng')])['valid'])
        result=compose.validate_rows([row(status='Hàng đặc biệt')])
        self.assertIn('status',result['errors'][0])
        self.assertEqual(result['rows'][0]['status'],'Hàng đặc biệt')

    def test_no_silent_picking_of_multiple_codes(self):
        result=compose.parse_editable('Kho xuất: 3945 hoặc 789\nKho nhận: 447\nMSP: 0131491005415')
        self.assertEqual(result['rows'][0]['source'],'3945 hoặc 789')
        self.assertIn('source',result['errors'][0])

    def test_strict_fields_and_blocked_destination(self):
        for changes,key in [({'source':'1\nKho nhận: 5'},'source'),({'product':'０１３１４９１００５４１５'},'product'),
                            ({'quantity':'0'},'quantity'),({'quantity':'1.5'},'quantity'),({'note':'x'*501},'note'),
                            ({'destination':'03945'},'destination')]:
            self.assertIn(key,compose.validate_rows([row(**changes)])['errors'][0])
        with patch.dict(compose.BLOCKED,{'447':{'name':'Shop thử','group':'Shop mẹ'}}):
            self.assertIn('Shop mẹ',compose.validate_rows([row()])['errors'][0]['destination'])
        for bad in (None,[],[1],[row(product=131491005415)]):
            with self.assertRaises(ValueError):compose.validate_rows(bad)

    def test_payload_ignores_client_names_and_authority(self):
        review=compose.validate_rows([dict(row(),requester_name='Giả tên',owner=fixtures.OWNER,product_name='Giả sản phẩm')])
        payload=compose.queue_payload(review)
        self.assertEqual(set(payload),set(compose.FIELDS));self.assertEqual(payload['quantity'],1)


class ComposeFlowTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.PortalTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.q=self.fx.q;self.call=self.fx.call;self.login=self.fx.login;self.job=self.fx.job
        self.key='a'*32;self.login()

    def submit(self,rows=None,key=None,scope='group',**extra):
        return self.call('compose/submit','POST',dict(rows=rows or [row()],key=key or self.key,scope=scope,**extra))

    def count(self):
        with self.q.db() as db:return db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n']

    def ready(self):
        response=self.submit();self.assertEqual(response.status_code,200,response.json)
        job=self.q.claim(preview_protocol=True,batch_protocol=True)
        self.assertIsNotNone(job)
        self.assertTrue(self.q.update(job['id'],job['lease'],'preview_ready','Tên thật từ MWG'))
        return job,self.call('jobs/'+job['id']).json['job']

    def test_parse_and_validate_do_not_enqueue_even_offline(self):
        self.q.heartbeat(False)
        response=self.call('compose/parse','POST',{'text':'MSP: 131491005415\nKho xuất: 3945'})
        self.assertEqual(response.status_code,200);self.assertFalse(response.json['valid'])
        self.assertTrue(self.call('compose/validate','POST',{'rows':[row()]}).json['valid'])
        self.assertEqual(self.count(),0)

    def test_auth_csrf_origin_and_scope(self):
        for path in ('compose/parse','compose/validate','compose/submit'):
            self.assertEqual(self.call(path,'POST',{},headers={'Origin':'https://evil.example'}).status_code,403)
            self.assertEqual(self.call(path,'POST',{},headers={'X-Tao-CSRF':''}).status_code,403)
        self.assertEqual([s['value'] for s in self.call('compose').json['scopes']],['group'])
        self.assertEqual(self.submit(scope='private').status_code,403)
        self.assertEqual(self.submit(scope=fixtures.DISABLED_CO_GROUP).status_code,403)
        self.login(fixtures.ADMIN);self.assertEqual(self.submit(scope='private').status_code,403)
        self.assertEqual(self.count(),0)

    def test_group_membership_checked_on_each_submit(self):
        with patch.object(portal,'verify_chat_member',side_effect=portal.PortalError('Không còn trong nhóm',403)):
            self.assertEqual(self.submit().status_code,403)
        self.assertEqual(self.count(),0)

    def test_sender_and_chat_come_from_server(self):
        response=self.submit(owner=fixtures.OWNER,chat=fixtures.OWNER,requester_name='Giả tên')
        self.assertEqual(response.status_code,200,response.json)
        jid=response.json['job']['id']
        with self.q.db() as db:job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        self.assertEqual(job['owner'],fixtures.MEMBER);self.assertEqual(job['chat'],fixtures.GROUP)
        self.assertEqual(job['state'],'preview_queued')
        payload=json.loads(job['payload']);self.assertEqual(payload['requester_name'],'Tên LINE đã xác thực')
        self.assertIn('Mọi thắc mắc liên hệ Tên LINE đã xác thực',items(payload)[0]['note'])
        self.assertNotIn('product_name',items(payload)[0])

    def test_offline_off_and_lock_rules(self):
        self.q.heartbeat(False);self.assertEqual(self.submit().status_code,409)
        self.q.heartbeat();self.q.admin('BOT OFF');self.assertEqual(self.submit().status_code,409)
        self.q.admin('BOT ON')
        with self.q.db() as db:db.execute('INSERT INTO co_confirmation_locks VALUES(?,?,?,?,?,?)',(fixtures.MEMBER,'Member',3,0,'1234567890',time.time()))
        self.assertEqual(self.submit().status_code,409);self.assertEqual(self.count(),0)
        self.login(fixtures.OWNER);self.q.admin('BOT OFF')
        response=self.submit(scope='private');self.assertEqual(response.status_code,200,response.json)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT chat FROM jobs').fetchone()['chat'],fixtures.OWNER)

    def test_invalid_rows_blocked_shops_and_mixed_status_do_not_enqueue(self):
        for records in ([row(product='123')],[row()]*8,[row(),row(status='Đã sử dụng')],[row(note='x'*490)]):
            response=self.submit(records)
            self.assertEqual(response.status_code,400,response.json);self.assertIn('review',response.json)
        with patch.dict(compose.BLOCKED,{'447':{'name':'Shop thử','group':'Không kinh doanh ICT'}}):
            self.assertEqual(self.submit().status_code,400)
        self.assertEqual(self.count(),0)

    def test_idempotent_retry_and_changed_body_rejected(self):
        first=self.submit();second=self.submit()
        self.assertEqual(first.json['job']['id'],second.json['job']['id']);self.assertEqual(self.count(),1)
        self.assertEqual(self.submit([row(quantity='2')]).status_code,409)
        recovered=self.call('compose/submissions/'+self.key).json
        self.assertTrue(recovered['found']);self.assertEqual(recovered['job']['id'],first.json['job']['id'])
        self.login(fixtures.OTHER)
        self.assertFalse(self.call('compose/submissions/'+self.key).json['found'])

    def test_duplicate_rows_are_skipped_without_blocking_new_rows(self):
        self.submit()
        response=self.submit([row(),row(source='789')],key='b'*32)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(len(response.json['job']['rows']),1)
        self.assertEqual(response.json['job']['rows'][0]['source'],'789')
        self.assertEqual(len(response.json['job']['skipped_duplicates']),1)
        response=self.submit(key='c'*32)
        self.assertTrue(response.json['skipped']);self.assertEqual(self.count(),2)
        self.assertTrue(self.call('compose/submissions/'+'c'*32).json['skipped'])

    def test_gather_keeps_portal_receipt_and_retry_binding(self):
        with patch.dict('os.environ',{'CO_GATHER_SECONDS':'10'}):
            first=self.submit().json['job']['id']
            second=self.submit([row(source='789')],key='b'*32)
            self.assertEqual(second.json['job']['id'],first)
            self.assertEqual(len(second.json['job']['rows']),2)
            self.assertEqual(self.submit().json['job']['id'],first)
            self.assertEqual(self.submit([row(source='789')],key='b'*32).json['job']['id'],first)
            self.assertEqual(self.submit([row(source='111')],key='b'*32).status_code,409)
            self.assertEqual(self.count(),1)

    def test_preview_read_does_not_confirm_or_start_clock_until_seen(self):
        job,public=self.ready();self.assertTrue(public['can_ack_preview']);self.assertFalse(public['can_confirm'])
        self.assertIsNone(public['expires_at'])
        result=self.call('jobs/'+job['id']+'/preview-seen','POST',{'revision':public['preview_revision']})
        self.assertEqual(result.status_code,200,result.json)
        preview=result.json['job'];self.assertTrue(preview['can_confirm'])
        self.assertAlmostEqual(preview['expires_at']-time.time(),60,delta=2)
        self.assertEqual(self.fx.state(job['id']),'draft')
        again=self.call('jobs/'+job['id']+'/preview-seen','POST',{'revision':public['preview_revision']})
        self.assertEqual(again.json['job']['expires_at'],preview['expires_at'])
        confirmed=self.call('jobs/'+job['id']+'/confirm','POST',{})
        self.assertEqual(confirmed.status_code,200);self.assertEqual(self.fx.state(job['id']),'verified_queued')

    def test_preview_seen_only_sender_and_current_portal_preview(self):
        job,public=self.ready();path='jobs/'+job['id']+'/preview-seen'
        self.assertEqual(self.call(path,'POST',{'revision':'0'*64}).status_code,409)
        self.login(fixtures.OWNER)
        self.assertFalse(self.call('jobs/'+job['id']).json['job']['can_ack_preview'])
        self.assertEqual(self.call(path,'POST',{'revision':public['preview_revision']}).status_code,403)
        self.login(fixtures.MEMBER)
        line_job=self.job();self.assertEqual(self.call('jobs/'+line_job+'/preview-seen','POST',{'revision':'0'*64}).status_code,403)
        self.assertEqual(self.fx.state(job['id']),'draft')

    def test_expiry_penalty_after_visible_minute_is_unchanged(self):
        job,public=self.ready()
        self.call('jobs/'+job['id']+'/preview-seen','POST',{'revision':public['preview_revision']})
        with self.q.db() as db:db.execute('UPDATE jobs SET created=? WHERE id=?',(time.time()-61,job['id']))
        self.q.expire_confirmations();self.assertEqual(self.fx.state(job['id']),'expired')
        with self.q.db() as db:
            lock=db.execute('SELECT * FROM co_confirmation_locks WHERE owner=?',(fixtures.MEMBER,)).fetchone()
        self.assertEqual(lock['strikes'],1)
        self.assertEqual(self.submit([row(source='789')],key='b'*32).status_code,409)


if __name__=='__main__':unittest.main()
