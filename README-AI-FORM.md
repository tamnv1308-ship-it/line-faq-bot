# Hỗ trợ sửa form Telegram bằng OpenAI

Tính năng chỉ gợi ý sửa form sai. Không tự gửi yêu cầu CO, xác nhận, hủy, nhận job, tạo CO, sửa quyền, reset hoặc reload MWG. Giữ nguyên parser cho form hợp lệ và bước xác nhận 1 phút.

## Cấu hình máy chủ Render

- `OPENAI_API_KEY`: khóa dự án OpenAI, lưu trực tiếp trong Environment/Secret của Render. Không đưa vào mã nguồn, chat hoặc log.
- `AI_FORM_ASSIST_ENABLED=1`: bật sau khi kiểm tra khóa và số dư API. Mặc định tắt khi thiếu biến này hoặc thiếu khóa.
- `OPENAI_FORM_MODEL=gpt-4.1-mini`: mô hình mặc định, dùng Responses API với Structured Outputs. Nếu đổi mô hình phải kiểm tra tương thích schema và hạn mức trước.

Khóa cục bộ `.env.local` không tự được tải lên Render. `.gitignore` loại file này khỏi Git. Không chép khóa vào README hoặc file triển khai. ChatGPT và OpenAI API có hệ thống thanh toán riêng.

## Cách hoạt động

1. Tin nhắn qua kiểm tra nhóm/người gửi hiện có.
2. Form hợp lệ đi thẳng vào luồng CO hiện tại, không gọi AI.
3. Nếu parser từ chối form, bot trả lỗi ngay và có thể xếp một tác vụ hỗ trợ riêng.
4. Chỉ các mã kho, mã sản phẩm, số lượng, trạng thái đã trích được gửi tới OpenAI; không gửi lịch sử chat, danh tính người gửi, ghi chú liên hệ, IMEI, barcode, token hay URL. Trường chưa rõ gửi giá trị null. `store=false` cho Responses API; điều này không thay thế chính sách lưu dữ liệu vận hành của OpenAI.
5. Mô hình chỉ chọn ID tham chiếu của trường có sẵn. Server từ chối nếu AI tạo ID, đổi loại trường, dùng lặp, bỏ trường hoặc xếp chéo các dòng.
6. Bot dựng bản nháp theo mẫu cố định; mã sản phẩm không đủ 13 số phải bổ sung, không tự thêm số 0. Chỉ mặc định SL=1/trạng thái Mới khi trường thực sự vắng mặt.
7. Người gửi kiểm tra, giữ đủ ghi chú và gửi lại phần form. Form sửa vẫn qua toàn bộ kiểm tra shop, trùng, khóa, quyền và xác nhận trước khi tạo CO.

Đây là hỗ trợ trình bày/bổ sung form, không phải chẩn đoán hay tự sửa hệ thống MWG. Form quá dài, không tách rõ, hoặc không nhận diện được trường sẽ giữ thông báo lỗi hiện có.

## Giới hạn và sự cố

- Tối đa 100 lượt hỗ trợ/24 giờ cho toàn bot; mỗi người 1 lượt/30 giây; tối đa 5 tác vụ chờ.
- Tối đa 7 dòng, 35 trường, 10.000 ký tự đầu vào; 1.200 output token mỗi lần.
- API timeout 8 giây; không gọi lại tự động. Mất tiến trình sau khi gọi cũng không gửi lại API để tránh tính phí lặp.
- Scheduler AI riêng, không giữ khóa DB trong lúc gọi mạng; không chặn tiếp nhận Telegram hoặc worker MWG.
- Hết số dư/khóa sai/giới hạn truy cập/lỗi mạng: tạm ngừng gọi AI 5 phút trong tiến trình, báo không có gợi ý; CO không bị khóa theo AI.
- Kết quả gửi Telegram có cơ chế retry riêng, tối đa 3 lượt, không gọi lại AI. Tác vụ hết hạn 3 phút, xóa nội dung sau khi gửi/hết hạn; metadata phục vụ giới hạn được xóa sau 24 giờ.
- Tắt nhanh bằng `AI_FORM_ASSIST_ENABLED=0` và triển khai lại máy chủ; không cần khởi động lại Chrome/Mac.

## Kiểm thử

`python -m unittest bao_tri.kiem_thu.test_form_assist -q`

Các kiểm tra dùng DB tạm, Telegram giả lập và OpenAI giả lập: không tạo CO thật. Trước khi bật cần một kiểm tra OpenAI thật có số dư; không gửi form thử vào nhóm hay bấm Xác nhận/Tạo CO.

Tài liệu: https://developers.openai.com/api/docs/guides/structured-outputs
