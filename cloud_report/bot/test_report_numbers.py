import sys
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'work'))
from report_numbers import configure_precision


class ExactRevenueTests(unittest.TestCase):
    def test_grouping_preserves_tiny_source_fractions_without_removing_checks(self):
        with localcontext() as context:
            context.prec=28
            source=[Decimal('100000000000.00000000000000001'),Decimal('-100000000000'),Decimal('0.00000000000000002')]
            self.assertNotEqual(sum(source),sum(reversed(source)))
            configure_precision(source)
            self.assertEqual(sum(source),sum(reversed(source)))
            self.assertEqual(sum(source),Decimal('0.00000000000000003'))
            vat=[v*Decimal('1.08') for v in source]
            self.assertEqual(sum(vat),sum(source)*Decimal('1.08'))

    def test_precision_adapts_to_more_fractional_digits(self):
        with localcontext() as context:
            context.prec=28
            source=[Decimal('100000000000'),Decimal('1e-90'),Decimal('-100000000000')]
            configure_precision(source)
            self.assertEqual(sum(source),Decimal('1e-90'))

    def test_non_finite_money_is_still_rejected(self):
        with self.assertRaises(ValueError): configure_precision(['NaN'])


if __name__=='__main__': unittest.main()
