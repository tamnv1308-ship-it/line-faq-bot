from test_admin_control import AdminTests
from co_flow import PRIVATE_CO_OWNER
from unittest.mock import patch

class PrivateCOTests(AdminTests):
    def test_other_private_forms_and_confirmations_are_rejected(self):
        for text in ['Kho xuất: 1\nKho nhận: 2\nMSP: 003','XACNHAN abc','XACNHAN ALL']:
            e=self.event(text,'operator');del e.source.group_id
            self.handle(e)
            self.assertIn('không nhận yêu cầu',self.replies[-1])
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],0)
    def test_owner_passes_private_gate(self):
        # Existing allowlist still applies after the private-chat restriction.
        e=self.event('Kho xuất: 1\nKho nhận: 2\nMSP: 003','operator');del e.source.group_id
        with patch('co_flow.PRIVATE_CO_OWNER','operator'):
            self.handle(e)
        self.assertIn('offline',self.replies[-1])
    def test_private_cancel_remains_available(self):
        e=self.event('HUY abc','operator');del e.source.group_id
        self.handle(e);self.assertNotIn('không nhận yêu cầu',self.replies[-1])
