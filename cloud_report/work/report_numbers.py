import os
"""Keep exact finite MWG amounts while summing in different grouping orders."""
from decimal import Decimal, getcontext


def configure_precision(values=()):
    whole = fraction = count = 0
    for value in values:
        value = Decimal(str(value))
        if not value.is_finite():
            raise ValueError('Số báo cáo phải hữu hạn')
        whole = max(whole, value.adjusted()+1)
        fraction = max(fraction, -value.as_tuple().exponent)
        count += 1
    # Two extra decimal places for VAT x1.08, plus carry digits for the sum.
    getcontext().prec = max(getcontext().prec, 64, whole+fraction+len(str(max(count,1)))+4)


configure_precision()
