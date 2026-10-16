/* Công cụ Táo: all authorization and queue transitions remain server-side. */
(() => {
  'use strict';
  const main=document.getElementById('main'), nav=document.getElementById('nav');
  const notice=document.getElementById('notice'), progress=document.getElementById('progress');
  const state={page:'home',me:null,jobs:[],filter:'active',period:'today',offset:0,more:false,job:null,search:'',lookup:null,conditions:null,summary:null,locks:[],queueOverview:null,cancelPreview:null,unknownReview:null,unknownChecked:false,busy:false,clock:0};
  let activeRefresh=0, serial=0, timer=null, liffReady=false, config=null;
  const paths={search:'m21 21-5-5M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16',
    home:'m3 10 9-7 9 7v10H3ZM9 20v-7h6v7',layers:'m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 17l10 5 10-5',
    check:'m5 12 4 4L19 6',arrow:'M4 12h16m-6-6 6 6-6 6',back:'M20 12H4m6-6-6 6 6 6',right:'m9 5 7 7-7 7',
    chart:'M4 20V10m8 10V4m8 16v-7',shield:'m12 3 9 4v6c0 5-9 9-9 9s-9-4-9-9V7Zm-4 9 3 3 5-6',
    clock:'M12 8v5l3 2M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
    settings:'M4 7h16M4 17h16M8 4v6m8 4v6',x:'m6 6 12 12M6 18 18 6',
    warehouse:'m3 8 9-5 9 5v13H3ZM7 21V11h10v10M7 16h10',
    lock:'M6 10h12v11H6ZM8 10V6a4 4 0 0 1 8 0v4',refresh:'M20 8a8 8 0 1 0 1 7M20 3v5h-5',
    box:'m12 3 9 5v9l-9 5-9-5V8Zm-9 5 9 5 9-5M12 13v9'};
  const icon=n=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[n]||paths.box}"/></svg>`;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short=v=>String(v||'').replace(/^Điện thoại\s+/i,'');
  const number=v=>Number(v||0).toLocaleString('vi-VN');
  const date=v=>new Date(v*1000).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'});
  function error(message){notice.textContent=message;notice.hidden=!message;}
  async function api(path,options={}){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch('/tao/api/'+path,{...options,credentials:'same-origin',cache:'no-store',signal:controller.signal,
        headers:{...(options.body?{'Content-Type':'application/json','X-Tao-CSRF':state.me?.csrf||''}:{}),...(options.headers||{})}});
      const data=await response.json();
      if(!response.ok){const e=new Error(data.error||'Chưa thực hiện được thao tác.');e.status=response.status;throw e;}
      if(data.server_time)state.clock=data.server_time*1000-Date.now();
      return data;
    }catch(e){
      if(e.name==='AbortError')throw new Error(options.method==='POST'?'Chưa nhận được phản hồi. Hãy tải lại để kiểm tra kết quả trước khi thao tác tiếp.':'Kết nối chậm. Vui lòng thử lại.');
      throw e;
    }finally{clearTimeout(timeout);}
  }
  function loading(value){progress.hidden=!value;document.getElementById('refresh').disabled=value;}
  function title(text,sub=''){return `<div class="tao-page-heading"><button class="tao-back" data-go="home" aria-label="Về trang chủ">${icon('back')}</button><div><h1>${esc(text)}</h1>${sub?`<p class="tao-subtitle">${esc(sub)}</p>`:''}</div></div>`;}
  function badge(job){const style=job.state==='succeeded'?'success':['failed','unknown'].includes(job.state)?'danger':['cancelled','expired'].includes(job.state)?'neutral':'';return `<span class="tao-badge ${style}">${icon(job.state==='draft'?'clock':job.state==='succeeded'?'check':'box')}${esc(job.label)}</span>`;}
  function jobCard(job){
    const row=job.rows[0]||{};
    return `<button class="tao-order" data-job="${esc(job.id)}"><div class="tao-order-top"><span>#${esc(job.id)}</span>${badge(job)}</div><div class="tao-route">${esc(row.source)} ${icon('arrow')} ${esc(row.destination)}</div><p class="tao-product">${esc(short(row.product_name)||'Đang lấy tên sản phẩm từ MWG')}</p>${job.rows.length>1?`<p class="tao-subtitle">+ ${job.rows.length-1} dòng khác</p>`:''}<div class="tao-order-foot"><span>${esc(job.requester)} · ${job.rows.length>1?job.rows.length+' dòng':'SL '+row.quantity}</span><b>${job.can_confirm?'Xác nhận':'Chi tiết'} ${icon('right')}</b></div></button>`;
  }
  function navigation(){
    const active=state.page==='detail'?'queue':['report','conditions'].includes(state.page)?'home':state.page;
    nav.innerHTML=[['home','home','Trang chủ'],['queue','layers','Yêu cầu'],['lookup','search','Tra cứu'],...(state.me.admin?[['admin','settings','Quản lý']]:[])].map(([p,i,t])=>`<button data-go="${p}" ${active===p?'aria-current="page"':''}>${icon(i)}${t}</button>`).join('');
    nav.hidden=false;
    nav.classList.toggle('tao-nav-admin',state.me.admin);
  }
  function home(){
    const me=state.me,health=me.health;
    const tools=[['lookup','search','Tra cứu CO','Tìm nhanh kết quả'],['queue','layers','Yêu cầu',me.owner?'Quản lý các yêu cầu':'Các yêu cầu của bạn'],['conditions','shield','Điều kiện SP','Kiểm tra từ Sheet DATA'],...(me.owner?[['report','chart','Tổng kết','Hôm nay · 7 · 30 ngày']]:[])];
    return `<div class="tao-greeting"><div><div class="tao-kicker">Công cụ Táo</div><h1>Chào ${esc(me.owner?'Tâm':me.name)} 👋</h1><p class="tao-subtitle">Mọi việc gọn trong một chỗ.</p></div><span class="tao-avatar">${esc(me.name.trim().charAt(0).toUpperCase())}</span></div><div class="tao-live"><b class="${health.mwg_ready?'':'not-ready'}"><span class="tao-dot"></span>${esc(health.worker_label)}</b><span>${me.enabled?'Nhận CO theo quyền hiện tại':'Chỉ Tâm được tạo CO'}</span></div>${me.notice?`<div class="tao-info-card tao-long-text">${esc(me.notice)}</div>`:''}<div class="tao-grid">${tools.map(([p,i,t,d],n)=>`<button class="tao-tool ${n===0?'tao-tool-featured':''}" data-go="${p}"><span class="tao-tool-icon">${icon(i)}</span><strong>${t}</strong><small>${d}</small></button>`).join('')}</div><div class="tao-section-heading"><h2>Yêu cầu đang xử lý</h2><button class="tao-link" data-go="queue">Xem tất cả ${icon('arrow')}</button></div>${state.jobs.length?state.jobs.slice(0,2).map(jobCard).join(''):'<div class="tao-info-card tao-empty">Không có yêu cầu đang chờ.</div>'}${me.admin?`<button class="tao-admin-entry" data-go="admin">${icon('shield')}<span>${me.owner?'Quản lý của Tâm':'Quản lý ADM'}<small>${me.owner?'Bật/tắt bot · Mở khóa · Hàng chờ':'Bật/tắt nhận CO · Trạng thái bot'}</small></span>${icon('right')}</button>`:''}`;
  }
  function bulkCancelCard(){
    if(!state.me.owner)return '';
    const q=state.queueOverview,review=state.cancelPreview;
    if(review)return `<section class="tao-info-card" aria-label="Xác nhận hủy hàng chờ"><h2>Hủy ${number(review.waiting)} yêu cầu đang chờ?</h2><p class="tao-product">Áp dụng cho tất cả người dùng, trong mọi chat.</p><p class="tao-hint">Lệnh đang xử lý, chưa rõ kết quả và CO đã tạo được giữ nguyên.</p><div class="tao-inline-actions"><button class="tao-secondary" data-action="cancel-back">Quay lại</button><button class="tao-secondary tao-cancel-all" data-action="cancel-waiting-confirm">Đồng ý hủy</button></div></section>`;
    return `<section class="tao-info-card" aria-label="Hủy hàng chờ"><div class="tao-section-heading"><h2>Hàng chờ của mọi người</h2><span class="tao-badge neutral">Chỉ Tâm</span></div>${q?`<div class="tao-queue-counts"><span><b>${number(q.waiting)}</b>Đang chờ</span><span><b>${number(q.processing)}</b>Đang xử lý</span><span><b>${number(q.unknown)}</b>Chưa rõ</span></div>`:'<p class="tao-hint">Đang tải hàng chờ…</p>'}<p class="tao-hint">Hủy yêu cầu chờ nhập file, chờ xác nhận và chờ tạo CO trong mọi chat. Giữ nguyên lệnh đang xử lý, chưa rõ kết quả và CO đã tạo.</p><button class="tao-secondary tao-cancel-all" data-action="cancel-waiting" ${!q?.waiting?'disabled':''}>${icon('x')}Hủy tất cả hàng chờ${q?.waiting?' ('+number(q.waiting)+')':''}</button></section>`;
  }
  function queue(){return title(state.me.owner?'Yêu cầu CO':'Yêu cầu của tôi')+bulkCancelCard()+`<div class="tao-segments tao-queue-filters" aria-label="Lọc yêu cầu">${[['active','Đang xử lý'],...(state.me.owner?[['waiting','Đang chờ'],['attention','Cần kiểm tra']]:[]),['done','Đã xong'],['all','Tất cả']].map(([v,t])=>`<button data-filter="${v}" aria-pressed="${state.filter===v}">${t}</button>`).join('')}</div>${state.filter==='attention'?'<p class="tao-hint">Các yêu cầu chưa rõ kết quả cần đối soát trên MWG trước khi xử lý tiếp.</p>':''}${state.jobs.length?state.jobs.map(jobCard).join(''):'<div class="tao-empty">Chưa có yêu cầu trong mục này.</div>'}${state.more?'<button class="tao-secondary" data-action="more">Xem thêm</button>':''}<p class="tao-refresh">Tự cập nhật khi màn hình đang mở.</p>`;}
  function rowDetails(row,index,total){return `<div class="tao-info-card">${total>1?`<div class="tao-kicker">Dòng ${index+1} / ${total}</div>`:''}<h2 class="tao-detail-title">${esc(short(row.product_name)||'MSP '+row.product+' · MWG chưa trả tên')}</h2>${row.co?`<button class="tao-copy" data-copy="${esc(row.co)}" aria-label="Sao chép mã CO ${esc(row.co)}">${esc(row.co)} · Sao chép</button>`:''}${row.error?`<p class="tao-long-text">${esc(row.error)}</p>`:''}${[['source','Kho xuất'],['destination','Kho nhận']].map(([key,label])=>`<div class="tao-warehouse"><span>${icon('warehouse')}</span><div><small>${label}</small><strong>${esc(row[key+'_name']?String(row[key+'_name']).startsWith(String(row[key]))?row[key+'_name']:row[key]+' - '+row[key+'_name']:row[key])}</strong></div></div>`).join('')}<div class="tao-field"><span>Số lượng</span><b>${esc(row.quantity)}</b></div><div class="tao-field"><span>Trạng thái</span><b>${esc(row.status||'Mới')}</b></div>${row.conditions?.length?`<div class="tao-kicker tao-note">Điều kiện</div>${row.conditions.map(v=>`<div class="tao-condition ${/^(❌|⚠️)/u.test(v)?'bad':''}">${icon(v.startsWith('✅')?'check':/^(❌|⚠️)/u.test(v)?'x':'box')}<span>${esc(v.replace(/^[✅❌⚠️❓]+\s*/u,''))}</span></div>`).join('')}`:''}${row.note?`<div class="tao-note"><b>Note:</b> ${esc(row.note).replace(/\n/g,'<br>')}</div>`:''}</div>`;}
  function unknownCancelCard(job){
    const resolution=job.unknown_resolution;
    if(!state.me.owner||!resolution)return '';
    if(!resolution.can_cancel)return `<div class="tao-info-card tao-long-text">${esc(resolution.reason)}</div>`;
    const review=state.unknownReview;
    if(review?.id===job.id)return `<section class="tao-info-card" aria-label="Xác nhận đã kiểm tra MWG"><div class="tao-kicker">Chỉ Tâm 258330</div><h2>Hủy yêu cầu #${esc(job.id)}?</h2><p class="tao-product">${esc(job.requester)} · ${job.rows.length} dòng. Hủy toàn bộ yêu cầu này và giữ lịch sử đối soát.</p><label class="tao-attestation"><input type="checkbox" data-unknown-check ${state.unknownChecked?'checked':''}><span>Tôi đã kiểm tra MWG và xác nhận <strong>chưa có CO ở tất cả ${job.rows.length} dòng</strong> của yêu cầu này.</span></label><div class="tao-inline-actions"><button class="tao-secondary" data-action="unknown-back">Quay lại</button><button class="tao-secondary tao-cancel-all" data-action="unknown-confirm" ${state.unknownChecked?'':'disabled'}>Xác nhận hủy</button></div></section>`;
    return `<section class="tao-info-card"><div class="tao-kicker">Riêng Tâm 258330</div><h2>Đã kiểm tra MWG?</h2><p class="tao-hint">Chỉ hủy khi em đã kiểm tra và chưa có CO ở tất cả dòng. Bot giữ lại lịch sử và không tự tạo lại yêu cầu.</p><button class="tao-secondary tao-cancel-all" data-action="unknown-review">${icon('x')}Hủy sau khi kiểm tra MWG</button></section>`;
  }
  function detail(){
    const job=state.job;if(!job)return '<div class="tao-empty">Đang tải yêu cầu…</div>';
    const processing=['queued','verified_queued','running','submitting'].includes(job.state);
    return title(job.state==='draft'?'Xác nhận yêu cầu':processing?'Đang tạo CO':'Kết quả yêu cầu','#'+job.id+' · '+job.requester)+`<div class="tao-section-heading">${badge(job)}${job.expires_at?`<span class="tao-badge" data-countdown="${job.expires_at}"></span>`:''}</div>${processing?'<div class="tao-info-card tao-long-text">Đã xác nhận. Kết quả CO sẽ hiện tại đây khi MWG xử lý xong.</div>':''}${job.state==='unknown'?'<div class="tao-info-card tao-long-text">MWG chưa trả đủ kết quả. Cần kiểm tra trên MWG trước khi xử lý tiếp; riêng Tâm có thể hủy sau khi xác nhận chưa có CO.</div>':''}${job.rows.map((r,i)=>rowDetails(r,i,job.rows.length)).join('')}${job.skipped_duplicates?.length?`<div class="tao-info-card">Đã bỏ qua ${job.skipped_duplicates.length} dòng trùng theo quy tắc hiện tại.</div>`:''}${job.skipped_errors?.length?`<div class="tao-info-card">Đã loại ${job.skipped_errors.length} dòng không hợp lệ. Xem tin bot để biết lỗi từng dòng.</div>`:''}${job.can_cancel||job.can_confirm?`<div class="tao-actions">${job.can_cancel?'<button class="tao-secondary" data-action="cancel">Hủy</button>':''}${job.can_confirm?'<button class="tao-primary" data-action="confirm">'+icon('check')+'Xác nhận</button>':''}</div>`:''}${unknownCancelCard(job)}${job.owner_cancelled_at?`<div class="tao-info-card tao-long-text">Tâm đã xác nhận kiểm tra MWG và chưa có CO lúc ${date(job.owner_cancelled_at)}. Đã lưu lịch sử hủy.${job.state!=='cancelled'?' Kết quả mới từ MWG được hiển thị phía trên.':''}</div>`:''}${job.state==='draft'&&!job.expires_at?'<p class="tao-hint">Bot đang gửi thông tin xác nhận về LINE. Vui lòng chờ cập nhật.</p>':''}`;
  }
  function searchForm(kind,label,placeholder){return `<form data-search="${kind}"><label class="tao-label" for="query">${label}</label><div class="tao-search">${icon('search')}<input id="query" name="query" ${kind==='conditions'?'inputmode="numeric" maxlength="13"':''} placeholder="${placeholder}" value="${esc(state.search)}" required autocomplete="off"><button type="submit">Tra cứu</button></div></form>`;}
  function lookup(){return title('Tra cứu CO','Lịch sử 30 ngày gần nhất')+searchForm('lookup','Mã CO hoặc mã yêu cầu','Nhập mã cần tra cứu')+`<p class="tao-hint">Tra CO theo quyền !CO hiện tại. Mã yêu cầu chỉ xem được khi bạn có quyền.</p>${state.lookup?.text?`<div class="tao-info-card tao-long-text">${esc(state.lookup.text)}</div>`:state.lookup?.job?jobCard(state.lookup.job):''}`;}
  function conditions(){const data=state.conditions;return title('Điều kiện sản phẩm','Thông tin tham khảo từ Sheet DATA')+searchForm('conditions','Mã sản phẩm','Nhập đủ 13 chữ số')+`<p class="tao-hint">Bán thường · Chiến giá · Chuyển kho</p>${data?`<div class="tao-info-card"><div class="tao-kicker">MSP ${esc(data.code)}</div>${data.found?data.conditions.map(c=>`<div class="tao-condition ${c.state==='no'?'bad':''}">${icon(c.state==='yes'?'check':c.state==='no'?'x':'box')}<span>${esc(c.label)} · ${esc(c.value)}</span></div>`).join(''):`<p class="tao-product">${esc(data.message)}</p>`}</div>`:''}`;}
  function report(){const s=state.summary;const labels={people:'Top 5 người yêu cầu',source:'Top 5 kho xuất',destination:'Top 5 kho nhận',region:'Top 5 vùng xuất',province:'Top 5 tỉnh/thành xuất',product:'Top 5 sản phẩm'};return title('Tổng kết CO','Riêng Tâm 258330')+`<div class="tao-segments" aria-label="Khoảng thời gian">${[['today','Hôm nay'],['7','7 ngày'],['30','30 ngày']].map(([v,t])=>`<button data-period="${v}" aria-pressed="${state.period===v}">${t}</button>`).join('')}</div>${s?`<p class="tao-hint">${state.period==='today'?'Trong ngày':state.period+' ngày gần nhất'} · Giờ Việt Nam</p><div class="tao-summary">${[['co','CO thành công'],['quantity','Sản phẩm đã chuyển'],['requests','Yêu cầu'],['failed','Dòng lỗi']].map(([v,t])=>`<div class="tao-stat"><strong>${number(s.stats[v])}</strong><span>${t}</span></div>`).join('')}</div>${Object.entries(labels).map(([k,t])=>`<div class="tao-info-card tao-report-list"><div class="tao-section-heading"><h2>${t}</h2><span class="tao-kicker">CO</span></div>${s.top[k].length?s.top[k].map((r,i)=>`<div class="tao-ranking"><span>${i+1}</span><span>${esc(k==='product'?short(r.name):r.name)}</span><b>${number(r.count)}</b></div>`).join(''):'<p class="tao-hint">Chưa có dữ liệu.</p>'}</div>`).join('')}<div class="tao-section-heading"><h2>5 dòng CO gần đây</h2></div>${s.recent.map(r=>`<div class="tao-info-card"><div class="tao-order-top"><span>${esc(r.time)} · ${esc(r.person)}</span><b>${esc(r.state)}</b></div><p class="tao-route">${esc(r.source)} → ${esc(r.destination)}</p><p class="tao-product">${esc(short(r.product))}</p><p>SL ${esc(r.quantity)} · ${esc(r.co)}</p></div>`).join('')}<p class="tao-hint">Số liệu dùng cùng cách tính với lệnh !tongket trên LINE.</p>`:''}`;}
  function admin(){const me=state.me;return title('Quản lý',me.owner?'Tâm 258330 Apple · Chủ bot':'Tài khoản ADM')+`<div class="tao-info-card"><div class="tao-setting"><div><strong>Nhận yêu cầu CO</strong><small>${me.enabled?'Theo quyền hiện tại':'Chỉ Tâm được tạo CO'}</small></div><button class="tao-toggle" role="switch" aria-label="Nhận yêu cầu CO theo quyền hiện tại" aria-checked="${me.enabled}" data-action="intake"></button></div><div class="tao-setting"><div><strong>Mac & MWG</strong><small>${esc(me.health.worker_label)}</small></div><span class="tao-badge ${me.health.mwg_ready?'success':''}">${me.health.online?'Online':'Offline'}</span></div></div>${!me.enabled?'<div class="tao-info-card"><div class="tao-kicker">Thông báo cho người khác</div><p class="tao-product">Gói cước đã hết hạn.<br>Vui lòng gia hạn để tiếp tục trải nghiệm dịch vụ.</p></div>':''}${me.owner?`<div class="tao-section-heading"><h2>Cần mở khóa</h2><span class="tao-badge neutral">${state.locks.length} người</span></div><div class="tao-info-card">${state.locks.length?state.locks.map((r,i)=>`<div class="tao-setting"><div><strong>${i+1}. ${esc(r.name)}</strong><small>${r.strikes>=3?'Chờ Tâm mở khóa':'Khóa đến '+date(r.locked_until)}</small></div><button class="tao-link" data-unlock="${i}">Mở khóa ${icon('lock')}</button></div>`).join(''):'<div class="tao-empty">Không có tài khoản đang bị khóa.</div>'}</div>`:''}${bulkCancelCard()}<button class="tao-order" data-go="queue"><div class="tao-section-heading"><h2>Kiểm tra hàng chờ</h2>${icon('right')}</div><p class="tao-subtitle">Xem chi tiết, hủy từng yêu cầu hoặc kiểm tra kết quả chưa rõ.</p></button><button class="tao-secondary tao-logout" data-action="logout">Đăng xuất Công cụ Táo</button><a class="tao-privacy-link" href="/tao/privacy">Thông tin sử dụng dữ liệu</a>`;}
  function render(){
    if(!state.me)return;
    navigation();
    main.innerHTML=({home,queue,detail,lookup,conditions,report,admin}[state.page]||home)();
    countdown();
  }
  function countdown(){
    document.querySelectorAll('[data-countdown]').forEach(el=>{
      const seconds=Math.max(0,Math.ceil((Number(el.dataset.countdown)*1000-Date.now()-state.clock)/1000));
      el.textContent=seconds?'Còn '+String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0'):'Đã hết hạn';
      if(!seconds)main.querySelector('[data-action="confirm"]')?.setAttribute('disabled','');
    });
  }
  async function refresh(quiet=false){
    if(!state.me||state.busy||(quiet&&(activeRefresh||state.unknownReview||state.page==='queue'&&state.jobs.length>20)))return;
    if(!quiet){state.unknownReview=null;state.unknownChecked=false;}
    activeRefresh++;
    const generation=++serial,page=state.page;
    if(!quiet){loading(true);error('');}
    try{
      const me=await api('me');
      if(generation!==serial)return;state.me=me;
      if(page==='home'||page==='queue'){
        const data=await api('jobs?filter='+(page==='home'?'active':state.filter));
        if(generation!==serial)return;state.jobs=data.jobs;state.offset=0;state.more=data.more;
      }else if(page==='detail'&&state.job){
        const data=await api('jobs/'+state.job.id);if(generation!==serial)return;state.job=data.job;
      }else if(page==='admin'&&me.owner){
        const data=await api('admin/locks');if(generation!==serial)return;state.locks=data.locks;
      }else if(page==='report'&&me.owner){
        const data=await api('summary?period='+state.period);if(generation!==serial)return;state.summary=data;
      }
      if(me.owner&&['queue','admin'].includes(page)){
        const data=await api('admin/queue');if(generation!==serial)return;state.queueOverview=data;
      }
      if(generation===serial)render();
    }catch(e){if(generation===serial){error(e.message);if(e.status===401)loginScreen('Phiên đăng nhập đã hết hạn.');}}
    finally{activeRefresh--;if(generation===serial)loading(false);}
  }
  async function go(page,jid){
    ++serial;state.page=page;state.cancelPreview=null;state.unknownReview=null;state.unknownChecked=false;
    if(page==='queue'){state.filter='active';state.offset=0;state.jobs=[];state.queueOverview=null;}
    if(page==='detail')state.job={id:jid,rows:[],state:'loading',label:'Đang tải'};
    render();await refresh();
  }
  function loginScreen(message='Đăng nhập để dùng các công cụ của bot.'){
    state.me=null;nav.hidden=true;loading(false);
    main.innerHTML=`<div class="tao-login"><div class="tao-kicker">Công cụ Táo</div><h1>Chào em 👋</h1><p class="tao-subtitle">${esc(message)}</p><button class="tao-primary" data-action="login">Đăng nhập bằng LINE</button><a class="tao-privacy-link" href="/tao/privacy">Thông tin sử dụng dữ liệu</a></div>`;
  }
  async function authenticate(){
    if(!window.liff)throw new Error('Chưa tải được kết nối LINE. Kiểm tra mạng rồi mở lại công cụ.');
    if(!liffReady){await liff.init({liffId:config.liff_id});liffReady=true;}
    if(!liff.isLoggedIn()){loginScreen();return;}
    const token=liff.getIDToken();if(!token)throw new Error('Thiếu quyền xác thực LINE. Vui lòng đóng rồi mở lại ứng dụng.');
    await api('auth',{method:'POST',body:JSON.stringify({id_token:token})});
    state.me=await api('me');await refresh();
  }
  async function mutate(path,data={}){
    state.busy=true;++serial;loading(true);error('');
    main.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{
      const response=await api(path,{method:'POST',body:JSON.stringify(data)});
      if(response.job)state.job=response.job;
      if(response.message)error(response.message);
      return response;
    }catch(e){error(e.message);return null;}
    finally{state.busy=false;loading(false);render();}
  }
  document.getElementById('tao-app').addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button||button.disabled||state.busy)return;
    if(button.id==='refresh'){if(state.me)await refresh();else await start();return;}
    if(button.dataset.go){await go(button.dataset.go);return;}
    if(button.dataset.job){await go('detail',button.dataset.job);return;}
    if(button.dataset.filter){state.filter=button.dataset.filter;await refresh();return;}
    if(button.dataset.period){state.period=button.dataset.period;await refresh();return;}
    if(button.dataset.copy){try{await navigator.clipboard.writeText(button.dataset.copy);error('Đã sao chép mã CO.');}catch{error('Em nhấn giữ mã CO để sao chép nhé.');}return;}
    if(button.dataset.unlock!==undefined){
      const row=state.locks[Number(button.dataset.unlock)];
      if(row&&window.confirm('Mở khóa '+row.name+' và reset số lần quá hạn về 0?')){
        await mutate('admin/unlock',{owner:row.owner,last_job:row.last_job,updated:row.updated});await refresh(true);
      }return;
    }
    switch(button.dataset.action){
      case 'login':
        try{loading(true);error('');if(!liffReady){await liff.init({liffId:config.liff_id});liffReady=true;}if(!liff.isLoggedIn())liff.login({redirectUri:location.origin+'/tao/'});else await authenticate();}catch(e){error(e.message);loading(false);}break;
      case 'confirm':
        await mutate('jobs/'+state.job.id+'/'+button.dataset.action);await refresh(true);break;
      case 'cancel':
        if(window.confirm('Hủy yêu cầu #'+state.job.id+' của '+state.job.requester+'?')){
          await mutate('jobs/'+state.job.id+'/cancel');await refresh(true);
        }break;
      case 'unknown-review':
        if(state.me.owner&&state.job?.unknown_resolution?.can_cancel){
          state.unknownReview={id:state.job.id,revision:state.job.unknown_resolution.revision};state.unknownChecked=false;render();
        }break;
      case 'unknown-back':state.unknownReview=null;state.unknownChecked=false;render();break;
      case 'unknown-confirm':{
        const review=state.unknownReview,checked=state.unknownChecked;
        if(state.me.owner&&review&&checked){
          state.unknownReview=null;state.unknownChecked=false;
          await mutate('admin/jobs/'+review.id+'/cancel-unknown',{revision:review.revision,checked_mwg_no_co:true});await refresh(true);
        }break;}
      case 'cancel-waiting':
        if(state.me.owner&&state.queueOverview?.waiting){state.cancelPreview={...state.queueOverview};render();}break;
      case 'cancel-back':state.cancelPreview=null;render();break;
      case 'cancel-waiting-confirm':{
        const review=state.cancelPreview;state.cancelPreview=null;
        if(state.me.owner&&review?.waiting){
          await mutate('admin/cancel-waiting',{revision:review.revision});await refresh(true);
        }break;}
      case 'intake':{
        const enabled=!state.me.enabled;
        if(window.confirm(enabled?'Bật nhận CO theo quyền hiện tại?':'Chuyển sang chỉ Tâm được tạo CO? Các lệnh đang xử lý vẫn hoàn tất.')){
          await mutate('admin/intake',{enabled});await refresh(true);
        }break;}
      case 'logout':
        if(await mutate('logout')){if(liffReady)liff.logout();loginScreen('Đã đăng xuất.');}break;
      case 'more':
        try{loading(true);const data=await api('jobs?filter='+state.filter+'&offset='+(state.jobs.length));const seen=new Set(state.jobs.map(j=>j.id));state.jobs.push(...data.jobs.filter(j=>!seen.has(j.id)));state.more=data.more;render();}catch(e){error(e.message);}finally{loading(false);}break;
    }
  });
  main.addEventListener('change',event=>{
    if(event.target.matches('[data-unknown-check]')){
      state.unknownChecked=event.target.checked===true;
      const button=main.querySelector('[data-action="unknown-confirm"]');if(button)button.disabled=!state.unknownChecked||state.busy;
    }
  });
  main.addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy)return;
    const form=event.target;if(!form.dataset.search)return;
    const kind=form.dataset.search,query=String(new FormData(form).get('query')||'').trim();
    state.search=query;const generation=++serial;loading(true);error('');
    try{const data=await api(kind+'?code='+encodeURIComponent(query));if(generation!==serial)return;state[kind==='lookup'?'lookup':'conditions']=data;render();}
    catch(e){if(generation===serial)error(e.message);}finally{if(generation===serial)loading(false);}
  });
  async function start(){
    loading(true);error('');
    try{
      config=await api('config');
      if(!config.ready){loginScreen('Công cụ Táo đang được kết nối. Vui lòng mở lại sau.');main.querySelector('[data-action="login"]').disabled=true;return;}
      try{state.me=await api('me');await refresh();}catch(e){if(e.status===401)await authenticate();else throw e;}
    }catch(e){loginScreen('Chưa kết nối được. Em có thể thử lại.');error(e.message);}
    finally{loading(false);}
  }
  timer=setInterval(()=>{
    countdown();
    if(!document.hidden&&state.me&&!state.busy&&['home','queue','detail','admin'].includes(state.page))refresh(true);
  },6000);
  setInterval(countdown,1000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.me)refresh(true);});
  start();
})();
