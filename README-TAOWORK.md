# TáoWork trong line-faq-bot

Dashboard mở tại `/tao/dashboard/`, từ liên kết Báo cáo Apple trên trang chủ Công cụ Táo. Dùng phiên LINE hiện có, chỉ `PRIVATE_CO_OWNER` được đọc HTML, assets và API. Không đổi phiên, quyền CO, lệnh xác nhận/hủy, các hàng chờ hoặc worker MWG.

`taowork_assets/` chỉ chứa giao diện Tổng quan và Doanh thu được tách từ bản Dashboard Mac ngày 02/11/2026. Không chứa số liệu bán hàng, workbook, revenue-snapshot.json hay các khối dữ liệu nhúng. Repository hiện công khai, nên chỉ cập nhật danh sách file đã kiểm tra, không dùng `git add .` với bản Mac.

Mac gửi bản tổng hợp JSON tới `/tao/dashboard/api/snapshot` bằng kết nối worker hiện có. Endpoint chỉ nhận snapshot; không chạy BOT, gửi Telegram, tạo CO, hoặc thay lịch. Không gửi token vào URL, không chuyển tiếp khi redirect. Snapshot được ghi nguyên tử, quyền 600, tại `/var/data/taowork/snapshot.json.gz` trên ổ đĩa Render đã có. Bản cũ hơn hoặc sai schema/đơn vị bị từ chối, giữ lần thành công trước. Có thể cấu hình `TAOWORK_DATA_DIR` tuyệt đối khi thử độc lập.

Chạy `taowork_sync.py --dashboard <thư mục Dashboard>` bằng runtime của Dashboard cho một lần đồng bộ. Khi cài `taowork_sync.py` vào `scripts/` của Dashboard, `start(dashboard_root)` chỉ tạo vòng đồng bộ đọc báo cáo nếu `.automation/cloud-sync.json` có `enabled: true`. Không ghi token vào cấu hình mới; đọc hai khóa kết nối từ bản LINE Mac hiện có. Phần này chỉ đồng bộ Tổng quan/Doanh thu; dữ liệu tồn kho, dò giá, MWG/Excel VBA và các lệnh BOT vẫn ở Mac. Không tắt Mac sau khi Dashboard cloud hoạt động.

Doanh thu/SP giữ đơn vị triệu/SP. Bảng tháng lấy trực tiếp API snapshot đã đồng bộ, không đóng gói fallback cũ 26/10; ghi rõ nguồn/chốt và thời điểm đồng bộ. Response dữ liệu hỗ trợ gzip. Chưa khẳng định đã chuyển Telegram renderer, báo cáo ảnh hoặc MWG lên cloud.

Kiểm thử: bộ PortalTests hiện có; test_taowork_dashboard dùng phiên đăng nhập LINE mô phỏng và dữ liệu tổng hợp giả, chặn người chưa đăng nhập/thành viên, giữ số cũ khi bản gửi lỗi/cũ, xác minh không thay jobs CO. Kiểm tra trình duyệt bằng server thử cổng riêng; không dùng server thử làm production. Render giữ `gunicorn app:app`, DB và đĩa hiện có. Sau deploy phải kiểm tra health, worker readiness, trạng thái jobs/holds, anonymous 401, receipt hash và API owner trước khi khẳng định hoàn tất chuyển đổi.
