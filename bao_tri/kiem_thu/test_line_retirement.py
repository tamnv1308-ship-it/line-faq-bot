"""Exercise actual app transport functions without importing its schedulers."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

class RetirementTests(TestCase):
    def setUp(self):
        tree=ast.parse(Path('app.py').read_text())
        names={'callback','push_to_group','push_image_to_group','reply_text','push_co_result','reply_summary_image','reply_price_cards'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        for node in nodes:node.decorator_list=[]
        self.transport=Mock()
        self.ns={'telegram_bridge':SimpleNamespace(settings=lambda:{'active':True},is_chat=lambda x:str(x).startswith('tg:')), 'telegram':self.transport}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'app.py','exec'),self.ns)

    def test_line_callback_and_all_outbound_paths_disabled(self):
        self.assertEqual(self.ns['callback'](),'OK')
        for name,args in [('push_to_group',('C1','text')),('push_image_to_group',('C1','image')),('reply_text',('line-token','text')),('push_co_result',('C1','text','retry')),('reply_summary_image',('line-token','image')),('reply_price_cards',('line-token',[]))]:
            result=self.ns[name](*args)
            self.assertFalse(result[0] if isinstance(result,tuple) else result)
        self.assertEqual(self.transport.mock_calls,[])

    def test_telegram_delivery_kept(self):
        self.ns['reply_text']('tgr:1','text')
        self.transport.reply.assert_called_with('tgr:1','text')
        self.ns['push_co_result']('tg:1','result','retry')
        self.transport.send.assert_called_with('tg:1','result','retry')
        self.ns['reply_summary_image']('tgr:1','image')
        self.transport.reply.assert_called_with('tgr:1','image',photo=True)
