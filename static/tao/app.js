/* Công cụ Táo: all authorization and queue transitions remain server-side. */
(() => {
  'use strict';
  const main=document.getElementById('main'), nav=document.getElementById('nav');
  const notice=document.getElementById('notice'), progress=document.getElementById('progress');
  const state={page:'home',me:null,jobs:[],filter:'active',period:'today',offset:0,more:false,job:null,search:'',lookup:null,conditions:null,summary:null,locks:[],queueOverview:null,operations:null,cancelPreview:null,unknownReview:null,unknownChecked:false,busy:false,clock:0};
  let activeRefresh=0, serial=0, timer=null, liffReady=false, config=null;
  const editor={text:'',review:null,scope:'group',options:null,pending:null,openRow:-1,showSource:true};
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
      if(!response.ok){const e=new Error(data.error||'Chưa thực hiện được thao tác.');e.status=response.status;e.data=data;throw e;}
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
    const active=['detail','compose','forward'].includes(state.page)?'queue':['report','conditions','operations'].includes(state.page)?'home':state.page;
    nav.innerHTML=[['home','home','Trang chủ'],['queue','layers','Yêu cầu'],['lookup','search','Tra cứu'],...(state.me.admin?[['admin','settings','Quản lý']]:[])].map(([p,i,t])=>`<button data-go="${p}" ${active===p?'aria-current="page"':''}>${icon(i)}${t}</button>`).join('');
    nav.hidden=false;
    nav.classList.toggle('tao-nav-admin',state.me.admin);
  }
  function home(){
    const me=state.me,health=me.health;
    const tools=[['compose','box','Tạo yêu cầu','Dán tin nhắn · Sửa form'],['lookup','search','Tra cứu CO','Tìm nhanh kết quả'],['queue','layers','Yêu cầu',me.owner?'Quản lý các yêu cầu':'Các yêu cầu của bạn'],['conditions','shield','Điều kiện SP','Kiểm tra từ Sheet DATA'],...(me.owner?[['forward','layers','Giỏ nháp của Tâm','Tin gom từ LINE · Sửa từng dòng'],['operations','shield','Cần Tâm xử lý','Sự cố · Thời gian từng bước'],['report','chart','Tổng kết','Hôm nay · 7 · 30 ngày']]:[])];
    return `<div class="tao-greeting"><div><div class="tao-kicker">Công cụ Táo</div><h1>Chào ${esc(me.owner?'Tâm':me.name)} 👋</h1><p class="tao-subtitle">Mọi việc gọn trong một chỗ.</p></div><span class="tao-avatar">${esc(me.name.trim().charAt(0).toUpperCase())}</span></div><div class="tao-live"><b class="${health.mwg_ready?'':'not-ready'}"><span class="tao-dot"></span>${esc(health.worker_label)}</b><span>${me.enabled?'Nhận CO theo quyền hiện tại':'Chỉ Tâm được tạo CO'}</span></div>${me.notice?`<div class="tao-info-card tao-long-text">${esc(me.notice)}</div>`:''}<div class="tao-grid">${tools.map(([p,i,t,d],n)=>`<button class="tao-tool ${n===0?'tao-tool-featured':''}" data-go="${p}"><span class="tao-tool-icon">${icon(i)}</span><strong>${t}</strong><small>${d}</small></button>`).join('')}</div><div class="tao-section-heading"><h2>Yêu cầu đang xử lý</h2><button class="tao-link" data-go="queue">Xem tất cả ${icon('arrow')}</button></div>${state.jobs.length?state.jobs.slice(0,2).map(jobCard).join(''):'<div class="tao-info-card tao-empty">Không có yêu cầu đang chờ.</div>'}${me.admin?`<button class="tao-admin-entry" data-go="admin">${icon('shield')}<span>${me.owner?'Quản lý của Tâm':'Quản lý ADM'}<small>${me.owner?'Bật/tắt bot · Mở khóa · Hàng chờ':'Bật/tắt nhận CO · Trạng thái bot'}</small></span>${icon('right')}</button>`:''}`;
  }
  const fieldLabels={source:'Kho xuất',destination:'Kho nhận',product:'Mã sản phẩm',quantity:'Số lượng',status:'Trạng thái',note:'Note'};
  function composeTotals(){
    const rows=editor.review.rows,quantities=rows.map(row=>/^\d{1,6}$/.test(row.quantity)?Number(row.quantity):NaN);
    return rows.length+' lệnh'+(quantities.every(q=>Number.isFinite(q)&&q>0)?' · '+number(quantities.reduce((sum,q)=>sum+q,0))+' sản phẩm':' · Kiểm tra số lượng');
  }
  function composeRowSummary(row,i){
    const bad=Object.keys(editor.review.errors[i]||{});
    return `<span class="tao-compose-number">${i+1}</span><span class="tao-compose-summary"><span class="tao-compose-route"><span>${esc(row.source||'Kho xuất')}</span>${icon('arrow')}<span>${esc(row.destination||'Kho nhận')}</span></span><span class="tao-compose-code">MSP ${esc(row.product||'Chưa điền')}</span><span class="tao-compose-meta"><span>SL ${esc(row.quantity||'—')}</span><span>${esc(row.status||'Chưa chọn trạng thái')}</span>${row.note?'<span>Có Note</span>':''}</span>${bad.length?`<span class="tao-compose-invalid">Cần sửa: ${bad.map(key=>fieldLabels[key]||key).map(esc).join(', ')}</span>`:''}</span><span class="tao-compose-edit-label">${editor.openRow===i?'Thu gọn':'Sửa'}<span aria-hidden="true">${editor.openRow===i?'−':'+'}</span></span>`;
  }
  function showComposeErrors(){
    const index=editor.review?.errors.findIndex(row=>Object.keys(row).length);
    if(index>=0)editor.openRow=index;
  }
  function compose(){
    const review=editor.review,options=editor.options,locked=!!editor.pending||state.busy;
    const field=(row,i,key)=>{
      const id='compose-'+i+'-'+key,value=row[key]||'',bad=review.errors[i]?.[key]||'';
      const attrs=`id="${id}" data-row="${i}" data-field="${key}" aria-describedby="${id}-error" aria-invalid="${!!bad}" ${locked?'disabled':''}`;
      const control=key==='status'?`<select ${attrs}>${!options?.statuses.includes(value)?`<option value="${esc(value)}">${esc(value||'Chọn trạng thái')}</option>`:''}${(options?.statuses||[]).map(v=>`<option ${v===value?'selected':''}>${esc(v)}</option>`).join('')}</select>`:key==='note'?`<textarea ${attrs} rows="3" maxlength="500">${esc(value)}</textarea>`:`<input ${attrs} type="text" inputmode="numeric" autocomplete="off" value="${esc(value)}">`;
      return `<div class="tao-compose-field ${['product','note'].includes(key)?'full':''}"><label for="${id}">${fieldLabels[key]}</label>${control}<small id="${id}-error" class="tao-field-error" ${bad?'':'hidden'}>${esc(bad)}</small></div>`;
    };
    const source=`<div id="compose-source" class="tao-info-card" ${review&&!editor.showSource?'hidden':''}><label class="tao-label" for="compose-text">${review?'Tin nhắn đã dán':'Tin nhắn cần tạo CO'}</label><textarea id="compose-text" class="tao-paste" rows="6" maxlength="10000" placeholder="Dán một hoặc nhiều lệnh có kho xuất, kho nhận, MSP…" ${locked?'disabled':''}>${esc(editor.text)}</textarea><p class="tao-hint">Không ghi số lượng: 1 · Không ghi trạng thái: Mới.${review?'<br>Tách lại sẽ thay các dòng đang sửa bằng nội dung tin nhắn này.':''}</p><button class="tao-primary tao-wide" data-action="compose-parse" ${locked?'disabled':''}>${icon('layers')}${review?'Tách lại tin nhắn':'Tách thành form'}</button></div>`;
    if(!review)return title('Tạo yêu cầu','Dán nhiều lệnh, tách rồi sửa từng dòng')+source;
    const scopes=options?.scopes||[],selectedScope=scopes.find(s=>s.value===editor.scope);
    return title('Đã tách '+review.rows.length+' lệnh','Chạm Sửa để chỉnh từng lệnh; Note giữ riêng theo dòng.')+`<button class="tao-link tao-compose-source-toggle" data-action="compose-source" aria-expanded="${editor.showSource}" aria-controls="compose-source" ${locked?'disabled':''}>${icon('layers')}${editor.showSource?'Ẩn tin nhắn đã dán':'Xem tin nhắn đã dán'}${icon('right')}</button>${source}<div class="tao-compose-overview"><strong id="compose-total">${esc(composeTotals())}</strong><span>Tối đa ${options?.max_rows||7} dòng</span></div><p class="tao-hint tao-compose-hint">Tên sản phẩm lấy từ MWG sau khi gửi. Bot tự thêm thông tin liên hệ vào Note.</p><div id="compose-global" class="tao-field-error" role="status">${review.global_errors.map(esc).join('<br>')}</div><div class="tao-compose-list">${review.rows.map((row,i)=>`<section class="tao-compose-row" aria-label="Dòng ${i+1}"><button id="compose-toggle-${i}" class="tao-compose-toggle" data-compose-row="${i}" aria-expanded="${editor.openRow===i}" aria-controls="compose-body-${i}" ${locked?'disabled':''}>${composeRowSummary(row,i)}</button><div id="compose-body-${i}" class="tao-compose-body" ${editor.openRow===i?'':'hidden'}><div class="tao-compose-fields">${Object.keys(fieldLabels).map(key=>field(row,i,key)).join('')}</div><div class="tao-compose-row-actions"><button class="tao-link tao-compose-remove" data-remove-row="${i}" ${locked?'disabled':''}>${icon('x')}Xóa dòng ${i+1}</button><button class="tao-secondary" data-compose-done="${i}" ${locked?'disabled':''}>${icon('check')}Xong</button></div></div>${review.warnings.filter(w=>w.row===i).map(w=>`<p class="tao-hint tao-row-warning">${esc(w.message)}</p>`).join('')}</section>`).join('')}</div><button class="tao-secondary tao-wide" data-action="compose-add" ${locked||review.rows.length>=(options?.max_rows||7)?'disabled':''}>+ Thêm dòng</button><div class="tao-info-card tao-compose-destination">${scopes.length>1?`<label class="tao-label" for="compose-scope">Gửi yêu cầu vào</label><select id="compose-scope" class="tao-scope" ${locked?'disabled':''}>${scopes.map(s=>`<option value="${esc(s.value)}" ${s.value===editor.scope?'selected':''}>${esc(s.label)}</option>`).join('')}</select>`:`<span class="tao-label">Gửi yêu cầu vào</span><strong>${esc(selectedScope?.label||'Nhóm được cấp quyền')}</strong>`}<p class="tao-hint">Các dòng cùng trạng thái sẽ nhập chung một file. Em vẫn cần Xác nhận trong 1 phút để tạo CO.</p></div>${editor.pending?'<div class="tao-info-card"><p class="tao-product">Đang giữ nguyên lần gửi để tránh tạo trùng. Kiểm tra xem bot đã nhận chưa.</p><button class="tao-primary tao-wide" data-action="compose-recover">Kiểm tra lần gửi</button><button class="tao-secondary tao-wide" data-action="compose-submit">Thử gửi lại cùng yêu cầu</button></div>':`<div class="tao-actions"><button class="tao-primary tao-wide" data-action="compose-submit" ${!review.rows.length?'disabled':''}>${icon('arrow')}Gửi yêu cầu · ${review.rows.length} dòng</button></div><p class="tao-hint tao-compose-submit-hint">Chưa tạo CO. Bot sẽ lấy dữ liệu để em kiểm tra và Xác nhận.</p>`}`;
  }
  function composeEdit(target){
    if(target.id==='compose-text'){editor.text=target.value;return;}
    if(target.id==='compose-scope'){editor.scope=target.value;return;}
    const key=target.dataset.field,index=Number(target.dataset.row),review=editor.review;
    if(!Object.hasOwn(fieldLabels,key)||!review?.rows[index]||editor.pending)return;
    error('');
    review.rows[index][key]=target.value;
    delete review.errors[index][key];review.warnings=[];
    target.setAttribute('aria-invalid','false');document.getElementById(target.id+'-error').hidden=true;
    review.global_errors=[];document.getElementById('compose-global').textContent='';
    main.querySelectorAll('.tao-row-warning').forEach(el=>el.remove());
    document.getElementById('compose-toggle-'+index).innerHTML=composeRowSummary(review.rows[index],index);
    document.getElementById('compose-total').textContent=composeTotals();
    // Full validation runs on the server again before a request enters the queue.
  }
  async function composeAction(action){
    if(state.busy)return;
    state.busy=true;++serial;loading(true);error('');
    main.querySelectorAll('button,input,textarea,select').forEach(el=>el.disabled=true);
    let destination=null,focusError=false;
    try{
      if(action==='parse'){
        editor.review=await api('compose/parse',{method:'POST',body:JSON.stringify({text:editor.text})});
        editor.showSource=false;editor.openRow=-1;showComposeErrors();focusError=!editor.review.valid;
      }else if(action==='submit'){
        if(!editor.pending){
          const review=await api('compose/validate',{method:'POST',body:JSON.stringify({rows:editor.review.rows})});
          editor.review=review;
          if(!review.valid){showComposeErrors();focusError=true;error('Sửa các ô đang báo lỗi trước khi gửi.');return;}
          editor.pending={key:crypto.randomUUID().replaceAll('-',''),scope:editor.scope,rows:review.rows};
        }
        const response=await api('compose/submit',{method:'POST',body:JSON.stringify(editor.pending)});
        error(response.message||'');destination=response.job;
        editor.pending=null;
      }else if(action==='recover'){
        const response=await api('compose/submissions/'+editor.pending.key);
        if(response.found){destination=response.job;editor.pending=null;}
        else if(response.skipped){editor.pending=null;error('Bot đã xử lý lần gửi này và bỏ qua các dòng trùng hoặc đang chờ đối soát. Không tạo yêu cầu mới.');}
        else error('Chưa thấy yêu cầu được ghi nhận. Em có thể thử gửi lại cùng yêu cầu bằng nút bên dưới.');
      }
    }catch(e){
      if(e.data?.review){editor.review=e.data.review;showComposeErrors();focusError=true;}
      if(e.status&&e.status<500&&e.status!==401&&e.status!==429)editor.pending=null;
      error(e.message);
      if(e.status===401){loginScreen('Phiên đăng nhập hết hạn. Form đang sửa vẫn được giữ trong trang này.');return;}
    }finally{
      state.busy=false;loading(false);
      if(destination){editor.review=null;editor.text='';editor.openRow=-1;editor.showSource=true;await go('detail',destination.id);}
      else{
        render();
        if(focusError&&state.page==='compose'){
          const field=main.querySelector('.tao-compose-fields [aria-invalid="true"]');
          if(field)field.focus();else document.getElementById('compose-global')?.scrollIntoView({block:'center'});
        }
      }
    }
  }
  const basket={data:null,statuses:[],edit:null,pending:null,changed:false};
  function forward(){
    if(!state.me.owner)return title('Giỏ nháp')+'<div class="tao-info-card">Chỉ Tâm được dùng giỏ nháp.</div>';
    const draft=basket.data,edit=basket.edit;
    const heading=title('Giỏ nháp của Tâm','Đồng bộ tin gom trong chat riêng với bot');
    if(!draft)return heading+'<div class="tao-empty">Đang tải giỏ nháp…</div>';
    const pending=basket.pending?`<div class="tao-info-card"><p>Đang kiểm tra lần gửi trước để tránh gửi trùng.</p><button class="tao-primary tao-wide" data-forward-action="recover">Kiểm tra lần gửi</button><button class="tao-secondary tao-wide" data-forward-action="submit">Thử lại cùng lần gửi</button></div>`:'';
    if(draft.state!=='collecting')return heading+pending+`<section class="tao-info-card"><h2>${draft.state==='sent'?'Đã gửi giỏ nháp':draft.state==='paused'?'Giỏ cũ đã hết thời gian lưu':'Gom nháp đang tắt'}</h2><p class="tao-product tao-long-text">${esc(draft.receipt||'Bật gom, rồi chuyển tiếp các tin văn bản vào chat riêng của bot. Tin sẽ xuất hiện ở đây để em xem và sửa.')}</p>${draft.job_id?`<button class="tao-primary tao-wide" data-job="${esc(draft.job_id)}">Xem yêu cầu đã gửi ${icon('arrow')}</button>`:''}<button class="tao-secondary tao-wide" data-forward-action="start" ${basket.pending?'disabled':''}>${draft.state==='sent'?'Gom giỏ tiếp theo':'Bật gom nháp'}</button>${draft.state==='sent'?'<p class="tao-hint">Gom vẫn bật. Tin LINE mới sẽ vào giỏ mới.</p>':''}</section>`;
    const fields=(item,index)=>Object.keys(fieldLabels).map(key=>{
      const id='forward-'+index+'-'+key,value=edit.values[key]||'',bad=item.errors[key]||'';
      const attrs=`id="${id}" data-forward-field="${key}" aria-invalid="${!!bad}" ${basket.pending?'disabled':''}`;
      const control=key==='status'?`<select ${attrs}>${!basket.statuses.includes(value)?`<option value="${esc(value)}">${esc(value||'Chọn trạng thái')}</option>`:''}${basket.statuses.map(v=>`<option ${v===value?'selected':''}>${esc(v)}</option>`).join('')}</select>`:key==='note'?`<textarea ${attrs} rows="3" maxlength="500">${esc(value)}</textarea>`:`<input ${attrs} type="text" inputmode="numeric" autocomplete="off" value="${esc(value)}">`;
      return `<div class="tao-compose-field ${['product','note'].includes(key)?'full':''}"><label for="${id}">${fieldLabels[key]}</label>${control}${bad?`<small class="tao-field-error">${esc(bad)}</small>`:''}</div>`;
    }).join('');
    return heading+`<div class="tao-forward-sync"><span class="tao-badge success">${icon('lock')}Chỉ Tâm</span><span>Tự cập nhật · 6 giây</span></div><div class="tao-compose-overview"><strong>${draft.messages} tin · ${draft.rows.length}/${draft.max_rows} dòng</strong><span>Chưa gửi</span></div><p class="tao-hint">Chuyển tiếp thêm tin vào chat riêng đang bật !gom. Note của từng dòng được giữ riêng; người yêu cầu là Tâm.</p><div id="forward-conflict" class="tao-info-card" ${basket.changed?'':'hidden'}><p>Giỏ đã thay đổi trên LINE hoặc thiết bị khác. Bản sửa của em vẫn được giữ, chưa ghi đè lên giỏ.</p><button class="tao-secondary tao-wide" data-forward-action="reload">Tải bản mới</button></div>${draft.edit_index>=0?`<div class="tao-info-card">Đang sửa tin ${draft.edit_index+1} trên LINE. Hoàn tất hoặc bấm Thôi sửa trên LINE trước khi gửi. Lưu một dòng tại đây sẽ kết thúc lượt sửa tin đó.</div>`:''}${draft.global_errors.length?`<p class="tao-field-error">${draft.global_errors.map(esc).join('<br>')}</p>`:''}<div class="tao-compose-list">${draft.rows.map((item,index)=>{
      const row=item.values,open=edit?.index===index;
      const bad=[...Object.values(item.errors),...(item.entry_error?[item.entry_error]:[])];
      return `<section class="tao-compose-row" aria-label="Dòng nháp ${index+1}"><button class="tao-compose-toggle" data-forward-edit="${index}" aria-expanded="${open}" ${basket.pending?'disabled':''}><span class="tao-compose-number">${index+1}</span><span class="tao-compose-summary"><small class="tao-forward-origin">Tin ${item.entry+1}</small><span class="tao-compose-route">${esc(row.source||'?')} ${icon('arrow')} ${esc(row.destination||'?')}</span><span class="tao-compose-code">MSP ${esc(row.product||'Chưa có')}</span><span class="tao-compose-meta"><span>SL ${esc(row.quantity)}</span><span>${esc(row.status)}</span></span>${bad.length?'<span class="tao-compose-invalid">Cần kiểm tra dòng này</span>':''}</span><span class="tao-compose-edit-label">${open?'Đang sửa':'Sửa'} ${icon('right')}</span></button>${row.note&&!open?`<p class="tao-forward-note">${esc(row.note)}</p>`:''}${bad.length?`<p class="tao-field-error tao-forward-note">${bad.map(esc).join('<br>')}</p>`:''}${open?`<div class="tao-compose-body"><div class="tao-compose-fields">${fields(item,index)}</div><div class="tao-compose-row-actions"><button class="tao-link tao-compose-remove" data-forward-remove="${index}">Bỏ dòng</button><button class="tao-secondary" data-forward-action="cancel">Thôi sửa</button><button class="tao-primary" data-forward-action="save" ${basket.changed?'disabled':''}>Lưu dòng</button></div></div>`:`<div class="tao-forward-remove"><button class="tao-link tao-compose-remove" data-forward-remove="${index}" ${basket.pending?'disabled':''}>${icon('x')}Bỏ dòng ${index+1}</button></div>`}</section>`;
    }).join('')}</div>${!draft.rows.length?'<div class="tao-info-card tao-empty">Giỏ chưa có tin. Chuyển tiếp tin văn bản vào chat riêng của bot để bắt đầu.</div>':''}${draft.warnings.map(w=>`<p class="tao-hint">Dòng ${w.row+1}: ${esc(w.message)}</p>`).join('')}${pending||`<div class="tao-actions"><button class="tao-primary tao-wide" data-forward-action="submit" ${!draft.can_send||edit||basket.changed?'disabled':''}>${icon('arrow')}Gửi yêu cầu · ${draft.rows.length} dòng</button></div>`}<p class="tao-hint">${edit?'Lưu dòng hoặc Thôi sửa trước khi gửi. ':''}Sau khi gửi, bot lấy dữ liệu MWG rồi em Xác nhận trong 1 phút để tạo CO.</p>`;
  }
  function acceptBasket(response){
    basket.data=response.draft;
    if(response.statuses)basket.statuses=response.statuses;
    basket.changed=false;
  }
  async function forwardAction(action,index){
    if(state.busy||!state.me.owner)return;
    if(action==='cancel'){basket.edit=null;await refresh();return;}
    if(action==='reload'){
      if(basket.edit&&!window.confirm('Bỏ phần sửa chưa lưu và tải giỏ mới từ LINE?'))return;
      basket.edit=null;await refresh();return;
    }
    const draft=basket.data,edit=basket.edit;
    if(action==='remove'&&edit&&edit.index!==index){error('Lưu dòng hoặc Thôi sửa trước khi bỏ dòng khác.');return;}
    if(action==='remove'&&!window.confirm('Bỏ dòng '+(index+1)+' khỏi giỏ nháp chung với LINE?'))return;
    state.busy=true;++serial;loading(true);error('');
    main.querySelectorAll('button,input,textarea,select').forEach(el=>el.disabled=true);
    let destination=null;
    try{
      let response;
      if(action==='start')response=await api('forward-draft/start',{method:'POST',body:JSON.stringify({id:draft.id,revision:draft.revision})});
      else if(action==='save'||action==='remove'){
        const item=action==='save'?edit.ref:draft.rows[index];
        response=await api('forward-draft/row',{method:'POST',body:JSON.stringify({id:edit?.id||draft.id,revision:edit?.revision??draft.revision,entry:item.entry,row:item.row,action:action==='save'?'save':'remove',...(action==='save'?{values:edit.values}:{})})});
        basket.edit=null;
      }else if(action==='submit'){
        if(!basket.pending){
          if(edit||basket.changed||!draft.can_send)return;
          basket.pending={id:draft.id,revision:draft.revision};
        }
        response=await api('forward-draft/submit',{method:'POST',body:JSON.stringify(basket.pending)});
        basket.pending=null;destination=response.job;
      }else if(action==='recover'){
        if(!basket.pending)return;
        response=await api('forward-draft/submissions/'+basket.pending.id);
        if(response.found||response.skipped){basket.pending=null;destination=response.job;}
        else error('Chưa thấy lần gửi được ghi nhận. Dùng Thử lại cùng lần gửi để kiểm tra và gửi tiếp.');
      }
      if(response?.draft)acceptBasket(response);
      if(response?.message)error(response.message);
      if(response?.skipped)error(response.message||'Bot đã xử lý lần gửi này và bỏ qua các dòng trùng. Không tạo yêu cầu mới.');
      if(!destination&&!basket.edit&&!basket.pending)acceptBasket(await api('forward-draft'));
    }catch(e){
      if(e.status&&e.status<500&&![401,429].includes(e.status))basket.pending=null;
      if(e.status===409){basket.changed=true;if(!basket.edit)acceptBasket(await api('forward-draft').catch(()=>({draft:basket.data})));}
      error(e.message);
      if(e.status===401)loginScreen('Phiên đăng nhập hết hạn. Giỏ nháp đã lưu vẫn nằm trên bot.');
    }finally{
      state.busy=false;loading(false);
      if(destination)await go('detail',destination.id);else render();
    }
  }

  async function acknowledgePreview(){
    const job=state.job;
    if(state.page!=='detail'||document.hidden||!job?.can_ack_preview||state.busy)return;
    state.busy=true;
    try{
      const response=await api('jobs/'+job.id+'/preview-seen',{method:'POST',body:JSON.stringify({revision:job.preview_revision})});
      if(state.page==='detail'&&state.job?.id===job.id){state.job=response.job;render();}
    }catch(e){error(e.message);}
    finally{state.busy=false;}
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
    return title(job.state==='draft'?'Xác nhận yêu cầu':processing?'Đang tạo CO':'Kết quả yêu cầu','#'+job.id+' · '+job.requester)+`<div class="tao-section-heading">${badge(job)}${job.expires_at?`<span class="tao-badge" data-countdown="${job.expires_at}"></span>`:''}</div>${processing?'<div class="tao-info-card tao-long-text">Đã xác nhận. Kết quả CO sẽ hiện tại đây khi MWG xử lý xong.</div>':''}${job.state==='unknown'?'<div class="tao-info-card tao-long-text">MWG chưa trả đủ kết quả. Cần kiểm tra trên MWG trước khi xử lý tiếp; riêng Tâm có thể hủy sau khi xác nhận chưa có CO.</div>':''}${job.rows.map((r,i)=>rowDetails(r,i,job.rows.length)).join('')}${job.skipped_duplicates?.length?`<div class="tao-info-card">Đã bỏ qua ${job.skipped_duplicates.length} dòng trùng theo quy tắc hiện tại.</div>`:''}${job.skipped_errors?.length?`<div class="tao-info-card">Đã loại ${job.skipped_errors.length} dòng không hợp lệ.${state.me.owner?job.skipped_errors.map(r=>`<p><strong>${esc(r.source)} → ${esc(r.destination)}</strong><br>MSP ${esc(r.product)} · SL ${esc(r.quantity)}<br>${esc(r.error)}</p>`).join(''):' Xem tin bot để biết lỗi từng dòng.'}</div>`:''}${job.can_cancel||job.can_confirm?`<div class="tao-actions">${job.can_cancel?'<button class="tao-secondary" data-action="cancel">Hủy</button>':''}${job.can_confirm?'<button class="tao-primary" data-action="confirm">'+icon('check')+'Xác nhận</button>':''}</div>`:''}${unknownCancelCard(job)}${state.me.owner?diagnostics(job.diagnostics):''}${job.owner_cancelled_at?`<div class="tao-info-card tao-long-text">Tâm đã xác nhận kiểm tra MWG và chưa có CO lúc ${date(job.owner_cancelled_at)}. Đã lưu lịch sử hủy.${job.state!=='cancelled'?' Kết quả mới từ MWG được hiển thị phía trên.':''}</div>`:''}${job.state==='draft'&&!job.expires_at?'<p class="tao-hint">Bot đang gửi thông tin xác nhận về LINE. Vui lòng chờ cập nhật.</p>':''}`;
  }
  const secondsLabel=value=>value===null||value===undefined?'Chưa có số đo':Number(value)<60?number(Math.round(Number(value)*10)/10)+' giây':number(Math.round(Number(value)/6)/10)+' phút';
  function diagnostics(data){
    if(!data)return '';
    if(!data.available)return '<div class="tao-info-card tao-hint">Yêu cầu này chưa có nhật ký đo thời gian. Các yêu cầu mới sẽ được ghi từ bản cập nhật này.</div>';
    const steps=data.mac_steps.filter((step,i,all)=>step.outcome!=='start'||!all.slice(i+1).some(next=>next.stage===step.stage&&next.outcome!=='start')).slice(-20);
    return `<section class="tao-info-card tao-diagnostics"><h2>Thời gian từng bước</h2><p class="tao-hint">${esc(data.notice)}</p>${data.phases.map(p=>`<div class="tao-timing"><span>${esc(p.label)}<small>${p.complete?'Đã kết thúc':p.stopped?'Đã dừng · thời gian quan sát':'Đang chờ · thời gian quan sát'}</small></span><b>${esc(secondsLabel(p.seconds))}</b></div>`).join('')}${steps.length?`<h3>Chi tiết trên Mac</h3>${steps.map(p=>`<div class="tao-timing ${p.outcome==='error'?'tao-timing-error':''}"><span>${esc(p.label)}<small>${esc(p.error||(p.outcome==='start'?'Bắt đầu · chưa nhận mốc kết thúc':'Đã ghi nhận'))}</small></span><b>${esc(secondsLabel(p.seconds))}</b></div>`).join('')}`:'<p class="tao-hint">Chưa nhận chi tiết từng thao tác từ Mac.</p>'}</section>`;
  }
  function operations(){
    if(!state.me.owner)return title('Không có quyền truy cập');
    const data=state.operations;
    if(!data)return title('Cần Tâm xử lý','Đang tải thông tin vận hành');
    const mainTimings=data.timings.filter(p=>!p.key.startsWith('mac:')),macTimings=data.timings.filter(p=>p.key.startsWith('mac:'));
    const timingRows=rows=>rows.map(p=>`<div class="tao-metric"><strong>${esc(p.label)}</strong><div><span>Trung bình <b>${esc(secondsLabel(p.average))}</b></span><span>95% lượt ≤ <b>${esc(secondsLabel(p.p95))}</b></span></div><small>${number(p.count)} lượt có đủ mốc bắt đầu/kết thúc</small></div>`).join('');
    return title('Cần Tâm xử lý','Chỉ Tâm 258330 · cập nhật '+date(data.server_time))+`<div class="tao-summary"><div class="tao-stat"><strong>${number(data.issue_count)}</strong><span>Mục cần kiểm tra</span></div><div class="tao-stat"><strong>${number(data.coverage.instrumented)}/${number(data.coverage.recent_requests)}</strong><span>Yêu cầu có nhật ký · 24 giờ</span></div></div><p class="tao-hint">Danh sách hỗ trợ kiểm tra; không tự hủy hoặc tạo lại CO. Dòng lỗi gần đây hiển thị trong 24 giờ; yêu cầu chưa rõ kết quả tiếp tục được giữ.</p>${data.issues.length?data.issues.map(issue=>`<section class="tao-info-card tao-issue ${issue.severity==='danger'?'tao-issue-danger':''}"><div class="tao-order-top"><span>${issue.job_id?'#'+esc(issue.job_id):'Mac & MWG'}</span><span class="tao-badge ${issue.severity==='danger'?'danger':'neutral'}">${issue.severity==='danger'?'Cần kiểm tra':'Lưu ý'}</span></div><h2>${esc(issue.title)}</h2>${issue.requester?`<p class="tao-hint">${esc(issue.requester)}</p>`:''}<p>${esc(issue.guidance)}</p>${issue.reason?`<p class="tao-hint">${issue.kind==='slow'?'Bước cuối: ': 'Phân loại: '}${esc(issue.kind==='slow'?issue.reason:({line_delivery:'Gửi thông báo',product:'Dữ liệu sản phẩm',timeout:'Quá thời gian',status:'Trạng thái MWG',network:'Kết nối',mismatch:'Đối chiếu dữ liệu',login:'Đăng nhập',browser_closed:'Chrome đã đóng',mwg_error:'Thông báo MWG',unclassified:'Chưa rõ'}[issue.reason]||issue.reason))}</p>`:''}<button class="tao-secondary" ${issue.job_id?'data-job="'+esc(issue.job_id)+'"':'data-go="admin"'}>${issue.job_id?'Xem chi tiết yêu cầu':'Xem quản lý'}</button></section>`).join(''):'<div class="tao-info-card tao-empty">Chưa có sự cố cần Tâm xử lý theo dữ liệu hiện có.</div>'}${data.truncated?'<p class="tao-hint">Đang hiển thị giới hạn dữ liệu gần nhất. Mở Hàng chờ để xem thêm yêu cầu.</p>':''}<section class="tao-info-card"><h2>Thời gian xử lý · 24 giờ</h2><p class="tao-hint">Chờ xác nhận được tính riêng. Chỉ tính lượt có đủ mốc; chưa có dữ liệu không tính là 0 giây.</p>${mainTimings.length?timingRows(mainTimings):'<p>Đang chờ yêu cầu mới để đo thời gian.</p>'}</section>${macTimings.length?`<section class="tao-info-card"><h2>Từng thao tác trên Mac</h2>${timingRows(macTimings)}</section>`:'<p class="tao-hint">Chi tiết Mac xuất hiện sau khi worker bản mới xử lý yêu cầu.</p>'}<section class="tao-info-card"><h2>Nguyên nhân cần chú ý · 24 giờ</h2>${data.error_stages?.length?data.error_stages.map(e=>`<div class="tao-timing"><span>${esc(e.stage)}<small>${esc(e.label)}</small></span><b>${number(e.count)} yêu cầu</b></div>`).join(''):''}${data.errors.length?data.errors.map(e=>`<div class="tao-timing"><span>${esc(e.label)}</span><b>${number(e.count)} yêu cầu</b></div>`).join(''):'<p class="tao-hint">Chưa có lỗi thuộc nhóm đang theo dõi.</p>'}</section><p class="tao-hint">Nhật ký lưu tối đa 30 ngày. Không thay đổi quyền, bước Xác nhận hay quy tắc hàng chờ.</p>`;
  }
  function searchForm(kind,label,placeholder){return `<form data-search="${kind}"><label class="tao-label" for="query">${label}</label><div class="tao-search">${icon('search')}<input id="query" name="query" ${kind==='conditions'?'inputmode="numeric" maxlength="13"':''} placeholder="${placeholder}" value="${esc(state.search)}" required autocomplete="off"><button type="submit">Tra cứu</button></div></form>`;}
  function lookup(){return title('Tra cứu CO','Lịch sử 30 ngày gần nhất')+searchForm('lookup','Mã CO hoặc mã yêu cầu','Nhập mã cần tra cứu')+`<p class="tao-hint">Tra CO theo quyền !CO hiện tại. Mã yêu cầu chỉ xem được khi bạn có quyền.</p>${state.lookup?.text?`<div class="tao-info-card tao-long-text">${esc(state.lookup.text)}</div>`:state.lookup?.job?jobCard(state.lookup.job):''}`;}
  function conditions(){const data=state.conditions;return title('Điều kiện sản phẩm','Thông tin tham khảo từ Sheet DATA')+searchForm('conditions','Mã sản phẩm','Nhập đủ 13 chữ số')+`<p class="tao-hint">Bán thường · Chiến giá · Chuyển kho</p>${data?`<div class="tao-info-card"><div class="tao-kicker">MSP ${esc(data.code)}</div>${data.found?data.conditions.map(c=>`<div class="tao-condition ${c.state==='no'?'bad':''}">${icon(c.state==='yes'?'check':c.state==='no'?'x':'box')}<span>${esc(c.label)} · ${esc(c.value)}</span></div>`).join(''):`<p class="tao-product">${esc(data.message)}</p>`}</div>`:''}`;}
  function report(){const s=state.summary;const labels={people:'Top 5 người yêu cầu',source:'Top 5 kho xuất',destination:'Top 5 kho nhận',region:'Top 5 vùng xuất',province:'Top 5 tỉnh/thành xuất',product:'Top 5 sản phẩm'};return title('Tổng kết CO','Riêng Tâm 258330')+`<div class="tao-segments" aria-label="Khoảng thời gian">${[['today','Hôm nay'],['7','7 ngày'],['30','30 ngày']].map(([v,t])=>`<button data-period="${v}" aria-pressed="${state.period===v}">${t}</button>`).join('')}</div>${s?`<p class="tao-hint">${state.period==='today'?'Trong ngày':state.period+' ngày gần nhất'} · Giờ Việt Nam</p><div class="tao-summary">${[['co','CO thành công'],['quantity','Sản phẩm đã chuyển'],['requests','Yêu cầu'],['failed','Dòng lỗi']].map(([v,t])=>`<div class="tao-stat"><strong>${number(s.stats[v])}</strong><span>${t}</span></div>`).join('')}</div>${Object.entries(labels).map(([k,t])=>`<div class="tao-info-card tao-report-list"><div class="tao-section-heading"><h2>${t}</h2><span class="tao-kicker">CO</span></div>${s.top[k].length?s.top[k].map((r,i)=>`<div class="tao-ranking"><span>${i+1}</span><span>${esc(k==='product'?short(r.name):r.name)}</span><b>${number(r.count)}</b></div>`).join(''):'<p class="tao-hint">Chưa có dữ liệu.</p>'}</div>`).join('')}<div class="tao-section-heading"><h2>5 dòng CO gần đây</h2></div>${s.recent.map(r=>`<div class="tao-info-card"><div class="tao-order-top"><span>${esc(r.time)} · ${esc(r.person)}</span><b>${esc(r.state)}</b></div><p class="tao-route">${esc(r.source)} → ${esc(r.destination)}</p><p class="tao-product">${esc(short(r.product))}</p><p>SL ${esc(r.quantity)} · ${esc(r.co)}</p></div>`).join('')}<p class="tao-hint">Số liệu dùng cùng cách tính với lệnh !tongket trên LINE.</p>`:''}`;}
  function admin(){const me=state.me;return title('Quản lý',me.owner?'Tâm 258330 Apple · Chủ bot':'Tài khoản ADM')+`<div class="tao-info-card"><div class="tao-setting"><div><strong>Nhận yêu cầu CO</strong><small>${me.enabled?'Theo quyền hiện tại':'Chỉ Tâm được tạo CO'}</small></div><button class="tao-toggle" role="switch" aria-label="Nhận yêu cầu CO theo quyền hiện tại" aria-checked="${me.enabled}" data-action="intake"></button></div><div class="tao-setting"><div><strong>Mac & MWG</strong><small>${esc(me.health.worker_label)}</small></div><span class="tao-badge ${me.health.mwg_ready?'success':''}">${me.health.online?'Online':'Offline'}</span></div></div>${!me.enabled?'<div class="tao-info-card"><div class="tao-kicker">Thông báo cho người khác</div><p class="tao-product">Gói cước đã hết hạn.<br>Vui lòng gia hạn để tiếp tục trải nghiệm dịch vụ.</p></div>':''}${me.owner?`<div class="tao-section-heading"><h2>Cần mở khóa</h2><span class="tao-badge neutral">${state.locks.length} người</span></div><div class="tao-info-card">${state.locks.length?state.locks.map((r,i)=>`<div class="tao-setting"><div><strong>${i+1}. ${esc(r.name)}</strong><small>${r.strikes>=3?'Chờ Tâm mở khóa':'Khóa đến '+date(r.locked_until)}</small></div><button class="tao-link" data-unlock="${i}">Mở khóa ${icon('lock')}</button></div>`).join(''):'<div class="tao-empty">Không có tài khoản đang bị khóa.</div>'}</div>`:''}${me.owner?'<button class="tao-order" data-go="operations"><strong>Cần Tâm xử lý</strong><p class="tao-subtitle">Sự cố và thời gian từng bước</p></button>':''}${bulkCancelCard()}<button class="tao-order" data-go="queue"><div class="tao-section-heading"><h2>Kiểm tra hàng chờ</h2>${icon('right')}</div><p class="tao-subtitle">Xem chi tiết, hủy từng yêu cầu hoặc kiểm tra kết quả chưa rõ.</p></button><button class="tao-secondary tao-logout" data-action="logout">Đăng xuất Công cụ Táo</button><a class="tao-privacy-link" href="/tao/privacy">Thông tin sử dụng dữ liệu</a>`;}
  function render(){
    if(!state.me)return;
    navigation();
    main.innerHTML=({home,queue,detail,compose,forward,lookup,conditions,report,admin,operations}[state.page]||home)();
    countdown();
    if(state.page==='detail'&&state.job?.can_ack_preview)requestAnimationFrame(()=>acknowledgePreview());
  }
  function countdown(){
    document.querySelectorAll('[data-countdown]').forEach(el=>{
      const seconds=Math.max(0,Math.ceil((Number(el.dataset.countdown)*1000-Date.now()-state.clock)/1000));
      el.textContent=seconds?'Còn '+String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0'):'Đã hết hạn';
      if(!seconds)main.querySelector('[data-action="confirm"]')?.setAttribute('disabled','');
    });
  }
  async function refresh(quiet=false){
    if(!state.me||state.busy||(quiet&&(activeRefresh||state.unknownReview||state.page==='compose'||state.page==='queue'&&state.jobs.length>20)))return;
    if(!quiet){state.unknownReview=null;state.unknownChecked=false;}
    activeRefresh++;
    const generation=++serial,page=state.page;
    if(!quiet){loading(true);error('');}
    try{
      const me=await api('me');
      if(generation!==serial)return;state.me=me;
      if(page==='compose'){
        editor.options=await api('compose');if(generation!==serial)return;
        if(!editor.options.scopes.some(s=>s.value===editor.scope))editor.scope='group';
      }else if(page==='forward'&&me.owner){
        const response=await api('forward-draft');if(generation!==serial)return;
        if(basket.edit){
          basket.changed=response.draft.id!==basket.edit.id||response.draft.revision!==basket.edit.revision;
          const banner=document.getElementById('forward-conflict');if(banner)banner.hidden=!basket.changed;
          const save=main.querySelector('[data-forward-action="save"]');if(save)save.disabled=basket.changed;
          return; // Keep focus, unsaved input and row references intact during synchronization.
        }
        if(quiet&&basket.data?.id===response.draft.id&&basket.data?.revision===response.draft.revision&&basket.data?.job_id===response.draft.job_id)return;
        acceptBasket(response);
      }else if(page==='home'||page==='queue'){
        const data=await api('jobs?filter='+(page==='home'?'active':state.filter));
        if(generation!==serial)return;state.jobs=data.jobs;state.offset=0;state.more=data.more;
      }else if(page==='detail'&&state.job){
        const data=await api('jobs/'+state.job.id);if(generation!==serial)return;state.job=data.job;
      }else if(page==='admin'&&me.owner){
        const data=await api('admin/locks');if(generation!==serial)return;state.locks=data.locks;
      }else if(page==='operations'&&me.owner){
        const data=await api('admin/operations');if(generation!==serial)return;state.operations=data;
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
    if(button.id==='refresh'){if(state.page==='forward'&&basket.edit){await forwardAction('reload');return;}if(state.me)await refresh();else await start();return;}
    if(button.dataset.go){await go(button.dataset.go);return;}
    if(button.dataset.job){await go('detail',button.dataset.job);return;}
    if(button.dataset.filter){state.filter=button.dataset.filter;await refresh();return;}
    if(button.dataset.period){state.period=button.dataset.period;await refresh();return;}
    if(button.dataset.copy){try{await navigator.clipboard.writeText(button.dataset.copy);error('Đã sao chép mã CO.');}catch{error('Em nhấn giữ mã CO để sao chép nhé.');}return;}
    if(button.dataset.forwardAction){await forwardAction(button.dataset.forwardAction);return;}
    if(button.dataset.forwardRemove!==undefined){await forwardAction('remove',Number(button.dataset.forwardRemove));return;}
    if(button.dataset.forwardEdit!==undefined&&!basket.pending){
      const index=Number(button.dataset.forwardEdit),item=basket.data?.rows[index];
      if(!item)return;
      if(basket.edit){error('Lưu dòng hoặc Thôi sửa trước khi chọn dòng khác.');return;}
      basket.edit={index,id:basket.data.id,revision:basket.data.revision,ref:{entry:item.entry,row:item.row},values:{...item.values}};
      render();document.getElementById('forward-'+index+'-source')?.focus({preventScroll:true});return;
    }
    if(button.dataset.composeRow!==undefined&&!editor.pending){
      const index=Number(button.dataset.composeRow);editor.openRow=editor.openRow===index?-1:index;render();
      document.getElementById('compose-toggle-'+index)?.focus({preventScroll:true});return;
    }
    if(button.dataset.composeDone!==undefined&&!editor.pending){
      const index=Number(button.dataset.composeDone);editor.openRow=-1;render();
      document.getElementById('compose-toggle-'+index)?.focus({preventScroll:true});return;
    }
    if(button.dataset.removeRow!==undefined&&!editor.pending){
      const index=Number(button.dataset.removeRow);editor.review.rows.splice(index,1);editor.review.errors.splice(index,1);
      editor.review.warnings=[];editor.review.global_errors=[];editor.openRow=-1;error('');render();return;
    }
    if(button.dataset.unlock!==undefined){
      const row=state.locks[Number(button.dataset.unlock)];
      if(row&&window.confirm('Mở khóa '+row.name+' và reset số lần quá hạn về 0?')){
        await mutate('admin/unlock',{owner:row.owner,last_job:row.last_job,updated:row.updated});await refresh(true);
      }return;
    }
    switch(button.dataset.action){
      case 'compose-source':if(!editor.pending){editor.showSource=!editor.showSource;render();}break;
      case 'compose-parse':await composeAction('parse');break;
      case 'compose-submit':await composeAction('submit');break;
      case 'compose-recover':await composeAction('recover');break;
      case 'compose-add':
        if(editor.review&&!editor.pending&&editor.review.rows.length<(editor.options?.max_rows||7)){
          editor.review.rows.push({source:'',destination:'',product:'',quantity:'1',status:editor.review.rows[0]?.status||'Mới',note:''});
          editor.review.errors.push({});editor.openRow=editor.review.rows.length-1;render();
        }break;
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
        if(await mutate('logout')){basket.data=null;basket.edit=null;basket.pending=null;basket.changed=false;editor.text='';editor.review=null;editor.pending=null;editor.openRow=-1;editor.showSource=true;if(liffReady)liff.logout();loginScreen('Đã đăng xuất.');}break;
      case 'more':
        try{loading(true);const data=await api('jobs?filter='+state.filter+'&offset='+(state.jobs.length));const seen=new Set(state.jobs.map(j=>j.id));state.jobs.push(...data.jobs.filter(j=>!seen.has(j.id)));state.more=data.more;render();}catch(e){error(e.message);}finally{loading(false);}break;
    }
  });
  function forwardEdit(target){
    if(state.page==='forward'&&basket.edit&&Object.hasOwn(fieldLabels,target.dataset.forwardField))
      basket.edit.values[target.dataset.forwardField]=target.value;
  }
  main.addEventListener('input',event=>{if(state.page==='compose')composeEdit(event.target);forwardEdit(event.target);});
  main.addEventListener('change',event=>{
    forwardEdit(event.target);
    if(state.page==='compose')composeEdit(event.target);
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
    if(!document.hidden&&state.me&&!state.busy&&['home','queue','detail','admin','forward'].includes(state.page))refresh(true);
  },6000);
  setInterval(countdown,1000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.me)refresh(true);});
  start();
})();
