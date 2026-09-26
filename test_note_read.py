import unittest
from test_note_group import NoteGroupTests
from test_admin_control import AdminTests
from co_flow import NOTE_GROUP

class NoteReadTests(NoteGroupTests):
    def seed(self,n=27):
        with self.q.db() as db:
            db.execute('INSERT INTO co_note_outbox(job_id,destination,message) VALUES(?,?,?)',('batch',NOTE_GROUP,'Đã tạo CO\nNgười yêu cầu: Tâm' + ''.join('\n\nTên sản phẩm: iPhone\nCO: 123CO'+str(i)+'\nSố lượng: 1' for i in range(n))))
    def test_pages_and_no_repeat(self):
        self.seed();texts=[]
        for i,n in enumerate([10,10,7]):
            self.q.reply_notes(str(i),lambda t:texts.append(t) or True)
            self.assertEqual(texts[-1].count('CO: '),n)
        self.q.reply_notes('3',lambda t:texts.append(t) or True)
        self.assertIn('Chưa có',texts[-1])
        with self.q.db() as db:self.assertEqual(db.execute('SELECT delivered FROM co_note_outbox').fetchone()['delivered'],1)
    def test_failed_reply_preserves_results_and_redelivery(self):
        self.seed(2);texts=[]
        self.q.reply_notes('e',lambda t:False)
        self.q.reply_notes('e',lambda t:texts.append(t) or True)
        self.q.reply_notes('e',lambda t:texts.append(t) or True)
        self.assertEqual(len(texts),1);self.assertEqual(texts[0].count('CO: '),2)

class NoteReadAuthTests(AdminTests):
    def test_permissions_and_group(self):
        self.handle(self.event('!ketqua','operator'));self.assertIn('chỉ dành',self.replies[-1])
        self.handle(self.event('!ketqua'));self.assertIn('nhóm NOTE',self.replies[-1])
        e=self.event('!ketqua');e.source.group_id=NOTE_GROUP
        self.handle(e);self.assertIn('Chưa có',self.replies[-1])
