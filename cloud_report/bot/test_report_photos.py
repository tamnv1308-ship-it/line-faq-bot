import unittest
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import report_photos as photos
import report_bot as bot

class PhotoTests(unittest.TestCase):
    def test_new_period_tables_replace_only_daily_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);replacement=folder/'week.jpg';replacement.write_bytes(b'jpg')
            report={'tables':[{'stem':'04_So_Sanh'},{'stem':'01_Vung'},{'stem':'03_01_iPhone'}],
                    'period_comparison_photos':[str(replacement)]}
            with patch.object(photos,'render_table_photos',side_effect=lambda t:[Path(t['stem']+'.jpg')]) as render:
                result=photos.report_photos(report)
            self.assertEqual(result,[replacement,Path('01_Vung.jpg'),Path('03_01_iPhone.jpg')])
            self.assertEqual([call.args[0]['stem'] for call in render.call_args_list],['01_Vung','03_01_iPhone'])

    def test_period_header_only_extends_first_photo_preserves_other_images(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            paths=[folder/'daily.jpg',folder/'daily-part2.jpg',folder/'regions.jpg']
            for path in paths:Image.new('RGB',(300,400),'white').save(path)
            original=[p.read_bytes() for p in paths]
            header=folder/'header.jpg';Image.new('RGB',(300,100),'blue').save(header)
            report={'tables':[{'stem':'04_So_Sanh'},{'stem':'01_Vung'}],
                    'comparison_header_photo':str(header),'overview_photo':'obsolete.jpg'}
            with patch.object(photos,'render_table_photos',side_effect=[paths[:2],paths[2:]]):
                result=photos.report_photos(report)
            self.assertEqual(len(result),3)
            self.assertEqual(result[1:],paths[1:])
            self.assertEqual([p.read_bytes() for p in paths],original)
            with Image.open(result[0]) as picture:self.assertEqual(picture.size,(300,500))

    def test_long_table_covers_each_whole_row_once(self):
        t={'stem':'03_San_Pham','width':1821,'height':7740,'rows':300}
        parts=photos.photo_sections(t)
        self.assertGreater(len(parts),1)
        self.assertEqual([i for a,b in parts for i in range(a,b)],list(range(300)))
        self.assertTrue(all((b-a)*25+182+58+28<=1821*1.3 for a,b in parts))
    def test_short_tables_remain_single_photo(self):
        self.assertEqual(photos.photo_sections({'stem':'01_Vung_Mien','width':1056,'height':535,'rows':13}),[(0,13)])
        self.assertEqual(photos.photo_sections({'stem':'04_So_Sanh','width':1130,'height':1698,'rows':56}),[(0,56)])
    def test_layout_change_refuses_to_drop_rows(self):
        with self.assertRaises(RuntimeError):
            photos.photo_sections({'stem':'03_San_Pham','width':1800,'height':1000,'rows':300})
    def test_albums_never_exceed_ten_or_contain_singleton(self):
        for count in range(2,101):
            sizes=photos.album_sizes(count)
            self.assertEqual(sum(sizes),count);self.assertTrue(all(2<=n<=10 for n in sizes))
    def test_partial_album_failure_never_retries_whole_report(self):
        report={'comparison_data':{'total':['0','0']}}
        sent=[{'message_id':i,'chat':{'id':-1},'photo':[{}]} for i in range(9)]
        with patch.object(photos,'report_photos',return_value=[Path(str(i)+'.jpg') for i in range(11)]),patch.object(bot,'telegram',side_effect=[sent,bot.ApiRejected('rejected')]) as send:
            with self.assertRaises(bot.DeliveryUncertain):
                bot.send_report({'chat_id':-1},report,datetime(2026,10,21,tzinfo=bot.VN))
        self.assertEqual(send.call_count,2)
        media=[json.loads(c.args[2]['media']) for c in send.call_args_list]
        self.assertTrue(all('caption' not in p for p in media[0]))
        self.assertEqual(sum('caption' in p for p in media[1]),1)
    def test_image_build_failure_sends_nothing(self):
        with patch.object(photos,'report_photos',side_effect=RuntimeError('bad layout')),patch.object(bot,'telegram') as send:
            with self.assertRaises(RuntimeError):bot.send_report({}, {},datetime(2026,10,21,tzinfo=bot.VN))
        send.assert_not_called()
