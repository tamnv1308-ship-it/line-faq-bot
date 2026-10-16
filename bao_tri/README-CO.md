# Tạo CO từ LINE với máy Mac

## Kiểm tra và tách lỗi từng dòng (2026-10-15)

MSP phải đúng 13 chữ số, giữ nguyên số 0 đầu; không tự sửa hoặc đoán mã. Tin nhiều dòng sẽ bỏ riêng dòng sai độ dài và báo mã/kho/số lượng/lý do trong bản xác nhận. Khi nhập MWG, đối chiếu từng dòng rồi loại dòng báo lỗi hoặc thiếu tên, nhập lại phần hợp lệ trước bước xác nhận. Không nhập lại sau khi đã bấm Tạo CO.

Kết quả mới có trạng thái riêng từng dòng. Lỗi kho + MSP đang tạo được gắn đúng dòng; mã CO đã nhận được giữ nguyên. Dòng chưa trả kết quả vẫn cần đối soát, không tự gửi lại. Hàng chờ chỉ bảo vệ tồn của dòng chưa rõ; dữ liệu cũ không có trạng thái dòng vẫn giữ nguyên. Deploy máy chủ trước, sau đó cập nhật worker lúc rảnh.

Worker quan sát phản hồi `ImportExcel` của chính lần tải file qua nút web, không gửi thêm API nhập file. Ghép từng dòng bằng kho xuất/kho nhận/MSP/số lượng và đọc `ISERROR`, `ERRORNOTE`, `PRODUCTNAME`. Không dựa vào các hàng của popup Kendo vì cách hiển thị có thể không cho đọc đủ ô. Chỉ chấp nhận một phản hồi đúng lượt tải; xóa phản hồi cũ trước lượt nhập lại, gỡ bộ lắng nghe sau mỗi lượt. Sau Đồng ý vẫn đối chiếu bảng chính trước khi gửi xác nhận. Nhật ký lỗi chỉ ghi tên trường, không ghi nội dung phản hồi. Kiểm thử tải file ngoại tuyến (Chrome riêng, toàn bộ HTTP được mô phỏng): `CO_BROWSER_TESTS=1 python -m unittest bao_tri.kiem_thu.test_import_capture_browser -v`.

Bảng chính đọc các ô hiển thị, bỏ cột mẫu ẩn. Sau Đồng ý chờ tối đa 7 giây để đủ mọi dòng, đúng kho/MSP/số lượng/note và có tên sản phẩm ổn định 0,3 giây; không dừng ngay khi bảng chỉ hiện một phần. Khi xác nhận vẫn kiểm tra lại bảng đang giữ, không reload hoặc nhập lại. Nếu không khớp, nhật ký chỉ ghi số dòng/ô và kết quả so sánh từng trường, không ghi note hoặc thông tin đăng nhập.

## Trạng thái MWG và điều khiển Mac (2026-10-13)

Chọn đủ TGDD, DMX và TopZone trước khi chờ trạng thái sản phẩm: MWG có thể chỉ tải danh sách trạng thái sau khi chọn thương hiệu. Áp dụng cùng thứ tự cho yêu cầu mới và phục hồi khi rảnh; không thay thương hiệu khi đang giữ bản xác nhận. Mỗi lượt vẫn chờ trạng thái tối đa 7 giây và tối đa 5 lượt.

Máy chủ kiểm tra cả heartbeat và tiến độ giao diện. Worker gửi `health.state` và `health.progress_age_seconds` trong heartbeat/claim. Heartbeat còn mới nhưng tiến độ không đổi quá 60 giây được hiển thị là bị kẹt và tạm ngừng nhận yêu cầu. Worker cũ chỉ gửi online được hiển thị chưa kiểm tra MWG, không được nhận CO cho đến khi cập nhật. Các trạng thái đăng nhập, tải trang, kết nối lại và đang dừng cũng ngừng nhận. Worker đang xử lý bình thường hoặc giữ bản xác nhận vẫn cho gom yêu cầu theo quy tắc cũ. `!bot status` và `/co/worker/status` hiển thị trạng thái thực và cờ accepting; chỉ huy hiệu online không chứng minh MWG sẵn sàng.

Hủy/hết hạn bản xác nhận vẫn giải phóng bản nhập kể cả MWG chưa sẵn sàng. Không phạt người gửi khi hết hạn trong lúc MWG không hoạt động. Các kết quả chưa rõ vẫn giữ để đối soát, không tạo lại CO.

Trên bản Mac đã cài: `Bat-BOT.command` mở một phiên; `Tat-BOT.command` gửi yêu cầu dừng đúng phiên bằng UUID; `Kiem-tra-BOT.command` hiển thị trạng thái. Dừng chờ thao tác hiện tại, lưu kết quả và đóng Chrome của bot, không đụng Chrome cá nhân. Nếu gửi kết quả đang lỗi mạng thì giữ file kết quả để gửi lại, không tạo lại. Khóa hệ thống được giữ đến khi trình duyệt và heartbeat dừng. Worker chặn mở hai phiên; yêu cầu dừng cũ không tác động phiên mới.

Sau khi chọn thương hiệu, ô trạng thái có riêng tối đa 7 giây để xuất hiện ổn định; tối đa 5 lượt. Khi rảnh, có thể phục hồi ô trống tối đa 5 lượt; không reload khi đang giữ bản xác nhận, đang tạo CO, còn kết quả chưa gửi hoặc vừa tạo CO chưa rõ kết quả trên chính trang này. Các yêu cầu chưa rõ từ phiên cũ vẫn giữ nguyên trên máy chủ và chặn các dòng xung đột, nhưng không chặn phục hồi trang rảnh của phiên mới. Giữ quy tắc reload 5 phút khi rảnh. Lỗi trang được lưu ảnh cục bộ trong `.co-mac/diagnostics` (không chụp trang đăng nhập, không gửi ảnh lên LINE). Các file worker trên Mac dùng môi trường riêng; deploy Render không tự thay chương trình Mac đang chạy.

## Gom tin nhắn trong 10 giây (2026-10-12)

Mặc định `CO_GATHER_SECONDS=10`: từ lúc nhận tin đầu, bot đợi một cửa sổ cố định 10 giây và gom các tin hợp lệ của cùng người gửi, cùng cuộc chat, cùng trạng thái sản phẩm. Tin tiếp theo không kéo dài cửa sổ. Mỗi file tối đa 7 dòng; một tin có nhiều dòng được giữ nguyên, không chia nhỏ để lấp chỗ trống. Tin vượt giới hạn hoặc đến sau cửa sổ sẽ thành yêu cầu riêng. Có thể đặt `CO_GATHER_SECONDS=0` để trở lại xử lý từng tin ngay.

Sau cửa sổ, Mac nhập một file và gửi một bản xác nhận chung. Xác nhận/Hủy áp dụng toàn bộ các dòng trong bản đó, chỉ người gửi hoặc chủ bot được thao tác theo quyền hiện có. Hiệu lực vẫn là 1 phút từ khi bản xác nhận được gửi thành công. Khi xác nhận, bot dùng bảng đã nhập để tạo CO, không reload hoặc nhập lại chỉ vì đã gom tin. Kết quả liệt kê từng dòng cùng mã CO/lỗi.

Chống trùng, chặn kho nhận và quy tắc trạng thái chưa rõ kết quả vẫn áp dụng trước khi nhận thêm dòng. Tin đã nhận lại do LINE gửi lại không được thêm lần hai. Tổng kết vẫn đếm đủ số tin yêu cầu ban đầu. Dữ liệu ánh xạ tin gom được dọn cùng lịch sử sau 30 ngày và giữ dấu chống xử lý lại.

Thay đổi nằm ở `co_flow.py`, `co_summary.py`, `co_summary_view.py`; worker Mac hiện tại đã hỗ trợ file nhiều dòng. Kiểm thử: `PYTHONPATH=bao_tri/kiem_thu:. python -m unittest test_gather test_preview_reply` và `python -m unittest discover -s bao_tri/kiem_thu`. Các phần bên dưới mô tả những phiên bản trước; mục này là quy tắc gom tin mới nhất.

Bot nhận form, gửi bản xem lại, và chỉ đưa vào hàng đợi khi chính người gửi xác nhận trong cùng cuộc chat. Hàng đợi SQLite nằm trên persistent disk Render tại `/var/data/co.db`. Mặc định chỉ các quản trị viên có sẵn trong `config.ADMIN_USER_IDS` được dùng CO; có thể giới hạn riêng bằng `CO_ALLOWED_USER_IDS`.

## Chạy trên Mac đã chuẩn bị

Mở `Bat-BOT.command` để bật chế độ tự động. LaunchAgent `vn.tam258330.line-co-bot` chạy trong tài khoản Mac hiện tại khi đăng nhập. `bot_service.py` giữ một worker, nhận quản lý phiên đang chạy nếu xác minh đúng PID/thư mục/nhóm tiến trình, và mở lại sau khi worker thoát với thời gian chờ 5–60 giây. Lỗi của supervisor được launchd mở lại. Không cần giữ Terminal mở.

`Tat-BOT.command` lưu `enabled=false` vào `.co-mac/service-control.json` trước khi dừng, vô hiệu hóa LaunchAgent và yêu cầu đúng UUID worker dừng an toàn. Sau khi worker dừng, gỡ phiên LaunchAgent đang nạp. Trạng thái Tắt tồn tại qua khởi động lại Mac; Bật sẽ bật lại LaunchAgent. Khóa điều khiển ngăn Bật/Tắt và khởi chạy worker chạy đua. Cài ban đầu bằng Python của `.venv-co`: `python bot_control.py install`.

Đăng nhập MWG trong Chrome riêng nếu phiên đã hết; worker tự nhận lại khi trang sẵn sàng, không cần Enter. `caffeinate -i` ngăn ngủ do không thao tác khi worker chạy, không ngăn đóng nắp máy. Tự mở lại không gửi lại thao tác tạo CO; kết quả lưu và các trạng thái cần đối soát vẫn được giữ nguyên. Nhật ký tự chạy: `.co-mac/service.log`, `.co-mac/worker-auto.log` (xoay khi khởi chạy nếu quá 4 MiB).

Mac dùng `.env` riêng chứa `CO_BOT_URL` và `CO_WORKER_TOKEN`, không đưa tệp này lên GitHub. Bot không đọc cookie từ Chrome cá nhân. Phiên đăng nhập riêng được lưu trong `.co-mac/browser`.

## Sử dụng trong LINE

```text
Kho xuất: 645
Kho nhận: 10341
Mã sản phẩm: 0131491005424
Số lượng: 1
Note: DM Hoàng XN
```

Các giá trị trên là ví dụ, không tự gửi để tạo lại lệnh cũ. Kiểm tra bản xem lại trước khi gửi `XACNHAN <mã yêu cầu>`. Gửi `HUY <mã>` hoặc `SUA <mã>` để hủy bản nháp. Sau khi sửa, gửi form mới và xác nhận lại. Xác nhận hết hạn sau 15 phút. `Note` điền Ghi chú, không tự bật cột Chuyển gấp.

Worker chọn TGDD, DMX và TopZone, tải một mẫu mới có tiền tố `StoreChangeOrderTGDD`, điền đúng một dòng và nhập lại. Khi có lỗi import: bấm Đồng ý, nhận cảnh báo OK, Hủy hộp nhập và trả lỗi. Trước Tạo CO, worker đối chiếu lại kho, sản phẩm, số lượng và ghi chú. Thành công chỉ khi dòng có mã CO và không có nội dung lỗi.

## Cấu hình Render

Lọc dòng trùng: so sánh kho xuất, kho nhận, mã sản phẩm và số lượng. Trong cùng tin nhắn giữ bản đầu, không cộng số lượng hoặc ghép ghi chú. Dòng trùng yêu cầu đang chờ/đang xử lý/chưa rõ kết quả được bỏ qua; các dòng còn lại vẫn đi qua kiểm tra MWG và xác nhận. Bản xác nhận/kết quả nêu số dòng đã bỏ. Nếu không còn dòng mới, ghi nhận sự kiện đã xử lý nhưng không tạo job hoặc thay đổi yêu cầu gốc. Cơ chế gom 10 giây, quyền xác nhận và chặn kho/mã sản phẩm chưa rõ kết quả vẫn giữ nguyên. `/co/worker/status` trả `duplicate_filter_version: 1` khi bản này đã chạy.

- `CO_ENABLED=1`
- `CO_DB_PATH=/var/data/co.db` trên persistent disk thật
- `CO_WORKER_TOKEN`: khóa ngẫu nhiên dùng chung với Mac, không công khai
- `CO_ALLOWED_USER_IDS`: tùy chọn, các LINE user ID phân cách bằng dấu phẩy; mặc định dùng quản trị viên bot

Giữ một instance và một Gunicorn worker. Các chức năng FAQ và báo cáo hiện có vẫn chạy.

## Cài trên máy khác

Cài Python 3.9+, tạo virtualenv và cài `requirements-mac.txt`. Cài Google Chrome chính thức trong Applications. Worker dùng channel `chrome`, không cần tải Chrome for Testing. Thiết lập `.env`, chạy `python mac_worker.py --login --live`, đăng nhập nếu cần rồi nhấn Enter để tiếp tục chạy trong cùng cửa sổ. Launcher `.command` trong bản cài hiện tại trỏ tới virtualenv do phiên làm việc này chuẩn bị, cần sửa đường dẫn nếu chuyển thư mục.

## Gián đoạn và chống tạo trùng

Webhook trùng, xác nhận lặp và nhiều worker cùng nhận việc được chặn bằng giao dịch DB. Trước click Tạo CO, trạng thái `submitting` được lưu. Nếu mất kết nối sau đó, không tự click lại: tác vụ sang `unknown` và chặn hàng đợi để người vận hành đối chiếu MWG. Cần xác nhận mã CO thực tế hoặc xác nhận chưa tạo trước khi giải phóng tác vụ đó. Chưa có giao diện quản trị cho bước đối chiếu thủ công.

Kết quả chưa gửi được lưu tại `.co-mac/pending.json`. LINE được gửi lại với cùng retry key để giảm gửi trùng. Không xóa DB hoặc nhật ký khi tác vụ chưa rõ kết quả.

## Kiểm thử

`python -m unittest discover -s bao_tri/kiem_thu -p test_co_flow.py -v`: parser, giữ số 0 đầu mã sản phẩm, webhook trùng, xác nhận sai người/cuộc chat, hết hạn, nhận việc đồng thời, tác vụ gián đoạn và lưu kết quả qua lần mở DB mới.

Đã thử API Flask cục bộ qua luồng xác nhận → nhận việc → checkpoint → kết quả → gửi một lần; đã thử điền đúng mẫu Excel. Đã kiểm tra chọn ba thương hiệu trên giao diện MWG thật. Chưa hoàn tất kiểm thử đầu cuối từ tin nhắn LINE tới một CO thật trên profile Chrome riêng của Mac; cần đăng nhập và thực hiện một yêu cầu được người dùng xác nhận.

Bản Mac đã chuyển lại Google Chrome chính thức và hồ sơ `.co-mac/browser` vì Chrome for Testing bị macOS chặn do thiếu dữ liệu chữ ký. Đã kiểm tra cấu hình bằng mock; chưa kiểm chứng chạy đầu cuối và chưa xác nhận khắc phục crash cũ. Không gửi lại yêu cầu đang chờ trước khi kiểm tra kết quả để tránh trùng CO.

Mẫu dùng chung: `templates/StoreChangeOrderTGDD_template.xlsx` (mẫu trắng đã kiểm tra). Worker không tải mẫu qua Chrome mỗi yêu cầu; mỗi yêu cầu ghi file riêng trong `.co-mac/<id>/`. Nếu MWG đổi mẫu, thay mẫu trắng này trước khi chạy. Mỗi lần điền vẫn kiểm tra tiêu đề và từ chối mẫu có dữ liệu sẵn.

## Kiểm tra tên sản phẩm trước xác nhận (2026-09-21)
Yêu cầu mới vào hàng kiểm tra: Mac reload, nhập Excel để đọc tên sản phẩm MWG, chưa bấm tạo. Bot dùng reply token của form để gửi thẳng bản xác nhận có tên sau khi nhập file; không gửi tin nhận yêu cầu và không cần bước XEM. Người gửi dùng XACNHAN để tạo. Mac kiểm tra lại tên khi tạo. Nếu kiểm tra quá 45 giây, bot trả thông báo chậm trước khi token hết hạn; bản xác nhận khi có kết quả chuyển sang push và chịu hạn mức LINE. Worker cũ không nhận hàng kiểm tra mới; khởi động lại worker đã cập nhật.
Reload trước mỗi yêu cầu và sau 5 phút rảnh vẫn giữ; không reload khi có kết quả chưa rõ hoặc tác vụ đang xử lý. Reload không bảo đảm phiên đăng nhập không hết hạn.
!say có thể bị LINE từ chối do hết hạn mức tháng; cập nhật Render không cấp thêm hạn mức LINE. Không tự nâng gói hay gửi thử tin tới nhóm.

XACNHAN dùng lại đúng dòng đã nhập trong phiên Mac hiện tại: không reload/upload lần hai. Bot giữ trang trong lúc chờ (tối đa 15 phút), tạm dừng reload định kỳ và nhập yêu cầu kế tiếp đến khi xác nhận/hủy/hết hạn. Nếu mất phiên hoặc dòng bị đổi, báo lỗi trước khi tạo, không tự nhập lại. Lệnh XACNHAN riêng giữ reply token để trả kết quả hoặc lỗi; quá 45 giây báo chờ/không rõ kết quả rồi dùng push cho kết quả sau. Khởi động lại Mac worker một lần để nạp bản sửa.

## Batch requests (2026-09-24)

Send up to seven complete labelled requests in one LINE message. Repeat the product/source labels or separate records with `====`. Each record requires source warehouse, destination warehouse and product ID; omitted quantity defaults to 1. Explicit invalid quantities are rejected. Notes include Note/Ghi chú and lines starting with QL/QLST cho hàng or DM xác nhận. All rows must share the product status; duplicate source/destination/product combinations must be combined before sending.

The Mac imports one file, returns MWG product names, then holds the same table until XACNHAN or cancellation. XACNHAN ALL on the one batch uses the same deferred reply path. Results match warehouses/product/quantity/note rather than MWG row order, and list names plus COs/errors. Unknown outcomes keep the queue blocked for reconciliation; successful rows are never automatically retried.

Deploy co_results.py together with app.py, co_flow.py, transfer_parser.py and mac_worker.py. Restart the Mac worker after the server is live. Older workers cannot claim batch jobs. Polling is 1 second while waiting for confirmation and 2 seconds otherwise. Idle reload remains 5 minutes and is suppressed while holding a prepared table.

## ADM controls and Mac availability (2026-09-25)

Only IDs in ADMIN_USER_IDS can use `!listadm`, `!bot on`, `!bot off`, `!bot status`, `!huy cho all` (also accepted without `!`, case insensitive). The CO operator allowlist does not grant ADM privileges. Global cancellation covers draft/queued/verified_queued/preview_queued across all owners/chats, preserving in-flight and unknown jobs and created COs.

The updated Mac worker sends an authenticated heartbeat every 10 seconds after login and startup recovery. After 30 seconds without a heartbeat, new forms and confirmations are rejected without adding jobs. BOT OFF persists across heartbeats and server restarts, pauses new claims but lets an already-claimed operation finish. BOT ON requires a fresh heartbeat. Reconnecting expires waiting requests older than 15 minutes before claiming work. Graceful worker exit reports offline; abrupt exit relies on heartbeat expiry. Restart the Mac worker after deployment; the older worker cannot send heartbeat and therefore will not receive new work.


## Cần Tâm xử lý và đo thời gian (2026-10-17)

Trong Công cụ Táo, chủ bot Tâm 258330 có mục **Cần Tâm xử lý**. API `/tao/api/admin/operations` chỉ chấp nhận phiên LINE đã xác thực của chủ bot; ADM khác và thành viên không được xem. Mục này cung cấp hướng dẫn và liên kết đến các thao tác đã có, không tự hủy, xác nhận, thử tạo lại hay thay đổi hàng chờ.

Theo dõi Mac/MWG cần đăng nhập, mất kết nối, bị kẹt; yêu cầu chưa rõ kết quả; lỗi từng dòng (kể cả lô có một phần thành công); thông báo LINE chưa gửi được; yêu cầu chờ/xử lý lâu. Lỗi của yêu cầu đã hoàn tất hiển thị trong 24 giờ; yêu cầu chưa rõ kết quả vẫn hiện cho đến khi được đối chiếu theo quyền hiện tại. Nguyên nhân được phân loại từ thông báo đã ghi nhận; khi thiếu chứng cứ thì không khẳng định nguyên nhân.

Nhật ký `co_ops_events` ghi mốc tiếp nhận, lấy dữ liệu MWG, đưa bản xác nhận tới người dùng, người dùng xác nhận, đến lượt tạo, gửi tạo CO, nhận kết quả và gửi thông báo. Thời gian chờ xác nhận tách khỏi thời gian xử lý. Dashboard tính trung bình và phân vị 95 trên các lượt có đủ mốc trong 24 giờ gần nhất, kèm số mẫu. Không suy đoán dữ liệu quá khứ; giới hạn tối đa 1.000 yêu cầu trong một lượt tổng hợp và có thông báo nếu bị giới hạn.

Worker ghi từng thao tác bằng đồng hồ monotonic vào `.co-mac/telemetry-pending.json` (quyền 0600), gửi cùng heartbeat/kết quả, loại trùng theo ID và kiểm tra lease tại máy chủ. Không ghi token, note, nội dung tin nhắn hay exception gốc vào nhật ký sự kiện. Spool cục bộ tối đa 1.000 sự kiện, chỉ giữ trong 30 ngày; mất dữ liệu đo không được cản trở lưu kết quả CO. Máy chủ dọn nhật ký theo lịch giữ lịch sử 30 ngày hiện có. Chi tiết từng thao tác có thể đến trễ vài giây hoặc thiếu khi worker cũ/chưa kết nối.

Triển khai máy chủ trước, sau đó nạp lại worker khi không có yêu cầu đang xử lý/chờ xác nhận hay kết quả đang chờ gửi. Không thay đổi quyền, thời hạn Xác nhận 60 giây, kiểm tra trùng, quy tắc hủy kết quả chưa rõ, tự tải lại trang hoặc chế độ Bật/Tắt.
