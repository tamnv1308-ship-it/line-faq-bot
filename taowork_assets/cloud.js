"use strict";
(()=>{
 function route(){const selected=location.hash==='#revenue'?'revenue':'home';for(const key of ['home','revenue'])document.getElementById('page-'+key).hidden=key!==selected;for(const link of document.querySelectorAll('[data-page]'))link.setAttribute('aria-current',link.dataset.page===selected?'page':'false');}
 route();window.addEventListener('hashchange',route);
 async function state(){try{const r=await fetch('/tao/dashboard/api/status',{cache:'no-store'});if(r.status===401){document.getElementById('cloud-status').textContent='Đăng nhập Công cụ Táo bằng LINE rồi mở lại báo cáo.';return;}if(!r.ok)throw Error();const d=await r.json(),age=Date.now()-Date.parse(d.received_at);document.getElementById('cloud-status').textContent=(age>10*60000?'Dữ liệu đồng bộ đã cũ · ':'Đã đồng bộ · ')+new Date(d.received_at).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'})+' · Số chốt '+d.cutoff;}catch{document.getElementById('cloud-status').textContent='Chưa có bản đồng bộ hợp lệ. Giữ Mac mini hoạt động để cập nhật.';}}
 state();setInterval(()=>{if(!document.hidden)state();},60000);
})();
