"""Exercise the real app handler without importing its schedulers or LINE client."""
import ast
import types
import unittest
from pathlib import Path
from unittest.mock import Mock
import co_flow

class UnlockDispatchTests(unittest.TestCase):
    def test_bang_unlock_commands_reach_co_handler(self):
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='handle_message')
        function.decorator_list=[]
        code=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
        handle=Mock(return_value=True)
        scope={'co_flow':co_flow,'config':types.SimpleNamespace(BOT_PREFIX='!'),
               'log_message_source':lambda event:None,'handle_summary':lambda event:False,
               'handle_price':lambda event:False,
               'handle_co':handle}
        exec(compile(code,'app-handler-test','exec'),scope)
        for text in ('!mokhoa','!mokhoa 2','!MoKhOa 1'):
            event=types.SimpleNamespace(message=types.SimpleNamespace(text=text))
            scope['handle_message'](event)
            handle.assert_called_with(event)

    def test_similar_keywords_do_not_intercept_faq(self):
        self.assertFalse(co_flow.is_unlock('!mokhoaabc'))
        self.assertFalse(co_flow.is_unlock('Nội dung !mokhoa 2'))

if __name__=='__main__':unittest.main()
