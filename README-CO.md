# Tạo CO từ LINE với máy Mac

Bot nhận form, gửi bản xem lại, và chỉ đưa vào hàng đợi khi chính người gửi xác nhận trong cùng cuộc chat. Hàng đợi SQLite nằm trên persistent disk Render tại `/var/data/co.db`. Mặc định chỉ các quản trị viên có sẵn trong `config.ADMIN_USER_IDS` được dùng CO; có thể giới hạn riêng bằng `CO_ALLOWED_USER_IDS`.

## Chạy trên Mac đã chuẩn bị

Mở `Chay-bot-Mac.command`. Đăng nhập MWG trong cửa sổ Chrome riêng của bot, sau đó quay lại Terminal nhấn Enter. Giữ Terminal và Mac hoạt động trong khi dùng bot. Script ngăn máy tự ngủ khi worker đang chạy, không ngăn việc đóng nắp máy. Ctrl+C để dừng.

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

- `CO_ENABLED=1`
- `CO_DB_PATH=/var/data/co.db` trên persistent disk thật
- `CO_WORKER_TOKEN`: khóa ngẫu nhiên dùng chung với Mac, không công khai
- `CO_ALLOWED_USER_IDS`: tùy chọn, các LINE user ID phân cách bằng dấu phẩy; mặc định dùng quản trị viên bot

Giữ một instance và một Gunicorn worker. Các chức năng FAQ và báo cáo hiện có vẫn chạy.

## Cài trên máy khác

Cài Python 3.9+, Google Chrome, tạo virtualenv và cài `requirements-mac.txt`. Thiết lập `.env`, chạy `python mac_worker.py --login`, đăng nhập rồi `python mac_worker.py --live`. Launcher `.command` trong bản cài hiện tại trỏ tới virtualenv do phiên làm việc này chuẩn bị, cần sửa đường dẫn nếu chuyển thư mục.

## Gián đoạn và chống tạo trùng

Webhook trùng, xác nhận lặp và nhiều worker cùng nhận việc được chặn bằng giao dịch DB. Trước click Tạo CO, trạng thái `submitting` được lưu. Nếu mất kết nối sau đó, không tự click lại: tác vụ sang `unknown` và chặn hàng đợi để người vận hành đối chiếu MWG. Cần xác nhận mã CO thực tế hoặc xác nhận chưa tạo trước khi giải phóng tác vụ đó. Chưa có giao diện quản trị cho bước đối chiếu thủ công.

Kết quả chưa gửi được lưu tại `.co-mac/pending.json`. LINE được gửi lại với cùng retry key để giảm gửi trùng. Không xóa DB hoặc nhật ký khi tác vụ chưa rõ kết quả.

## Kiểm thử

`python -m unittest test_co_flow -v`: parser, giữ số 0 đầu mã sản phẩm, webhook trùng, xác nhận sai người/cuộc chat, hết hạn, nhận việc đồng thời, tác vụ gián đoạn và lưu kết quả qua lần mở DB mới.

Đã thử API Flask cục bộ qua luồng xác nhận → nhận việc → checkpoint → kết quả → gửi một lần; đã thử điền đúng mẫu Excel. Đã kiểm tra chọn ba thương hiệu trên giao diện MWG thật. Chưa hoàn tất kiểm thử đầu cuối từ tin nhắn LINE tới một CO thật trên profile Chrome riêng của Mac; cần đăng nhập và thực hiện một yêu cầu được người dùng xác nhận.
