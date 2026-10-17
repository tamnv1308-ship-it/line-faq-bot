# line-faq-bot
LINE FAQ BOT

## Giỏ nháp của Tâm trên Công cụ Táo

- Chỉ tài khoản Tâm được dùng: Trang chủ → **Giỏ nháp của Tâm**. Các ADM khác không được đọc hoặc thay đổi giỏ.
- Bấm **Bật gom nháp** trên LIFF hoặc gửi `!gom` trong chat riêng với bot; chuyển tiếp các tin văn bản vào chat riêng này. Giỏ tự cập nhật khoảng 6 giây khi đang mở.
- Chọn **Sửa**, chỉnh kho/MSP/SL/trạng thái/Note và **Lưu dòng**; **Bỏ dòng** chỉ bỏ dòng được chọn, giữ các dòng còn lại của cùng tin.
- Dữ liệu nháp dùng chung với LINE. Nếu giỏ thay đổi khi đang sửa, tải bản mới trước khi lưu; bản sửa chưa lưu không ghi đè dữ liệu mới.
- **Gửi yêu cầu** đưa giỏ vào bước nhập MWG, rồi vẫn cần **Xác nhận** trong 1 phút. Tối đa 7 dòng cùng trạng thái; quyền, lọc trùng, kho chặn và quy tắc tạo CO giữ nguyên.
- Khi mạng chậm, dùng **Kiểm tra lần gửi** hoặc **Thử lại cùng lần gửi**. Cùng một giỏ chỉ đưa vào hàng chờ một lần dù bấm từ LINE và LIFF.
- Sau khi gửi, tin chuyển tiếp tiếp theo vào giỏ mới. `!gom tat` tắt gom và bỏ phần nháp chưa gửi; không hủy yêu cầu đã gửi.

## Kênh Telegram cho CO

Phần kết nối Telegram đã được bổ sung nhưng mặc định chưa bật. LIFF vẫn dùng đăng nhập LINE và cùng dữ liệu hàng chờ/giỏ nháp. Khi bot Telegram đã cấu hình, vào **Kết nối Telegram** trên LIFF để liên kết và xác nhận chính tài khoản của mình. Quyền của Tâm, ADM và thành viên giữ nguyên.

Xem `bao_tri/TELEGRAM.md` để cấu hình, kiểm tra webhook, chuyển nhận yêu cầu mới và quay lại LINE. Không đưa token vào mã nguồn hoặc tin nhắn.
