# TáoWork chạy độc lập trên Render

Dùng repository và service line-faq-bot hiện có. Dashboard `/tao/dashboard/` đăng nhập bằng tài khoản/mật khẩu TáoWork riêng, không dùng LINE. Cookie `__Host-taowork_session` tách hoàn toàn khỏi cổng CO. Hash scrypt của tài khoản đã có được chuyển một lần qua endpoint khởi tạo có bearer xác thực; không đưa tài khoản, mật khẩu, hash, session MWG, cấu hình Telegram hoặc số liệu lên Git. Không có trang đăng ký/reset mật khẩu công khai.

Bản cloud gồm Tổng quan, Doanh thu, lấy số trực tiếp API MWG, dựng ba ảnh theo bố cục đã duyệt và gửi Telegram theo yêu cầu. Không có bước đổ tồn kho hoặc chọn/upload file trong giao diện. Không gọi về Mac, không mở Excel/VBA/launchd, không dùng Playwright để lấy số. File xuất API chỉ là đầu vào nội bộ của tác vụ cloud. API nhập dữ liệu khởi tạo chỉ dành cho cutover, bị khóa khi runtime đã bật.

Dữ liệu, account và runtime nằm tại `/var/data/taowork` trên ổ Render đã có. Lịch sử được gom theo ngày/ngành/model/trạng thái/chuỗi, giữ Decimal và các nguồn coverage được chọn. Đã đối chiếu 93.718 trường số với nguồn Dashboard trước khi chuyển. Calendar, target, từ điển tên sản phẩm, font Noto Sans theo SIL OFL và snapshot theo giờ chuyển riêng, không nằm trong repo công khai.

`taowork_runtime.py` chạy tác vụ bằng subprocess có khóa riêng; lịch sử actions có mã chống trùng và bảo toàn trạng thái chưa rõ kết quả sau restart. Không tự gửi lại Telegram. Trạng thái gửi thành công không bị đổi thành lỗi chỉ vì bước công bố dữ liệu sau đó lỗi. Các lượt chuyển đổi/kiểm thử chỉ dùng probe và dry-run; dry-run lấy số và dựng ảnh thật nhưng không gọi gửi ảnh.

Kích hoạt chỉ sau khi account, dữ liệu, phiên MWG, đích Telegram, ảnh báo cáo và số liệu được kiểm chứng trên Render. Khi đổi máy chạy phải khóa runner Mac, lưu DB/cursor/receipt, tắt listener/schedule báo cáo Mac rồi chuyển phiên MWG mới nhất và bật cloud. Nếu chưa xác minh được cloud thì chưa dừng Mac. Không tác động worker CO, hàng chờ/holds hoặc các bot khác; những hệ thống đó có phạm vi vận hành riêng.

Background tick chạy trong service hiện có (`RENDER=true`), chỉ bật khi runtime-enabled.json đã được ghi sau nghiệm thu. Giữ cấu hình báo cáo theo yêu cầu, không tự bật lịch gửi. Tick giữ phiên MWG theo grant chuẩn và đọc lệnh Telegram mới với cursor đã chuyển, đồng thời cập nhật lịch sử bằng API. MWG có thể thu hồi phiên theo chính sách của họ; khi đó giữ số thành công gần nhất, báo cần xác thực lại, không kéo dài phiên hay bỏ qua xác thực. Việc đăng nhập lại MWG không được coi là phụ thuộc bắt buộc vào Mac mini.

GitHub CI kiểm tra đăng nhập TáoWork, migration, CSRF, chặn LINE cookie, chống trùng/unknown, báo cáo/API MWG và hồi quy CO. Render auto-deploy sau khi CI đạt. Các nút gửi báo cáo cần phiên TáoWork và CSRF; endpoint khởi tạo đòi worker identity hiện có. Các route CO/LINE hiện hành và session của chúng được giữ riêng.
