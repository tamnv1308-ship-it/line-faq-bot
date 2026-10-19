"""Local stock holds for unresolved COs; never change queue evidence or retry MWG."""
import json
from pathlib import Path

from mwg_result_contract import row_identity


class ReconciliationHold(ValueError):
    pass


def enforce(root, job_id, records):
    path = Path(root) / 'reconciliation-holds.json'
    try:
        body = json.loads(path.read_text())
        if not isinstance(body, dict) or body.get('version') != 1:
            raise ValueError()
        holds = body['rows']
        if not isinstance(holds, list):
            raise ValueError()
        protected = set()
        jobs = set()
        for row in holds:
            identity = row_identity(row)
            if not isinstance(row.get('job_id'), str) or not row['job_id']:
                raise ValueError()
            protected.add((identity[0], identity[2]))
            jobs.add(row['job_id'])
    except FileNotFoundError:
        # Existing installations without an explicit hold file are unchanged.
        # This deployment sets the required marker, so deletion cannot unlock it.
        if (Path(root) / 'reconciliation-holds.required').exists():
            raise ReconciliationHold('Thiếu hồ sơ khóa CO chưa đối soát; chưa tạo CO.') from None
        return
    except (OSError, ValueError, KeyError, TypeError):
        raise ReconciliationHold('Không đọc được hồ sơ khóa CO chưa đối soát; chưa tạo CO.') from None
    if job_id in jobs or any((key[0], key[2]) in protected for key in map(row_identity, records)):
        raise ReconciliationHold(
            'Kho xuất + mã sản phẩm còn CO cũ chưa rõ kết quả. '
            'Đã giữ khóa đối soát trên Mac; chưa nhập file hoặc tạo CO cho yêu cầu này.')
