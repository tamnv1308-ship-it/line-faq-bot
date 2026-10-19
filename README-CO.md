# Tạo CO từ LINE với máy Mac

## Trạng thái MWG và điều khiển Mac (2026-10-13)

Máy chủ kiểm tra cả heartbeat và tiến độ giao diện. Worker gửi `health.state` và `health.progress_age_seconds` trong heartbeat/claim. Heartbeat còn mới nhưng tiến độ không đổi quá 60 giây được hiển thị là bị kẹt và tạm ngừng nhận yêu cầu. Worker cũ chỉ gửi online được hiển thị chưa kiểm tra MWG, không được nhận CO cho đến khi cập nhật. Các trạng thái đăng nhập, tải trang, kết nối lại và đang dừng cũng ngừng nhận. Worker đang xử lý bình thường hoặc giữ bản xác nhận vẫn cho gom yêu cầu theo quy tắc cũ. `!bot status` và `/co/worker/status` hiển thị trạng thái thực và cờ accepting; chỉ huy hiệu online không chứng minh MWG sẵn sàng.

Hủy/hết hạn bản xác nhận vẫn giải phóng bản nhập kể cả MWG chưa sẵn sàng. Không phạt người gửi khi hết hạn trong lúc MWG không hoạt động. Các kết quả chưa rõ vẫn giữ để đối soát, không tạo lại CO.

Trên bản Mac đã cài: `Bat-BOT.command` mở một phiên; `Tat-BOT.command` gửi yêu cầu dừng đúng phiên bằng UUID; `Kiem-tra-BOT.command` hiển thị trạng thái. Dừng chờ thao tác hiện tại, lưu kết quả và đóng Chrome của bot, không đụng Chrome cá nhân. Nếu gửi kết quả đang lỗi mạng thì giữ file kết quả để gửi lại, không tạo lại. Khóa hệ thống được giữ đến khi trình duyệt và heartbeat dừng. Worker chặn mở hai phiên; yêu cầu dừng cũ không tác động phiên mới.

Sau khi chọn thương hiệu cho một yêu cầu, ô trạng thái có riêng tối đa 7 giây để xuất hiện ổn định; tối đa 5 lượt. Riêng khi bot rảnh mà trang chưa sẵn sàng, chờ 15 giây trước lượt phục hồi đầu và giữa các lượt, tối đa 5 lượt cho mỗi đợt lỗi. Sau lượt cuối, cho trang thêm 15 giây để trả dữ liệu rồi báo cần kiểm tra nếu vẫn chưa sẵn sàng; không tự lặp thêm một đợt hoặc chờ 5 phút để thử lại. Kết nối dữ liệu còn chờ chỉ được kiểm tra, không reload. Trạng thái sẵn sàng thực sự hoặc một workspace mới mới bắt đầu lại ngân sách phục hồi. Không phục hồi bằng reload khi đang giữ bản xác nhận, đã xác nhận chờ tạo, đang tạo CO hoặc còn kết quả chưa rõ trên trang. Giữ quy tắc reload 5 phút khi rảnh và trang sẵn sàng. Các file worker trên Mac dùng môi trường riêng; deploy Render không tự thay chương trình Mac đang chạy.

Trang tạo CO đã kết thúc phản hồi nhưng chưa đối chiếu được kết quả được lưu bằng chứng tại `.co-mac/settled-submissions/` (quyền 600) và ảnh chẩn đoán. Worker đọc lại trạng thái yêu cầu trên máy chủ trước khi thu hồi trang đó; không đổi trạng thái job, không tự hủy, không tạo lại và không gỡ khóa kho xuất + MSP còn `unknown`. Khi chủ bot đã hủy, chỉ chấp nhận đối chiếu nếu kết quả gốc vẫn được giữ nguyên. Trang cũ đã xử lý xong được thu hồi để không chiếm mãi giới hạn 3 trang đối soát. Trang vẫn có request đang chạy, chưa quan sát được request tạo CO, hoặc còn kết quả chưa gửi phải giữ nguyên. Nếu cả 3 trang cũ vẫn thực sự chờ phản hồi, tiếp tục chặn an toàn thay vì mở vô hạn. Các khóa riêng trong `reconciliation-holds.json` vẫn được giữ nguyên qua cập nhật và khởi động lại.

Sau một lần bấm Tạo CO, worker chờ tối đa 30 giây để đọc mã CO hoặc lỗi xác định từ phản hồi MWG/bảng kết quả. Có kết quả sớm thì trả ngay. Trong thời gian này không reload, không đổi trang và không bấm tạo lại. Sau 30 giây chưa rõ kết quả thì giữ quy trình đối soát hiện tại, không coi là đã hủy CO. Mốc phục hồi khi bot rảnh vẫn là 15 giây; hiệu lực xác nhận vẫn giữ nguyên.

Mốc 30 giây lấy từ sự kiện click thật trên nút Tạo CO trong trình duyệt, không tính thời gian chuẩn bị file, gửi trạng thái máy chủ hoặc chờ nút sẵn sàng. Nếu không đọc được mốc click thì dùng thời điểm quan sát POST tạo CO; trường hợp không quan sát được cả hai dùng lúc thao tác click trả về để không tính sớm. Có kết quả trong lúc thao tác click còn chờ thì vẫn đọc kết quả trước khi xét hết giờ. Hết 30 giây không phải lệnh reload: trang còn kết nối dữ liệu, lớp Loading hoặc không đọc được trạng thái vẫn được giữ nguyên; chỉ trang đã hết tải và lưu đủ bằng chứng mới được thu hồi.

Phản hồi tạo CO được ghi riêng theo yêu cầu tại `.co-mac/diagnostics/<id>-create-response.json`, quyền 600. Chỉ lưu mã HTTP, loại dữ liệu, cờ Success nếu là boolean, số dòng và mã lỗi cố định; không lưu body, Message, ghi chú, token hay cookie. `Data=null`, thiếu Data, sai định dạng, dòng không khớp và lỗi đọc JSON có thông báo riêng. HTTP 200 hoặc Success=true với Data rỗng vẫn là chưa rõ kết quả; không tự chuyển thành đã hủy/thất bại, không gửi lại CO và không bỏ khóa đối soát.

## Đối soát kết quả bị từ chối (2026-10-13)

API `POST /co/worker/result-status` yêu cầu worker token, nhận ID và lease để đọc trạng thái/kết quả hiện tại cùng cờ so khớp lease. Endpoint không sửa trạng thái, không trả token và không tạo CO. `/co/worker/status` trả đúng cờ bật/tắt, độ mới heartbeat và phiên bản đối soát.

Bản Mac đang cài phân biệt lỗi mạng có thể thử lại với lỗi HTTP 409. Sau 409, chỉ lỗi được ghi rõ xảy ra trước bước tạo CO mới được lưu vào `.co-mac/result-conflicts/` và giải phóng nếu máy chủ đã kết thúc yêu cầu ở trạng thái failed/cancelled/expired, không có mã CO. Kết quả thành công, chưa rõ, đang tạo hoặc thiếu bằng chứng được giữ nguyên để đối soát; không gửi lại thao tác tạo. Các lỗi HTTP cố định không còn bị gửi lặp vô hạn. Bản Mac dùng thư mục và môi trường riêng; cập nhật phần máy chủ không tự thay worker đang mở trên Mac.

## Danh mục Shop và cảnh báo cùng cụm (2026-10-13)

Danh mục được cập nhật từ sheet Chi Tiết và Cụm của file người dùng cung cấp. Chi Tiết dùng mã chi nhánh cột C, tên kho D, vùng A, phường H, tỉnh mới I và giữ tỉnh cũ L để truy vết. Bỏ qua các vùng ngoài 8 vùng hiện có, gồm An Khang/AvaWorld. Sheet Cụm: MST cột C và ST Base cột F đều có quan hệ trực tiếp với cụm cột E. Chữ hoa/thường trong tên cụm được chuẩn hóa; một base có thể tham gia nhiều quan hệ, không suy diễn ghép cụm bắc cầu.

Phần Điều kiện luôn hiển thị Cụm: `✅ Cùng cụm: <tên cụm>` khi có cụm chung, `❌ Khác cụm` khi hai kho có dữ liệu nhưng không chung cụm. Nếu thiếu danh mục, ghi `❌ Cụm: Chưa có dữ liệu` thay vì kết luận khác cụm. Cùng vùng dùng ✅, Khác vùng dùng ❌; dữ liệu chưa rõ được ghi rõ thay vì suy diễn. Đây là thông tin cảnh báo để người gửi xem trước, không chặn tạo CO hay sửa Note/Excel. Tổng kết dùng cùng danh mục mới.

Dữ liệu shop không đưa vào GitHub công khai. `import_store_directory.py --file <file.xlsx> --output <private.json>` chỉ đọc workbook và xuất JSON chuẩn hóa. `POST /co/worker/store-directory` yêu cầu worker authentication, kiểm tra giới hạn/cấu trúc và lưu nguyên tử trên persistent disk, giữ một bản trước để khôi phục. `GET` cùng đường dẫn chỉ trả nguồn, checksum và số lượng; không trả danh sách. File override được ưu tiên hơn cấu hình ZLIB cũ và tự cập nhật cache khi thay đổi, nên không cần khởi động lại Mac.


## Quá hạn xác nhận và mở khóa (2026-10-13)

Hiệu lực là 1 phút từ khi LINE nhận bản xác nhận. Quá hạn thì yêu cầu tự hủy trước khi tạo CO và Mac chuyển sang yêu cầu tiếp theo. Với bản xác nhận mới đã báo quy tắc, mỗi lần quá hạn tính một lần cho người gửi (một bản gộp nhiều dòng vẫn tính một lần): lần 1 khóa nhận yêu cầu mới 1 phút; lần 2 khóa 3 phút; lần 3 khóa đến khi chủ bot Tâm mở lại. Hết thời gian khóa 1/3 phút không reset số lần. Tâm được miễn khóa. Không tính vi phạm cho bản chưa gửi được, bản trước khi áp dụng quy tắc, người chủ động Hủy, hoặc khi bot đang offline/tạm dừng lúc kiểm tra hết hạn.

Chỉ User ID của chủ bot Tâm dùng được `!mokhoa` để xem danh sách hiện bị khóa, rồi `!mokhoa 2` để mở người ở số 2. Lựa chọn có hiệu lực 5 phút và gắn với đúng sự kiện khóa; danh sách thay đổi không làm số thứ tự trỏ sang người khác. Mở khóa reset số lần về 0. Danh sách tối đa 50 người; sau khi mở, gửi `!mokhoa` để làm mới. Webhook gửi lại không mở thêm người khác. Xác nhận đúng hạn và yêu cầu đã bắt đầu tạo CO được xử lý theo quy tắc hiện tại.


## Gom tin nhắn trong 10 giây (2026-10-12)

Mặc định `CO_GATHER_SECONDS=10`: từ lúc nhận tin đầu, bot đợi một cửa sổ cố định 10 giây và gom các tin hợp lệ của cùng người gửi, cùng cuộc chat, cùng trạng thái sản phẩm. Tin tiếp theo không kéo dài cửa sổ. Mỗi file tối đa 7 dòng; một tin có nhiều dòng được giữ nguyên, không chia nhỏ để lấp chỗ trống. Tin vượt giới hạn hoặc đến sau cửa sổ sẽ thành yêu cầu riêng. Có thể đặt `CO_GATHER_SECONDS=0` để trở lại xử lý từng tin ngay.

Sau cửa sổ, Mac nhập một file và gửi một bản xác nhận chung. Xác nhận/Hủy áp dụng toàn bộ các dòng trong bản đó, chỉ người gửi hoặc chủ bot được thao tác theo quyền hiện có. Hiệu lực vẫn là 1 phút từ khi bản xác nhận được gửi thành công. Khi xác nhận, bot dùng bảng đã nhập để tạo CO, không reload hoặc nhập lại chỉ vì đã gom tin. Kết quả liệt kê từng dòng cùng mã CO/lỗi.

Chống trùng, chặn kho nhận và quy tắc trạng thái chưa rõ kết quả vẫn áp dụng trước khi nhận thêm dòng. Tin đã nhận lại do LINE gửi lại không được thêm lần hai. Tổng kết vẫn đếm đủ số tin yêu cầu ban đầu. Dữ liệu ánh xạ tin gom được dọn cùng lịch sử sau 30 ngày và giữ dấu chống xử lý lại.

Thay đổi nằm ở `co_flow.py`, `co_summary.py`, `co_summary_view.py`; worker Mac hiện tại đã hỗ trợ file nhiều dòng. Kiểm thử: `python -m unittest test_gather test_preview_reply` và `python -m unittest discover`. Các phần bên dưới mô tả những phiên bản trước; mục này là quy tắc gom tin mới nhất.


## Xem giá Apple trong NOTE

`!gia` trả báo cáo so sánh MW/FPT/CellphoneS từ lượt quét KDBT đầy đủ gần nhất trên Mac bằng thẻ LINE Flex: mỗi sản phẩm một thẻ, vuốt ngang để xem và bấm Trang trước/Trang tiếp. `!gia 2` vẫn xem trang tiếp theo; `!gia air m5` tìm theo tên. Mỗi trang tối đa 10 sản phẩm. Giá đối thủ thấp hơn MW tô đỏ, bằng giá màu vàng, cao hơn màu xanh; luôn có chữ chỉ rõ chênh lệch. Giá chưa xác minh không hiển thị; luôn ghi thời điểm quét và cảnh báo khi bản quét quá 18 giờ. Thông báo không có dữ liệu/tìm kiếm không khớp vẫn trả chữ ngắn. Thẻ được gửi bằng Reply API; không gửi lại bằng Push hoặc tin khác nếu yêu cầu gửi thẻ thất bại.

Lệnh chỉ xử lý trong group NOTE đã xác minh ID/tên và dùng Reply API ngay trong webhook. Không tự quét website trong webhook, không chuyển sang Push khi trả lời thất bại. Mac đồng bộ snapshot qua `PUT /price/report`, dùng khóa HMAC riêng suy ra từ `CO_WORKER_TOKEN` với nhãn `apple-price-report-sync:v1`. Khóa này không có quyền gọi API worker CO. Dữ liệu lưu trong hai bảng `price_reply_snapshot` và `price_reply_events` của DB bền vững hiện có. `GET /price/status` yêu cầu cùng khóa, dùng kiểm tra đồng bộ và lần trả lời thành công gần nhất. Snapshot cũ/không đầy đủ/mâu thuẫn bị từ chối.

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
# Hộp thoại và tình trạng điều khiển Chrome

- Một bộ xử lý hộp thoại tồn tại suốt phiên Chrome, bao gồm trang CO đang được giữ để đối soát. Thông báo đến muộn vẫn được xử lý; mỗi hộp thoại chỉ xử lý một lần. Chỉ chấp nhận thông báo `alert`; không đồng ý hộp thoại xác nhận, nhập liệu hay rời trang. Lỗi hộp thoại đã đóng được ghi bằng mã lỗi, không ghi nội dung tin nhắn vào log.
- Heartbeat kiểm tra tiến trình driver thuộc đúng worker qua thông tin hệ điều hành, không gọi Playwright từ luồng nền. Driver mất kết nối/không xác minh được báo `driver_error`; vòng điều khiển không có tiến triển hơn 60 giây báo `control_stalled`. Heartbeat tự chạy không được làm mới mốc tiến triển.
- 60 giây là ngưỡng phát hiện bộ điều khiển ngừng phản hồi, không phải thời gian chờ tạo CO. Thời gian nhận kết quả CO vẫn 30 giây tính từ click thật. Khi MWG chậm nhưng vòng điều khiển vẫn phản hồi, bot vẫn phân biệt là đang chờ MWG.
- Các kiểm tra này chỉ báo tình trạng và ngăn nhận thêm khi bộ điều khiển lỗi; không tự đóng/reload trang, reset, hủy yêu cầu, phát sinh CO hoặc tạo lại lệnh chưa rõ kết quả. Quy tắc không reload khi chờ xác nhận/đang tạo CO giữ nguyên.

