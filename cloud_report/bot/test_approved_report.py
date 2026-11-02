import copy
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'work'))
from report_comparison import VN
import approved_report as approved
import report_bot as bot
import report_photos as photos


def value(q='1', revenue='108'):
    return {'total': [q, revenue], 'models': {'iPhone 17': {'category': 0, 'values': [q, revenue]}}}


class ApprovedReportTests(unittest.TestCase):
    def fixture(self):
        slot = datetime(2026, 10, 28, 10, tzinfo=VN)
        report = {'report_date': '2026-10-28', 'comparison_data': value('3', '324')}
        days = {}
        day = date(2026, 9, 1)
        while day < slot.date():
            days[str(day)] = value()
            day += timedelta(days=1)
        return slot, report, days

    def test_calendar_day_baselines_live_month_and_no_double_vat(self):
        slot, report, days = self.fixture()
        original = copy.deepcopy((report, days))
        with patch('period_model_comparison.snapshot_data', side_effect=AssertionError('Must not read clock snapshots')) as snapshot:
            periods = approved.compare(Path('/unused'), report, {'exported_at_vn': slot.isoformat()}, slot, days)
        self.assertEqual([p['current']['total'] for p in periods], [['3','324'], ['5','540'], ['30','3240']])
        self.assertEqual([p['previous']['total'] for p in periods], [['1','108'], ['3','324'], ['28','3024']])
        self.assertEqual([p['basis'] for p in periods], ['calendar_days_current_partial']*3)
        snapshot.assert_not_called()
        self.assertEqual((report, days), original)

    def test_missing_closed_day_is_not_zero_or_substituted(self):
        slot, report, days = self.fixture()
        del days['2026-10-27']
        with patch('period_model_comparison.snapshot_data', side_effect=AssertionError('Unexpected clock lookup')):
            periods = approved.compare(Path('/unused'), report, {'exported_at_vn': slot.isoformat()}, slot, days)
        self.assertEqual(periods[0]['current']['total'], ['3','324'])
        self.assertIsNone(periods[1]['current'])
        self.assertIsNone(periods[2]['current'])
        self.assertIsNone(periods[0]['previous'])
        self.assertEqual(periods[1]['previous']['total'], ['3','324'])
        self.assertEqual(periods[2]['previous']['total'], ['28','3024'])
        self.assertTrue(all(p['growth']==[None,None] for p in approved.display_rows(periods)[0]['periods']))

    def test_month_end_and_year_boundary_dates(self):
        for day, previous in [(date(2026,3,31), date(2026,2,28)), (date(2027,1,1), date(2026,12,1))]:
            slot = datetime.combine(day, datetime.min.time(), tzinfo=VN).replace(hour=10)
            report = {'report_date': str(day), 'comparison_data': value('0','0')}
            with patch('period_model_comparison.snapshot_data', side_effect=AssertionError('Unexpected clock lookup')):
                periods = approved.compare(Path('/unused'), report, {'exported_at_vn': slot.isoformat()}, slot, {})
            self.assertEqual(periods[2]['previous_end'], str(previous))
            self.assertEqual(periods[1]['start'], str(day-timedelta(days=day.weekday())))
            if day.day == 1:
                self.assertEqual(periods[2]['current']['total'], ['0','0'])
                self.assertIsNone(periods[2]['previous'])
                self.assertEqual(periods[2]['start'], str(day))
                self.assertEqual(periods[2]['end'], str(day))
                self.assertIn('đang cập nhật', approved.date_label(periods[2]))

    def test_first_day_shows_live_sales_and_previous_first_day(self):
        slot = datetime(2026,11,1,20,5,tzinfo=VN)
        report = {'report_date':'2026-11-01','comparison_data':value('6033','156370000000')}
        days = {'2026-10-01':value('9876','210000000000'),
                '2026-11-01':value('100000','999999999999')}
        original=copy.deepcopy((report,days))
        month=approved.compare(Path('/unused'),report,{'exported_at_vn':slot.isoformat()},slot,days)[2]
        self.assertEqual(month['current']['total'], ['6033','156370000000'])
        self.assertEqual(month['previous']['total'], ['9876','210000000000'])
        self.assertEqual(month['start'],month['end'])
        self.assertEqual(month['previous_start'],month['previous_end'])
        self.assertEqual((report,days),original)

    def test_stale_or_wrong_day_source_rejected(self):
        slot, report, days = self.fixture()
        for exported in (slot+timedelta(minutes=10), slot-timedelta(seconds=1), slot+timedelta(days=1)):
            with self.assertRaises(ValueError):
                approved.compare(Path('/unused'), report, {'exported_at_vn':exported.isoformat()}, slot, days)

    def test_arbitrary_request_minute_uses_complete_previous_calendar_days(self):
        slot, report, days = self.fixture()
        slot = slot.replace(hour=17, minute=43)
        days['2026-10-27'] = value('10','1080')
        days['2026-10-21'] = value('20','2160')
        periods = approved.compare(Path('/unused'), report, {'exported_at_vn':slot.isoformat()}, slot, days)
        self.assertEqual(periods[0]['previous']['total'], ['10','1080'])
        self.assertEqual(periods[1]['previous']['total'], ['22','2376'])
        self.assertEqual(periods[1]['current']['total'], ['14','1512'])
        del days['2026-10-21']
        missing = approved.compare(Path('/unused'), report, {'exported_at_vn':slot.isoformat()}, slot, days)
        self.assertIsNone(missing[1]['previous'])

    def test_monday_and_year_boundary_keep_corresponding_weekdays(self):
        slot = datetime(2027,1,4,16,27,tzinfo=VN)
        report = {'report_date':'2027-01-04', 'comparison_data':value('7','756')}
        days = {'2027-01-03':value('5','540'), '2026-12-28':value('9','972')}
        periods = approved.compare(Path('/unused'), report, {'exported_at_vn':slot.isoformat()}, slot, days)
        self.assertEqual(periods[0]['previous']['total'], ['5','540'])
        self.assertEqual(periods[1]['start'], '2027-01-04')
        self.assertEqual(periods[1]['previous_start'], '2026-12-28')
        self.assertEqual(periods[1]['previous_end'], '2026-12-28')
        self.assertEqual(periods[1]['current']['total'], ['7','756'])
        self.assertEqual(periods[1]['previous']['total'], ['9','972'])

    def test_calendar_caption_uses_same_baseline_as_image(self):
        slot, report, days = self.fixture()
        report['comparison'] = {'basis':'calendar_days_current_partial',
                                'baseline_available':True, 'yesterday_total':['1','108']}
        caption = bot.report_summary(report, slot)
        self.assertIn('So với cả ngày hôm qua', caption)
        self.assertNotIn('cùng giờ', caption)
        self.assertEqual(caption.count('+200,0%'), 2)
        report['comparison']['baseline_available'] = False
        caption = bot.report_summary(report, slot)
        self.assertIn('Chưa có đủ số cả ngày hôm qua', caption)
        self.assertNotIn('%', caption)

    def test_accessories_included_in_total_without_detail_rows_and_returns_kept(self):
        source = value('-1','-108')
        source['models']['Watch Band']={'category':3,'values':['2','216']}
        source['models']['Adapter']={'category':5,'values':['3','324']}
        source['total']=['4','432']
        original=copy.deepcopy(source)
        result=approved.selected(source)
        self.assertEqual(result['total'],['4','432'])
        self.assertEqual(result['models']['Watch Band']['category'],5)
        self.assertEqual(source,original)
        periods=[{'current':result,'previous':result}]*3
        rows=approved.display_rows(periods)
        self.assertEqual(rows[0]['label'],'TỔNG TOÀN BỘ')
        models=[r['label'] for r in rows if r['kind']=='model']
        self.assertEqual(models,['iPhone 17'])
        accessories=next(r for r in rows if r['label']=='Phụ kiện tiện ích')
        self.assertEqual([str(v) for v in accessories['periods'][0]['current']],['5','540'])
        for metric in (0,1):
            self.assertEqual(sum(r['periods'][0]['current'][metric] for r in rows if r['kind']=='category'),
                             rows[0]['periods'][0]['current'][metric])

    def test_live_month_updates_today_once_and_keeps_previous_full_days(self):
        slot, report, days = self.fixture()
        with patch('period_model_comparison.snapshot_data',side_effect=AssertionError('Unexpected clock lookup')):
            morning=approved.compare(Path('/unused'),report,{'exported_at_vn':slot.isoformat()},slot,days)
            slot=slot.replace(hour=22)
            report['comparison_data']=value('999','107892')
            evening=approved.compare(Path('/unused'),report,{'exported_at_vn':slot.isoformat()},slot,days)
        self.assertEqual(morning[2]['current']['total'], ['30','3240'])
        self.assertEqual(evening[2]['current']['total'], ['1026','110808'])
        self.assertEqual(morning[2]['previous'],evening[2]['previous'])
        self.assertEqual(morning[2]['end'],'2026-10-28')
        self.assertEqual(morning[2]['previous_end'],'2026-09-28')
        self.assertIn('Kỳ trước trọn ngày',approved.date_label(morning[2]))
        self.assertNotIn('10:00',approved.date_label(morning[2]))
        self.assertNotIn('10:00',approved.date_label(morning[0]))
        self.assertIn('đang cập nhật', approved.date_label(morning[0]))
        self.assertEqual(morning[0]['previous'], evening[0]['previous'])
        self.assertEqual(morning[1]['previous'], evening[1]['previous'])
        self.assertEqual(evening[0]['current']['total'], ['999','107892'])

    def test_previous_calculation_blocked_before_send(self):
        report={'delivery_layout':approved.LAYOUT,'delivery_photos':['a','b','c']}
        with patch.object(bot,'telegram') as send:
            with self.assertRaises(RuntimeError):
                bot.send_report({'report_layout':approved.LAYOUT,'report_calculation':approved.CALCULATION},report,datetime.now(VN))
        send.assert_not_called()

    def test_new_layout_sends_exactly_three_photos_with_one_caption_for_all_modes(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            files=[Path(temp)/(str(i)+'.jpg') for i in range(3)]
            for p in files:Image.new('RGB',(100,100),'white').save(p)
            report={'delivery_layout':approved.LAYOUT,'delivery_photos':[str(p) for p in files],
                    'tables':[{'stem':'04_So_Sanh'},{'stem':'01_Vung'},{'stem':'03_06_Phu_Kien'}],
                    'comparison_data':value()}
            config={'report_layout':approved.LAYOUT,'chat_id':-100,'omit_accessory_details_scheduled':True}
            reply=[{'message_id':i,'chat':{'id':-100},'photo':[{}]} for i in range(3)]
            for scheduled in (False,True):
                with patch.object(bot,'telegram',return_value=reply) as send,patch.object(photos,'render_table_photos') as legacy:
                    bot.send_report(config,report,datetime(2026,10,28,10,tzinfo=VN),scheduled=scheduled)
                legacy.assert_not_called()
                send.assert_called_once()
                media=json.loads(send.call_args.args[2]['media'])
                self.assertEqual(len(media),3)
                self.assertEqual(sum('caption' in m for m in media),1)
                self.assertEqual([p for _,p in send.call_args.args[3]],files)

    def test_approved_config_never_silently_falls_back_to_old_images(self):
        with patch.object(bot,'telegram') as send:
            with self.assertRaises(RuntimeError):
                bot.send_report({'report_layout':approved.LAYOUT},{'tables':[]},datetime.now(VN))
        send.assert_not_called()

    def test_corrupt_third_photo_prevents_entire_album(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            files=[Path(temp)/(str(i)+'.jpg') for i in range(3)]
            for p in files[:2]:Image.new('RGB',(100,100),'white').save(p)
            files[2].write_bytes(b'broken image')
            report={'delivery_layout':approved.LAYOUT,'delivery_photos':[str(p) for p in files]}
            with patch.object(bot,'telegram') as send:
                with self.assertRaises(OSError):
                    bot.send_report({'report_layout':approved.LAYOUT},report,datetime.now(VN))
            send.assert_not_called()

    def test_production_build_wires_approved_layout_for_scheduled_and_manual_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            stamp=datetime(2026,10,28,10,1,tzinfo=VN)
            groups=['iPhone','iPad','Mac','Watch','AirPods','Phụ kiện tiện ích']
            def child(command, log, timeout):
                if '--output' in command:
                    output=Path(command[command.index('--output')+1])
                    output.with_suffix('.export.json').write_text(json.dumps({'source_rows':1,'exported_at_vn':stamp.isoformat()}))
                else:
                    checks=Path(command[command.index('--checks')+1])
                    tables=[]
                    for i,group in enumerate([None,None]+groups):
                        pdf=checks.parent/(str(i)+'.pdf');pdf.touch()
                        tables.append({'stem':str(i),'pdf':str(pdf),'category':group})
                    checks.write_text(json.dumps({'tables':tables,'source_rows':1,'report_date':'2026-10-28','grand_total':['1','0,00']}))
            with patch.object(bot,'ROOT',root),patch.object(bot,'PRIVATE',root/'.private'),patch.object(bot,'now_vn',return_value=stamp),\
                 patch.object(bot,'read_config',return_value={'report_layout':approved.LAYOUT}),patch.object(bot,'run_child',side_effect=child),\
                 patch.object(bot,'attach_comparison',side_effect=lambda report,*args:report),patch('pypdf.PdfWriter'),\
                 patch.object(approved,'build',return_value={'photos':['a.jpg','b.jpg','c.jpg'], 'comparison':{'basis':'calendar_days_current_partial'}}) as build:
                for key in ('1000-try1','telegram-test'):
                    report=bot.build_report(stamp.date(),key)
                    self.assertEqual(report['delivery_layout'],approved.LAYOUT)
                    self.assertEqual(report['delivery_photos'],['a.jpg','b.jpg','c.jpg'])
                    self.assertEqual(report['comparison']['basis'], 'calendar_days_current_partial')
                self.assertEqual(build.call_args_list[0].args[3],stamp.replace(minute=0))
                self.assertEqual(build.call_args_list[1].args[3],stamp)


if __name__=='__main__':unittest.main()
