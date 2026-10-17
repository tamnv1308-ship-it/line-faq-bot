# Telegram cho CO, giữ nguyên LIFF

Bản này thêm kênh Telegram dùng **cùng Queue, Mac worker và dữ liệu LIFF**. Không tự chuyển kênh khi triển khai mã. Mặc định LINE vẫn nhận CO; không khởi động lại Mac để đổi kênh nhắn tin.

## Thiết lập

1. Tạo bot qua [BotFather chính thức](https://t.me/BotFather). Lưu token vào biến bí mật `TELEGRAM_BOT_TOKEN` trên Render; không gửi token trong chat hoặc commit vào Git.
2. Đặt `TELEGRAM_BOT_USERNAME` là tên bot vừa tạo (không có @); `TELEGRAM_WEBHOOK_SECRET` là chuỗi ngẫu nhiên 32–256 ký tự A–Z/a–z/0–9/_/-. Đặt `TELEGRAM_ENABLED=1`, `CO_INTAKE_TRANSPORT=line` trong giai đoạn kết nối.
3. Thêm bot vào nhóm được chọn; đặt ID nhóm âm vào `TELEGRAM_CO_GROUP_ID`. `TELEGRAM_NOTE_GROUP_ID` tùy chọn, dùng cho `/ketqua` của ADM. Không tự suy đoán nhóm từ tin gửi đến.
4. Để giữ Privacy Mode, thành viên gửi `/taoco@ten_bot` và nội dung form cùng một tin; hoặc trả lời trực tiếp tin bot. Đừng tắt Privacy Mode hoặc cấp quyền quản trị chỉ để nhận toàn bộ hội thoại. Nếu cần xác minh thành viên từ LIFF bằng `getChatMember`, Telegram chỉ bảo đảm kết quả cho người khác khi bot là quản trị viên; chủ nhóm phải quyết định và cấp các quyền tối thiểu. Không tự thay quyền nhóm.
5. Trong Render Shell, chạy `python telegram_setup.py` để kiểm tra bot, rồi `python telegram_setup.py --register` để đăng ký webhook vào `/telegram/webhook`. Lệnh không bỏ các tin đang chờ và từ chối ghi đè webhook trỏ sang máy chủ khác. Chỉ báo thành công khi `webhook_matches` là `true`.
6. Mở LIFF → **Kết nối Telegram** → tạo liên kết → mở Telegram và nhấn Start → quay LIFF, kiểm tra tên/mã Telegram rồi **Xác nhận liên kết**. Liên kết hết hạn sau 5 phút, chỉ dùng một lần. Chủ bot liên kết chính tài khoản của mình để giữ quyền. Thành viên trong nhóm CO cấu hình dùng ngay, không cần liên kết LIFF. Không cấp quyền theo username, tên hiển thị, tin chuyển tiếp hay chức vụ quản trị nhóm Telegram.
7. Kiểm thử tài khoản Tâm, thành viên, ADM; gửi form đến bước xác nhận, kiểm tra Xác nhận/Hủy, hết hạn, bot off, giỏ nháp, kết quả và LIFF. Không bấm Xác nhận tạo CO thật nếu mới kiểm thử bước nhập file.
8. Khi đã kiểm chứng xong, đặt `CO_INTAKE_TRANSPORT=telegram`. Các yêu cầu **mới** trong chat LINE được hướng sang Telegram; LIFF vẫn đăng nhập LINE và gửi yêu cầu vào Telegram. Yêu cầu LINE cũ giữ chat gốc, vẫn xác nhận/hủy/trả kết quả qua LINE để không thất lạc.

## Giữ nguyên quy tắc

- Chỉ tài khoản LINE Tâm đã liên kết đúng Telegram có quyền chủ bot, nhắn riêng tạo CO, gom nháp, mở khóa, xem tổng kết và thao tác yêu cầu người khác.
- ADM vẫn chỉ có quyền hiện có; thành viên nhóm Telegram được chỉ định được gửi yêu cầu và chỉ xác nhận/hủy yêu cầu của mình.
- Hạn xác nhận 1 phút, khóa do quá hạn, chống trùng, kiểm tra MSP/kho/trạng thái/cụm/vùng, nhập file trước xác nhận, bot off chỉ Tâm được tạo: dùng nguyên mã Queue.
- Cùng người/cùng chat/cùng trạng thái vẫn được gom theo cấu hình 10 giây đang có.
- Thành viên chưa liên kết dùng mã Telegram riêng; quyền sở hữu và khóa quá hạn giữ nguyên cả khi liên kết LIFF sau đó. Lịch sử Telegram của các thành viên này chưa gộp vào lịch sử cá nhân LIFF. Tài khoản đã liên kết trước lần sử dụng đầu tiên (bao gồm Tâm) giữ đồng bộ và quyền hiện có.

## Tin nhắn và phục hồi

- Webhook phải có secret header; update được lưu trước khi trả HTTP 200 và xử lý qua cùng event ID. Telegram gửi lại một update không tạo thêm yêu cầu.
- Chỉ xử lý tin mới và callback; không xử lý edit, kênh, gửi ẩn danh hoặc topic. Nhóm có topic cần bổ sung định tuyến trước khi sử dụng.
- Tin thường đến chậm hơn 5 phút không tự tạo CO. Link Telegram không tự đổi tài khoản đã liên kết.
- Nội dung webhook đã xử lý được xóa ngay; update chưa xử lý hết 24 giờ được bỏ nội dung và dừng phát lại. Biên nhận gửi/nhận lưu tối đa 30 ngày, liên kết tài khoản giữ cho đến khi quản trị thu hồi có kiểm soát.
- Gửi kết quả bị lỗi được thử lại với backoff, tôn trọng `retry_after`. Các đoạn gửi thành công có biên nhận để không gửi lặp. Telegram không có idempotency key cho sendMessage: nếu mạng ngắt sau khi Telegram nhận nhưng trước khi có phản hồi, tin trả lời có thể lặp; việc này không tạo CO lần nữa.

## Quay lại LINE

Đặt `CO_INTAKE_TRANSPORT=line` để nhận yêu cầu mới trên LINE. Giữ `TELEGRAM_ENABLED=1` đến khi các yêu cầu đã nhận trên Telegram trả kết quả xong. Không xóa hàng chờ hay yêu cầu chưa rõ kết quả khi đổi kênh.

Kiểm thử độc lập, không gọi Telegram/MWG thật:

```sh
python -m unittest bao_tri.kiem_thu.test_telegram_bridge -v
python -m unittest discover -s bao_tri/kiem_thu -q
```

Tài liệu gốc: [Telegram Bot API](https://core.telegram.org/bots/api), [Privacy Mode](https://core.telegram.org/bots/features#privacy-mode).
