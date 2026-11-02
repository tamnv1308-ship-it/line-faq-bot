/* Presentation only. Source currencies and all quantity/ratio calculations stay unchanged. */
'use strict';
(() => {
  const scales={vnd:1e9,million_vnd:1000,billion_vnd:1};
  const wholeBillions=new Intl.NumberFormat('vi-VN',{maximumFractionDigits:0});
  function billions(value,unit='vnd'){
    if(!Object.hasOwn(scales,unit))throw Error('Unknown revenue unit: '+unit);
    return Number.isFinite(value)?value/scales[unit]:null;
  }
  function format(value,unit='vnd'){
    const n=billions(value,unit);
    if(n===null)return '—';
    // Display whole billions; keep the original precision for calculations/exports.
    if(Math.abs(n)<0.5)return '0';
    return wholeBillions.format(n);
  }
  const api={billions,format};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else globalThis.TaoMoney=api;
})();

'use strict';
(() => {
  const Money=typeof module!=='undefined'&&module.exports?require('./money.js'):globalThis.TaoMoney;
  const numberFormats=new Map();
  const number = (n,d=0) => {if(!Number.isFinite(n))return '—';if(!numberFormats.has(d))numberFormats.set(d,new Intl.NumberFormat('vi-VN',{maximumFractionDigits:d,minimumFractionDigits:d}));return numberFormats.get(d).format(n);};
  const esc = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const change = (current,previous) => previous>0 ? (current/previous-1)*100 : null;
  const pct = value => value===null || !Number.isFinite(value) ? '—' : (value>0?'+':'')+number(value,1)+'%';
  const shortDate = day => day.slice(8,10)+'/'+day.slice(5,7);
  const money = n => Money.format(n);
  const amount = (n,metric) => metric==='quantity' ? number(n) : money(n)+' tỷ';
  const groupColor = g => 'var(--category-'+g.id+', '+g.color+')';
  const badge = value => '<span class="delta '+(value>0?'positive':value<0?'negative':'')+'">'+pct(value)+'</span>';
  function validate(data) {
    if(data?.schema!==1 || data.state!=='ready' || !/^2026-\d{2}-\d{2}$/.test(data.cutoff) || !Array.isArray(data.daily) || !data.daily.length || !Array.isArray(data.groups) || data.groups.length!==6)throw Error('History unavailable');
    if(data.grouping_rule!=='apple-6-watch-bands-accessories-v2'||data.groups.map(g=>g.id).join(',')!=='iphone,ipad,mac,watch,airpods,accessories')throw Error('Outdated product groups');
    const seen=new Set();
    for(const group of data.groups)if(!/^[a-z]+$/.test(group.id)||!/^#[0-9a-f]{6}$/i.test(group.color))throw Error('Invalid group');
    for(const [day,values] of data.daily){
      if(seen.has(day)||!/^2026-\d{2}-\d{2}$/.test(day)||day>data.cutoff||values.length!==data.groups.length||values.some(row=>row.length!==4||row.some(v=>!Number.isFinite(v))))throw Error('Invalid daily series');
      seen.add(day);
    }
    return data;
  }
  function periods(data){
    const month=Number(data.cutoff.slice(5,7)),q=Math.ceil(month/3),list=[{id:'ytd',name:'Lũy kế năm',start:'2026-01-01',end:data.cutoff}];
    for(let i=1;i<=q;i++){
      const start='2026-'+String((i-1)*3+1).padStart(2,'0')+'-01';
      const end=new Date(Date.UTC(2026,i*3,0)).toISOString().slice(0,10);
      list.push({id:'q'+i,name:'Quý '+i+(i===q?' · đến '+shortDate(data.cutoff):''),start,end:end<data.cutoff?end:data.cutoff});
    }
    list.push({id:'mtd',name:'Tháng '+month+' · đến '+shortDate(data.cutoff),start:data.cutoff.slice(0,8)+'01',end:data.cutoff});
    return list;
  }
  function aggregate(data,id='ytd'){
    const period=periods(data).find(p=>p.id===id)||periods(data)[0];
    const rows=data.daily.filter(([day])=>day>=period.start&&day<=period.end);
    const groups=data.groups.map(g=>({...g,previousQuantity:0,previousRevenue:0,quantity:0,revenue:0}));
    for(const [,values] of rows)values.forEach((v,i)=>{groups[i].previousQuantity+=v[0];groups[i].previousRevenue+=v[1];groups[i].quantity+=v[2];groups[i].revenue+=v[3];});
    const total=groups.reduce((a,g)=>{for(const k of ['previousQuantity','previousRevenue','quantity','revenue'])a[k]+=g[k];return a;},{previousQuantity:0,previousRevenue:0,quantity:0,revenue:0});
    groups.forEach(g=>{g.change=change(g.revenue,g.previousRevenue);g.quantityChange=change(g.quantity,g.previousQuantity);g.delta=g.revenue-g.previousRevenue;g.share=total.revenue>0?g.revenue/total.revenue*100:null;});
    const expected=Math.round((Date.parse(period.end)-Date.parse(period.start))/86400000)+1;
    return {period,rows,groups,total,expected,paired:rows.length};
  }
  function series(model,groupId='all',metric='revenue'){
    const index=model.groups.findIndex(g=>g.id===groupId),daily=model.expected<=31,map=new Map(),offset=metric==='quantity'?0:1;
    for(const [day,values] of model.rows){
      const key=daily?day:day.slice(0,7),point=map.get(key)||{key,label:daily?day.slice(8,10):'T'+Number(day.slice(5,7)),current:0,previous:0,days:0};
      const selected=index<0?values:[values[index]];
      for(const v of selected){point.previous+=v[offset];point.current+=v[offset+2];}point.days++;
      map.set(key,point);
    }
    return [...map.values()].sort((a,b)=>a.key.localeCompare(b.key));
  }
  function coordinates(points,width=760,height=244,metric='revenue'){
    const left=48,right=13,top=18,bottom=32,values=points.flatMap(p=>[p.current,p.previous]);
    let min=Math.min(0,...values),max=Math.max(0,...values);if(max===min)max=min+1;
    const rough=(max-min)*1.08/4,power=10**Math.floor(Math.log10(rough)),factor=rough/power;
    const step=Math.max(metric==='quantity'?1:0,(factor<=1?1:factor<=2?2:factor<=5?5:10)*power);
    min=Math.floor(min/step)*step;max=Math.ceil(max/step)*step;if(max===min)max=min+step;
    return {width,height,left,right,top,bottom,min,max,step,
      x:i=>left+(points.length<=1?(width-left-right)/2:i/(points.length-1)*(width-left-right)),
      y:v=>top+(max-v)/(max-min)*(height-top-bottom)};
  }
  function csv(model){
    const text = value => '"'+String(value??'').replaceAll('"','""')+'"';
    const header=['Nhóm hàng','Doanh thu 2025 (tỷ đồng)','Doanh thu 2026 (tỷ đồng)','Tăng trưởng (%)','Số bán 2025','Số bán 2026'];
    const lines=[['Kỳ so sánh',model.period.start,model.period.end],['Phạm vi','Apple; Mới + Mới giảm giá; doanh thu gốc × 1,08'],header];
    for(const g of [...model.groups,{...model.total,name:'Tổng cộng',change:change(model.total.revenue,model.total.previousRevenue)}])lines.push([g.name,Money.billions(g.previousRevenue),Money.billions(g.revenue),g.change===null?'':g.change.toFixed(4),g.previousQuantity,g.quantity]);
    return '\ufeff'+lines.map(row=>row.map(text).join(',')).join('\r\n');
  }
  const helpers={validate,periods,aggregate,series,change,coordinates,csv};
  if(typeof module!=='undefined'&&module.exports){module.exports=helpers;return;}
  const $=id=>document.getElementById(id);
  if(!$('business-overview'))return;
  let source=null,model=null,period='ytd',metric='revenue',group='all',comparison='growth',sortMode='revenue',points=[],loading=false,refreshTimer=null;
  let lastRead=0,needsRender=true;
  let revision=0;
  const visible=()=>!document.hidden&&['','#home','#portfolio-section'].includes(location.hash);
  function kpi(label,value,unit,note,delta,featured=false){return '<article class="business-kpi'+(featured?' featured':'')+'"><div class="kpi-label">'+esc(label)+'</div><div class="kpi-value"><span class="kpi-number">'+esc(value)+'</span>'+(unit?'<small>'+esc(unit)+'</small>':'')+'</div><div class="kpi-bottom">'+(delta!==undefined?badge(delta):'')+'<span>'+esc(note)+'</span></div></article>';}
  function renderKpis(){
    const t=model.total,driver=[...model.groups].sort((a,b)=>b.delta-a.delta)[0],delta=t.revenue-t.previousRevenue;
    const asp=t.quantity>0?t.revenue/t.quantity:null,previousAsp=t.previousQuantity>0?t.previousRevenue/t.previousQuantity:null;
    const primary=kpi('Doanh thu toàn ngành',money(t.revenue),'tỷ đồng','so với cùng kỳ',change(t.revenue,t.previousRevenue),true).replace('</article>','<p class="kpi-baseline">Cùng kỳ 2025 <strong>'+money(t.previousRevenue)+' tỷ</strong></p></article>');
    $('business-kpis').innerHTML=primary+
      kpi('Số sản phẩm',number(t.quantity),'','so với cùng kỳ',change(t.quantity,t.previousQuantity))+
      kpi('Chênh lệch doanh thu',(delta>0?'+':'')+money(delta),'tỷ','2026 so với 2025')+
      kpi('Doanh thu / sản phẩm',Number.isFinite(asp)?number(asp/1e6,1):'—','triệu/SP','so với cùng kỳ',asp!==null&&previousAsp!==null?change(asp,previousAsp):null);
    $('executive-takeaway').innerHTML=delta>0&&driver.delta>0?
      '<strong>'+esc(driver.name)+'</strong> đóng góp <strong>'+number(driver.delta/delta*100,1)+'%</strong> mức tăng doanh thu, tương ứng <strong>+'+money(driver.delta)+' tỷ đồng</strong>.':
      'Chênh lệch doanh thu toàn ngành: <strong>'+(delta>0?'+':'')+money(delta)+' tỷ đồng</strong> trên '+model.paired+' ngày đối chiếu.';
  }
  function renderTrend(){
    if(!model)return;
    points=series(model,group,metric);
    const title=metric==='quantity'?'số bán':'doanh thu',g=model.groups.find(g=>g.id===group),root=$('trend-chart');
    $('trend-title').textContent='Xu hướng '+title;
    $('trend-caption').textContent=(g?g.name:'Toàn ngành Apple')+' · '+(model.expected<=31?'theo ngày':'theo tháng');
    $('trend-unit').textContent=metric==='quantity'?'Sản phẩm':'Tỷ đồng';
    if(!points.length){root.innerHTML='<p class="empty">Chưa có ngày đủ dữ liệu trong kỳ này.</p>';return;}
    const w=Math.max(240,Math.min(960,root.clientWidth||760)),h=w<450?226:252,c=coordinates(points,w,h,metric),baseline=c.y(0);
    const peak=Math.max(Math.abs(c.min),Math.abs(c.max));
    const divisor=metric==='quantity'?(peak>=1000?1000:1):1e9;
    const digits=Math.min(12,Math.max(0,-Math.floor(Math.log10(c.step/divisor))));
    $('trend-unit').textContent=metric==='quantity'?(divisor===1000?'Nghìn sản phẩm':'Sản phẩm'):'Tỷ đồng';
    let grid='',labels='';
    for(let i=0;i<=Math.round((c.max-c.min)/c.step);i++){const v=c.min+c.step*i,y=c.y(v);grid+='<line class="grid-line" x1="'+c.left+'" y1="'+y+'" x2="'+(w-c.right)+'" y2="'+y+'"/><text class="axis-label" x="'+(c.left-9)+'" y="'+(y+3)+'" text-anchor="end">'+number(v/divisor,digits)+'</text>';}
    const current=points.map((p,i)=>(i?'L':'M')+c.x(i).toFixed(2)+','+c.y(p.current).toFixed(2)).join(' '),previous=points.map((p,i)=>(i?'L':'M')+c.x(i).toFixed(2)+','+c.y(p.previous).toFixed(2)).join(' ');
    const labelCount=Math.min(points.length,w<420?5:10),labelIndices=new Set();
    for(let i=0;i<labelCount;i++)labelIndices.add(labelCount===1?0:Math.round(i*(points.length-1)/(labelCount-1)));
    points.forEach((p,i)=>{if(labelIndices.has(i))labels+='<text class="axis-label" x="'+c.x(i)+'" y="'+(h-9)+'" text-anchor="middle">'+esc(p.label)+'</text>';});
    const markers=points.map((p,i)=>'<circle class="trend-point" data-point="'+i+'" tabindex="0" role="button" aria-label="'+esc(p.label+': 2026 '+amount(p.current,metric)+'; 2025 '+amount(p.previous,metric))+'" cx="'+c.x(i)+'" cy="'+c.y(p.current)+'" r="'+(points.length>15?2.4:3.6)+'"><title>'+esc(p.label+' · 2026: '+amount(p.current,metric)+' · 2025: '+amount(p.previous,metric))+'</title></circle>').join('');
    root.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+esc('Biểu đồ '+title+' '+(g?g.name:'toàn ngành')+' so sánh 2026 với 2025 cùng kỳ')+'"><defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b4cbff" stop-opacity=".12"/><stop offset="100%" stop-color="#b4cbff" stop-opacity="0"/></linearGradient></defs>'+grid+'<path d="'+current+' L'+c.x(points.length-1)+','+baseline+' L'+c.x(0)+','+baseline+' Z" fill="url(#trend-fill)"/><path class="series-previous" d="'+previous+'"/><path class="series-current" d="'+current+'"/>'+markers+labels+'</svg>';
    readPoint(points.length-1);
  }
  function readPoint(index){const p=points[index];if(!p)return;const label=p.key.length===7?'Tháng '+Number(p.key.slice(5))+' · '+p.days+' ngày đối chiếu':'Ngày '+shortDate(p.key);$('trend-readout').textContent=label+'  ·  2026: '+amount(p.current,metric)+'  /  2025: '+amount(p.previous,metric)+'  ·  '+pct(change(p.current,p.previous));}
  function renderMix(){
    const total=model.total[metric],previousKey=metric==='quantity'?'previousQuantity':'previousRevenue',previousTotal=model.total[previousKey],groups=model.groups;
    $('mix-caption').textContent='Tỷ trọng '+(metric==='quantity'?'số bán':'doanh thu')+' · hai năm cùng kỳ';
    if(total<=0||previousTotal<=0||groups.some(g=>g[metric]<0||g[previousKey]<0)){$('mix-chart').innerHTML='<p class="empty">Không thể hiện tỷ trọng khi có giá trị âm hoặc tổng bằng 0.</p>';$('mix-legend').innerHTML='';return;}
    function strip(key,sum,y,height,opacity){let offset=82;return groups.map(g=>{const width=g[key]/sum*518,x=offset;offset+=width;return '<rect x="'+x+'" y="'+y+'" width="'+width+'" height="'+height+'" fill="'+groupColor(g)+'" opacity="'+opacity+'"><title>'+esc(g.name+': '+number(g[key]/sum*100,1)+'%')+'</title></rect>';}).join('');}
    $('mix-chart').innerHTML='<svg viewBox="0 0 600 90" role="img" aria-label="Tỷ trọng năm 2026 phía trên và 2025 phía dưới"><text class="mix-year" x="0" y="28">2026</text>'+strip(metric,total,9,30,1)+'<text class="mix-year" x="0" y="74">2025</text>'+strip(previousKey,previousTotal,57,24,.46)+'</svg>';
    $('mix-legend').innerHTML='<div class="mix-header"><span></span><span>Nhóm hàng</span><span>2025</span><span>2026</span><span>Δ điểm %</span></div>'+groups.map(g=>{const share=g[metric]/total*100,previous=g[previousKey]/previousTotal*100,delta=share-previous;return '<div class="mix-row"><i class="color-dot group-'+g.id+'" aria-hidden="true"></i><span>'+esc(g.name)+'</span><strong class="previous-share">'+number(previous,1)+'%</strong><strong>'+number(share,1)+'%</strong><small aria-label="Thay đổi '+number(delta,1)+' điểm phần trăm">'+(delta>0?'+':'')+number(delta,1)+'</small></div>';}).join('');
  }
  function renderComparison(){
    const key=metric==='quantity'?'previousQuantity':'previousRevenue';
    const ranked=[...model.groups].sort(sortMode==='growth'?(a,b)=>(change(b[metric],b[key])??-Infinity)-(change(a[metric],a[key])??-Infinity):(a,b)=>b[metric]-a[metric]);
    const values=ranked.flatMap(g=>comparison==='growth'?[change(g[metric],g[key])??0]:[g[metric],g[key]]),min=Math.min(0,...values),max=Math.max(1,...values),scale=v=>(v-min)/(max-min)*260,origin=scale(0);
    const bar=(value,y,height,color)=>'<rect x="'+Math.min(origin,scale(value))+'" y="'+y+'" width="'+Math.abs(scale(value)-origin)+'" height="'+height+'" rx="3" fill="'+color+'"/>';
    $('compare-caption').textContent=comparison==='growth'?'Mức thay đổi so với cùng kỳ 2025':'Quy mô tuyệt đối · cùng một thang đo';
    $('comparison-note').textContent=comparison==='growth'?'So sánh tốc độ giữa các nhóm; không tính % khi nền 2025 bằng 0 hoặc âm.':'Thanh đậm: 2026 · Thanh nhạt: 2025. Nhóm nhỏ có thể khó thấy khi chênh lệch quy mô lớn.';
    $('group-comparison').innerHTML='<div class="comparison-legend"><span>Nhóm hàng</span><span>'+(comparison==='growth'?'Tăng trưởng · Kết quả 2026':metric==='quantity'?'Sản phẩm':'Doanh thu')+'</span></div>'+ranked.map(g=>{
      const growth=change(g[metric],g[key]);
      const bars=comparison==='growth'?(growth===null?'<span class="no-baseline">Chưa có nền dương</span>':'<svg viewBox="0 0 260 32" preserveAspectRatio="none" role="img" aria-label="'+esc(g.name+': tăng trưởng '+pct(growth))+'"><line class="comparison-zero" x1="'+origin+'" y1="2" x2="'+origin+'" y2="30"/>'+bar(growth,10,12,growth<0?'var(--red, #b76c7d)':groupColor(g))+'</svg>'):'<svg viewBox="0 0 260 32" preserveAspectRatio="none" role="img" aria-label="'+esc(g.name+': 2026 '+amount(g[metric],metric)+', 2025 '+amount(g[key],metric))+'">'+bar(g[metric],2,10,groupColor(g))+bar(g[key],19,10,'#dce3ee')+'</svg>';
      return '<div class="comparison-row"><div class="comparison-name"><i class="color-dot group-'+g.id+'" aria-hidden="true"></i>'+esc(g.name)+'</div><div class="comparison-bars">'+bars+'</div><div class="comparison-number">'+(comparison==='growth'?badge(growth)+'<br><small>'+amount(g[metric],metric)+'</small>':amount(g[metric],metric)+'<br><small>2025: '+amount(g[key],metric)+'</small>')+'</div></div>';
    }).join('');
    renderInsights();
  }
  function renderInsights(){
    const key=metric==='quantity'?'previousQuantity':'previousRevenue',ranked=[...model.groups].filter(g=>g[key]>0).sort((a,b)=>change(b[metric],b[key])-change(a[metric],a[key])),fast=ranked[0],driver=[...model.groups].sort((a,b)=>(b[metric]-b[key])-(a[metric]-a[key]))[0];
    const declining=[...model.groups].filter(g=>g.quantityChange!==null&&g.quantityChange<0).sort((a,b)=>a.quantityChange-b.quantityChange),slow=ranked.at(-1),watch=declining[0]||slow;
    const item=(label,title,note,attention=false)=>'<section class="insight-item'+(attention?' attention':'')+'"><div class="insight-tag">'+esc(label)+'</div><strong>'+esc(title)+'</strong><p>'+esc(note)+'</p></section>';
    $('business-insights').innerHTML=item('Đóng góp vào chênh lệch',driver.name,(driver[metric]-driver[key]>0?'+':'')+amount(driver[metric]-driver[key],metric)+' '+(metric==='quantity'?'sản phẩm':'doanh thu')+' so với cùng kỳ; mức chênh lệch cao nhất trong danh mục.')+
      (fast?item(change(fast[metric],fast[key])>=0?'Tốc độ tăng cao nhất':'Mức giảm thấp nhất',pct(change(fast[metric],fast[key])),fast.name+' · so sánh những nhóm có nền 2025 dương.'):'')+
      (watch?item(declining.length?'Số bán cần theo dõi':'Nhóm tăng chậm nhất',declining.length?pct(watch.quantityChange):pct(change(watch[metric],watch[key])),watch.name+': doanh thu '+pct(watch.change)+', số bán '+pct(watch.quantityChange)+' so với cùng kỳ.',Boolean(declining.length)):'');
  }
  const glyphs={
    iphone:'<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4m-3 14h2"/>',
    ipad:'<rect x="3" y="2" width="18" height="20" rx="2.5"/><path d="M11 19h2"/>',
    mac:'<rect x="4" y="3" width="16" height="12" rx="1.5"/><path d="m4 15-3 5h22l-3-5M9 20h6"/>',
    watch:'<rect x="5" y="6" width="14" height="12" rx="4"/><path d="m8 6 1-5h6l1 5m-8 12 1 5h6l1-5m4-8v3m-8-4v4l3 1"/>',
    accessories:'<rect x="4" y="3" width="10" height="12" rx="2"/><path d="M7 3V1m4 2V1M9 15v4a3 3 0 0 0 6 0v-7m-2 0h4V8h-4z"/>',
    airpods:'<path d="M8 3a4 4 0 0 0-4 4v3a3 3 0 0 0 3 3h1V8H6m10-5a4 4 0 0 1 4 4v3a3 3 0 0 1-3 3h-1V8h2M8 13v5m8-5v5"/><rect x="6" y="17" width="12" height="5" rx="2"/>'
  };
  function renderCards(){
    const key=metric==='quantity'?'previousQuantity':'previousRevenue';
    $('portfolio-metric-label').textContent=(metric==='quantity'?'Số bán':'Doanh thu')+' và biến động so với cùng kỳ · Chọn nhóm để xem xu hướng';
    $('category-cards').innerHTML=model.groups.map(g=>{
      const ps=series(model,g.id,metric),v=ps.map(p=>p.current),min=Math.min(0,...v),max=Math.max(1,...v),path=v.map((x,i)=>(i?'L':'M')+(v.length===1?80:i/(v.length-1)*160).toFixed(2)+','+(36-(x-min)/(max-min)*31).toFixed(2)).join(' ');
      return '<article class="category-card group-'+g.id+'" data-selected="'+(g.id===group)+'"><div class="category-head"><strong>'+esc(g.name)+'</strong><span class="device-glyph" aria-hidden="true"><svg viewBox="0 0 24 24">'+glyphs[g.id]+'</svg></span></div><div class="category-value">'+(metric==='quantity'?number(g.quantity):money(g.revenue))+' <small>'+(metric==='quantity'?'SP':'tỷ')+'</small></div><div class="category-meta">'+badge(change(g[metric],g[key]))+'<span>so cùng kỳ</span></div><p class="category-baseline">2025 · <strong>'+amount(g[key],metric)+'</strong></p><svg class="category-spark" viewBox="0 0 160 40" preserveAspectRatio="none" aria-hidden="true"><path d="'+path+'" fill="none" stroke="'+groupColor(g)+'" stroke-width="1.8" vector-effect="non-scaling-stroke"/></svg><p class="category-note">'+(metric==='quantity'?money(g.revenue)+' tỷ doanh thu':number(g.quantity)+' sản phẩm')+'</p><button class="category-filter" data-category="'+g.id+'" aria-pressed="'+(g.id===group)+'" aria-label="Xem xu hướng '+esc(g.name)+'">'+(g.id===group?'Đang xem nhóm':'Xem xu hướng')+' <span aria-hidden="true">↗</span></button></article>';
    }).join('');
  }
  function renderTable(){
    $('business-table-body').innerHTML=[...model.groups,{...model.total,name:'Tổng cộng',change:change(model.total.revenue,model.total.previousRevenue)}].map(g=>'<tr><td>'+esc(g.name)+'</td><td>'+money(g.previousRevenue)+'</td><td>'+money(g.revenue)+'</td><td>'+badge(g.change)+'</td><td>'+number(g.previousQuantity)+'</td><td>'+number(g.quantity)+'</td></tr>').join('');
  }
  function render(){
    if(!source||!visible())return;
    needsRender=false;
    model=aggregate(source,period);$('comparison-range').textContent=shortDate(model.period.start)+'–'+shortDate(model.period.end)+' · cùng kỳ';
    $('business-coverage').textContent='Đối chiếu '+model.paired+'/'+model.expected+' ngày · dữ liệu hoàn tất đến '+shortDate(source.cutoff)+'/2026.'+(model.paired<model.expected?' Ngày thiếu được loại khỏi cả hai năm.':'');
    renderKpis();renderTrend();renderMix();renderComparison();renderCards();renderTable();
  }
  function adopt(data,live=false){
    source=validate(data);const choices=periods(source);if(!choices.some(p=>p.id===period))period='ytd';
    needsRender=true;
    $('business-period').innerHTML=choices.map(p=>'<option value="'+p.id+'">'+esc(p.name)+'</option>').join('');$('business-period').value=period;
    $('trend-group').innerHTML='<option value="all">Toàn ngành Apple</option>'+source.groups.map(g=>'<option value="'+g.id+'">'+esc(g.name)+'</option>').join('');$('trend-group').value=group;
    const stamp=new Date(source.source_as_of).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    $('analytics-status').textContent=(live&&source.source_kind==='database'?'Lịch sử từ BOT':'Bản lịch sử đã tổng hợp')+' · Nguồn cập nhật '+stamp+' · Không cộng số đang chạy trong ngày vào so sánh năm.';
    render();
  }
  async function refresh(){
    if(loading)return;loading=true;$('analytics-refresh').disabled=true;
    const startedRevision=revision;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
    try{let value;if(window.TaoDataSync)value=await window.TaoDataSync.analytics();else{const r=await fetch('/tao/dashboard/api/analytics',{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('unavailable');value=await r.json();}if(source&&value.cutoff<source.cutoff)throw Error('Older history');adopt(value,true);lastRead=startedRevision===revision?Date.now():0;}
    catch{if(source)$('analytics-status').textContent='Đang hiển thị bản lịch sử đã tổng hợp · đủ ngày đến '+shortDate(source.cutoff)+'/2026. Chưa xác nhận được dữ liệu mới hơn.';else $('analytics-status').textContent='Chưa đọc được lịch sử. Bấm làm mới để thử lại.';}
    finally{clearTimeout(timer);loading=false;$('analytics-refresh').disabled=false;if(startedRevision!==revision&&visible())refresh();}
  }
  window.TaoDataSync?.subscribe(({analytics})=>{if(analytics){adopt(analytics,true);lastRead=Date.now();}else{revision++;lastRead=0;if(visible())refresh();}});
  $('business-period').addEventListener('change',e=>{period=e.target.value;render();});
  $('trend-group').addEventListener('change',e=>{group=e.target.value;renderTrend();renderCards();});
  $('metric-switch').addEventListener('click',e=>{const b=e.target.closest('[data-metric]');if(!b)return;metric=b.dataset.metric==='quantity'?'quantity':'revenue';$('metric-switch').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderTrend();renderMix();renderComparison();renderCards();});
  $('trend-chart').addEventListener('click',e=>{const p=e.target.closest('[data-point]');if(p)readPoint(Number(p.dataset.point));});
  $('trend-chart').addEventListener('keydown',e=>{if(!['Enter',' '].includes(e.key))return;const p=e.target.closest('[data-point]');if(p){e.preventDefault();readPoint(Number(p.dataset.point));}});
  $('category-cards').addEventListener('click',e=>{const b=e.target.closest('[data-category]');if(b){group=b.dataset.category;$('trend-group').value=group;renderTrend();renderCards();$('trend-title').scrollIntoView({block:'center',behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}});
  $('comparison-mode').addEventListener('click',e=>{const b=e.target.closest('[data-compare]');if(!b)return;comparison=b.dataset.compare==='scale'?'scale':'growth';$('comparison-mode').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderComparison();});
  $('group-sort').addEventListener('change',e=>{sortMode=e.target.value==='growth'?'growth':'revenue';renderComparison();});
  $('analytics-refresh').addEventListener('click',refresh);
  $('export-business').addEventListener('click',()=>{if(!model)return;const url=URL.createObjectURL(new Blob([csv(model)],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='Tao-so-sanh-'+model.period.start+'_'+model.period.end+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  window.addEventListener('resize',()=>{if(!visible())return;clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>{if(visible())renderTrend();},150);});
  function onRoute(){if(!visible())return;if(needsRender&&source)render();if(Date.now()-lastRead>300000)refresh();}
  window.addEventListener('hashchange',onRoute);
  document.addEventListener?.('visibilitychange',onRoute);
  try{adopt(window.TAO_BUSINESS_DATA);}catch{$('analytics-status').textContent='Chưa có bản lịch sử hợp lệ. Đang kết nối dữ liệu…';}
  onRoute();
  setInterval(onRoute,300000);
})();

/* Source revenue is in VAT-inclusive millions; all displayed/exported revenue is in billions. */
'use strict';
(() => {
const Money=typeof module!=='undefined'&&module.exports?require('./money.js'):globalThis.TaoMoney;
const money=v=>Money.format(v,'million_vnd');
const metricValue=(v,metric)=>metric==='quantity'?v:Money.billions(v,'million_vnd');
const metricFormat=(v,metric)=>metric==='quantity'?fmt(v):money(v);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const integers=new Intl.NumberFormat('vi-VN',{maximumFractionDigits:0}),percentages=new Intl.NumberFormat('vi-VN',{maximumFractionDigits:1});
const fmt=v=>v===null||v===undefined?'—':integers.format(v);
const pct=v=>v===null||v===undefined?'—':percentages.format(v)+'%';
const date=s=>s.split('-').reverse().join('/');
const signed=v=>v===null||v===undefined?'—':(v>0?'+':'')+pct(v);
const badge=v=>'<span class="rv-delta '+(v>0?'rv-up':v<0?'rv-down':'rv-flat')+'">'+signed(v)+'</span>';
const headings={mom:'So tháng liền trước',yoy:'Cùng tháng năm trước',qtd:'Lũy kế quý',ytd:'Lũy kế năm',target:'Target & ước tính'};
const matrixPeriods=[['wow','Tuần','So tuần trước'],['mom','Tháng','So tháng trước'],['qtd','Quý','So cùng quý năm trước'],['ytd','Năm','So cùng kỳ năm trước']];
const metricInfo=metric=>metric==='quantity'?{name:'Số lượng bán',unit:'sản phẩm (SP)',csvUnit:'SP',sort:'số lượng bán tháng'}:{name:'Doanh thu',unit:'tỷ đồng, gồm VAT',csvUnit:'tỷ đồng, VAT',sort:'doanh thu tháng'};
function validateQuantity(row){
 for(const key of ['wow','mom','yoy','qtd','ytd']){
  const v=row?.[key];if(!v||['current','previous'].some(x=>v[x]!==null&&!Number.isSafeInteger(v[x]))||(v.growth!==null&&!Number.isFinite(v.growth)))throw Error('Invalid quantity comparison');
 }
 if(row.actual!==undefined&&row.actual!==null&&!Number.isSafeInteger(row.actual))throw Error('Invalid quantity');
}
function analysis(data,period,scope,mode){
 const metric=mode==='target'?'yoy':mode,rows=period.scopes[scope];
 const comparable=data.groups.map(g=>({...g,...rows[g.id].quantity[metric]})).filter(g=>g.current!==null&&g.previous!==null);
 const changes=comparable.map(g=>({...g,delta:g.current-g.previous}));
 const positives=changes.filter(g=>g.delta>0).sort((a,b)=>b.delta-a.delta);
 const declines=changes.filter(g=>g.delta<0).sort((a,b)=>a.delta-b.delta);
 const leader=positives[0],low=declines[0],complete=comparable.length===data.groups.length;
 const notes=[];
 const growthNote=g=>g.growth===null?'Chưa đủ cơ sở tính % tăng/giảm.':'Số lượng '+signed(g.growth)+' so với kỳ đối chiếu.';
 if(leader)notes.push({title:'Nhóm tăng số lượng nhiều nhất',value:leader.name+' · +'+fmt(leader.delta)+' SP',note:growthNote(leader)+(complete?'':' Trong các nhóm đủ dữ liệu.')});
 else notes.push({title:'Tăng trưởng số lượng',value:complete?'Chưa có nhóm tăng':'Chưa đủ kỳ so sánh',note:complete?'Số lượng các nhóm đang đi ngang hoặc giảm.':'Chờ đủ số lượng của hai kỳ để đối chiếu.'});
 if(low)notes.push({title:'Nhóm giảm số lượng nhiều nhất',value:low.name+' · '+fmt(low.delta)+' SP',note:growthNote(low)+' Ưu tiên kiểm tra tồn và chương trình bán của '+low.name+'.'+(complete?'':' Chỉ xét các nhóm đủ dữ liệu.')});
 else notes.push({title:'Diễn biến số lượng',value:complete?'Chưa có nhóm giảm':'Chưa đủ số liệu',note:complete?'Số lượng cả '+data.groups.length+' nhóm đều tăng hoặc đi ngang.':'Chờ đủ dữ liệu để kết luận toàn danh mục.'});
 const [start,end]=period.ranges[metric],days=(Date.parse(end)-Date.parse(start))/86400000+1,total=rows.total.quantity[metric].current;
 notes.push({title:'Sức bán bình quân',value:total===null||!Number.isFinite(days)||days<=0?'Chưa đủ số liệu':fmt(total/days)+' SP/ngày',note:total===null?'Chưa đủ số lượng trong kỳ đang chọn.':date(start)+' – '+date(end)+' · Tổng bán '+fmt(total)+' SP.'});
 const chartRows=data.groups.map(g=>({...g,growth:rows[g.id].quantity[metric].growth})),maximum=Math.max(10,...chartRows.map(g=>Math.abs(g.growth||0)));
 const scale=Math.ceil(maximum/10)*10;
 const chart=chartRows.map(g=>{const length=Math.abs(g.growth||0)/scale*470,x=g.growth<0?500-length:500;return '<div class="rv-growth-row"><strong>'+esc(g.name)+'</strong><svg viewBox="0 0 1000 28" preserveAspectRatio="none" role="img" aria-label="'+esc(g.name+' tăng trưởng số lượng '+signed(g.growth))+'"><rect x="0" y="5" width="1000" height="18" rx="9" fill="#f0f3f8"/><line x1="500" y1="0" x2="500" y2="28" stroke="#9caac0" stroke-width="3"/><rect x="'+x+'" y="5" width="'+length+'" height="18" rx="8" fill="'+(g.growth<0?'#bd5264':'#548675')+'"/></svg><span class="'+(g.growth<0?'rv-negative':'rv-positive')+'">'+signed(g.growth)+'</span></div>';}).join('')+'<div class="rv-chart-scale"><span>−'+pct(scale)+'</span><span>0%</span><span>+'+pct(scale)+'</span></div>';
 return {notes,chart,metric,measure:'quantity'};
}
function validate(data){
 if(data?.schema!==1||data.unit!=='million_vnd'||!data.periods?.length||!Array.isArray(data.groups))throw Error('Invalid revenue snapshot');
 if(data.iphone_n_rule!=='year-cohorts-2026-18pro-duo-2025-17-air-v1')throw Error('Outdated iPhone classification');
 if(data.model_rule!=='calendar-model-matrix-v1'||!Array.isArray(data.models)||!data.models.length)throw Error('Outdated model comparison');
 if(data.grouping_rule!=='apple-6-watch-bands-accessories-v2')throw Error('Outdated group classification');
 if(data.quantity_rule!=='source-quantity-net-v1'||data.quantity_unit!=='product')throw Error('Outdated quantity comparison');
 if(data.apple_weeks?.rule!=='apple-week-sales-v1'||!data.apple_weeks.quarters?.length)throw Error('Outdated Apple weekly data');
 for(const q of data.apple_weeks.quarters){
  if(!/^Q[1-4]Y\d{2}$/.test(q.id)||![13,14].includes(q.weeks?.length))throw Error('Invalid Apple quarter');
  for(const row of [...q.weeks,q.total]){
   if(!['complete','partial','missing','future'].includes(row.state)||!Number.isInteger(row.elapsed_days)||row.covered_days<0||row.covered_days>row.elapsed_days||row.elapsed_days>row.calendar_days)throw Error('Invalid Apple week coverage');
   for(const key of ['total',...data.groups.map(g=>g.id),...data.models.map(m=>m.id)]){
    const v=row.values?.[key];if(!v||(v.revenue!==null&&!Number.isFinite(v.revenue))||(v.quantity!==null&&!Number.isSafeInteger(v.quantity)))throw Error('Invalid Apple weekly amount');
    if(['missing','future'].includes(row.state)&&(v.revenue!==null||v.quantity!==null))throw Error('Incomplete Apple week must not show a total');
   }
  }
 }
 for(const p of data.periods)for(const scope of ['system']){
  if(!p.scopes?.[scope]?.total)throw Error('Missing scope');
  for(const row of Object.values(p.scopes[scope])){
   for(const k of ['actual','forecast','target','attainment','projected_attainment'])if(row[k]!==null&&!Number.isFinite(row[k]))throw Error('Invalid amount');
   for(const k of ['wow','mom','yoy','qtd','ytd'])if(!row[k]||['current','previous','growth'].some(x=>row[k][x]!==null&&!Number.isFinite(row[k][x])))throw Error('Invalid comparison');
   validateQuantity(row.quantity);
  }
  for(const [key] of matrixPeriods)if(!Array.isArray(p.ranges?.[key])||p.ranges[key].length!==4||p.ranges[key].some(d=>!/^\d{4}-\d{2}-\d{2}$/.test(d)))throw Error('Missing comparison dates');
  for(const m of data.models){
   if(!data.groups.some(g=>g.id===m.group&&g.details.some(d=>d.id===m.detail)))throw Error('Invalid model group');
   for(const [key] of matrixPeriods){const v=p.models?.[m.id]?.[key];if(!v||['current','previous','growth'].some(x=>v[x]!==null&&!Number.isFinite(v[x])))throw Error('Missing model comparison');}
   validateQuantity(p.models[m.id].quantity);
  }
 }
 return data;
}
function columns(period,mode){
 if(mode==='target')return ['Nhóm hàng','Đã thực hiện','Target tháng','Ước cuối tháng','Ước đạt target'];
 const [a,b,c,d]=period.ranges[mode];
 const label=s=>mode==='ytd'?'Năm '+s.slice(0,4):mode==='qtd'?'Quý '+period.quarter+'/'+s.slice(0,4):'Tháng '+Number(s.slice(5,7))+'/'+s.slice(0,4);
 return ['Nhóm hàng',label(a),label(c),'Tăng / giảm'];
}
function cells(row,mode){
 if(mode==='target')return [money(row.actual),row.target===null?'<span class="rv-missing">Chưa nhập</span>':money(row.target),money(row.forecast),pct(row.projected_attainment)];
 const v=row[mode];return [money(v.current),money(v.previous),badge(v.growth)];
}
function matrixItems(data,period,group='all',model='all',metric='revenue'){
 const values=row=>metric==='quantity'?row.quantity:row;
 const chosen=data.models.find(m=>m.id===model&&(group==='all'||m.group===group));
 if(chosen)return [{...chosen,values:values(period.models[chosen.id])}];
 if(group==='all')return [...data.groups.map(g=>({id:g.id,name:g.name,values:values(period.scopes.system[g.id])})),{id:'total',name:'Tổng Apple',total:true,values:values(period.scopes.system.total)}];
 const g=data.groups.find(g=>g.id===group);if(!g)return [];
 const active=data.models.filter(m=>m.group===group&&matrixPeriods.some(([key])=>{const v=values(period.models[m.id])[key];return v.current!==0||v.previous!==0;}));
 active.sort((a,b)=>(values(period.models[b.id]).mom.current??-Infinity)-(values(period.models[a.id]).mom.current??-Infinity)||a.name.localeCompare(b.name,'vi'));
 return [...active.map(m=>({...m,values:values(period.models[m.id])})),{id:g.id,name:'Tổng '+g.name,total:true,values:values(period.scopes.system[g.id])}];
}
function comparisonDates(period,key){const r=period.ranges[key];return {current:date(r[0])+' – '+date(r[1]),previous:date(r[2])+' – '+date(r[3])};}
function rowsPerPage(width=1440,height=1000,focused=false){return width<=760?1:Math.max(2,Math.min(10,Math.floor((height-(focused?330:470))/62)));}
function pageOf(items,index=0,size=7){
 size=Math.max(1,Math.floor(size));const pages=Math.max(1,Math.ceil(items.length/size)),page=Math.max(0,Math.min(pages-1,index));
 return {items:items.slice(page*size,(page+1)*size),page,pages,start:items.length?page*size+1:0,end:Math.min(items.length,(page+1)*size),total:items.length};
}
function matrixTable(period,items,metric='revenue'){
 const info=metricInfo(metric);
 const head=matrixPeriods.map(([key,label,basis])=>{const d=comparisonDates(period,key);return '<th scope="col"><strong>'+label+'</strong><span>'+d.current+'</span><small>'+basis+'<br>'+d.previous+'</small></th>';}).join('');
 const renderRows=rows=>rows.map(item=>'<tr'+(item.total?' class="rv-matrix-total"':'')+'><th scope="row">'+esc(item.name)+'</th>'+matrixPeriods.map(([key,label,basis])=>{
  const v=item.values[key],d=comparisonDates(period,key),reason=v.current===null||v.previous===null?'Thiếu dữ liệu kỳ so sánh':v.previous<=0?'Nền đối chiếu ≤ 0':'';
  return '<td><div class="rv-mobile-period"><strong>'+label+'</strong><span>'+d.current+'</span></div><div class="rv-matrix-numbers"><strong class="rv-matrix-value">'+metricFormat(v.current,metric)+'</strong>'+badge(v.growth)+'</div><span class="rv-matrix-base">Đối chiếu: '+metricFormat(v.previous,metric)+'</span>'+(reason?'<small class="rv-matrix-warning">'+reason+'</small>':'')+'<small class="rv-mobile-period">'+basis+'<br>'+d.previous+'</small></td>';
 }).join('')+'</tr>').join('');
 const body=renderRows(items.filter(item=>!item.total)),totals=items.filter(item=>item.total);
 return '<div class="rv-matrix-scroll" tabindex="0" role="region" aria-label="'+info.name+' · so sánh đồng thời tuần, tháng, quý, năm"><table class="rv-matrix"><caption class="sr-only">'+info.name+' theo nhóm và model · '+info.unit+'. Mỗi cột có số kỳ này, kỳ đối chiếu và phần trăm tăng giảm.</caption><thead><tr><th scope="col">Nhóm / Model<small>'+info.name+' · '+info.unit+'</small><small>Kỳ này · Đối chiếu · Tăng/giảm</small></th>'+head+'</tr></thead><tbody>'+body+'</tbody>'+(totals.length?'<tfoot>'+renderRows(totals)+'</tfoot>':'')+'</table></div>';
}
function matrixCsv(data,period,group='all',model='all',metric='revenue'){
 const info=metricInfo(metric);
 const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const lines=[['Nhóm / Model','Kỳ','Cách đối chiếu','Từ ngày','Đến ngày','Đối chiếu từ','Đối chiếu đến',info.name+' kỳ này ('+info.csvUnit+')',info.name+' đối chiếu ('+info.csvUnit+')','Tăng / giảm (%)']];
 for(const item of matrixItems(data,period,group,model,metric))for(const [key,label,basis] of matrixPeriods){const v=item.values[key];lines.push([item.name,label,basis,...period.ranges[key],metricValue(v.current,metric),metricValue(v.previous,metric),v.growth]);}
 return '\ufeff'+lines.map(r=>r.map(quote).join(',')).join('\r\n');
}
function weeklyKey(data,group='all',model='all'){
 const chosen=data.models.find(m=>m.id===model&&(group==='all'||m.group===group));
 return chosen?{id:chosen.id,name:chosen.name}:group==='all'?{id:'total',name:'Toàn ngành Apple'}:{id:group,name:data.groups.find(g=>g.id===group)?.name||group};
}
function weeklyState(row){return row.state==='future'?'Chưa đến':row.state==='missing'?'Thiếu '+(row.elapsed_days-row.covered_days)+' ngày':row.covered_days+'/'+row.calendar_days+' ngày';}
function weeklyAverage(row,key,metric){const value=row.values[key][metric];return value===null||!row.elapsed_days?null:value/row.elapsed_days;}
// Only comparable time periods become points. Different horizons are never joined.
function comparisonSeries(data,period,group='all',model='all',metric='revenue',comparison='yoy'){
 const mode=['mom','yoy','qtd','ytd'].includes(comparison)?comparison:'yoy',key=weeklyKey(data,group,model),year=period.id.slice(0,4);
 const available=data.periods.filter(p=>p.id<=period.id&&p.id.startsWith(year)).sort((a,b)=>a.id.localeCompare(b.id));
 // Keep the full calendar visible. Missing/future months are gaps, never zeros.
 const months=Array.from({length:12},(_,i)=>year+'-'+String(i+1).padStart(2,'0'));
 const elapsed=months.filter(id=>id<=period.id);
 const slots=mode==='qtd'?elapsed.filter((id,i)=>Number(id.slice(5))%3===0||i===elapsed.length-1):months;
 const points=slots.map(id=>{
  const p=available.find(p=>p.id===id),row=p&&(p.models[key.id]||p.scopes.system[key.id]),v=(metric==='quantity'?row?.quantity:row)?.[mode];
  const ranges=p?.ranges[mode]||null;
  return {key:id,label:mode==='qtd'?'Q'+Math.ceil(Number(id.slice(5))/3):'T'+Number(id.slice(5)),current:v?.current??null,previous:v?.previous??null,ranges,
   state:p?(Number(p.end.slice(8))<p.month_days||(mode==='qtd'&&Number(p.id.slice(5))%3!==0)?'partial':'available'):id>period.id?'future':'missing',note:p?'Chốt '+date(p.end):id>period.id&&data.periods.some(x=>x.id===id)?'Sau tháng chốt đang chọn':'Chưa có dữ liệu'};
 });
 return {name:key.name,metric,comparison:mode,points,currentLabel:mode==='mom'?'Tháng đang xét':year,previousLabel:mode==='mom'?'Tháng liền trước':String(Number(year)-1),
  caption:mode==='qtd'?'Theo quý · cùng kỳ năm trước':mode==='ytd'?'Lũy kế đến từng tháng · cùng kỳ năm trước':mode==='mom'?'Theo tháng · đối chiếu cùng khoảng ngày':'Theo tháng · cùng kỳ năm trước'};
}
function weeklySeries(data,quarter,group='all',model='all',metric='revenue'){
 const key=weeklyKey(data,group,model),previousQuarter=data.apple_weeks.quarters.find(q=>q.year===quarter.year-1&&q.id.slice(0,2)===quarter.id.slice(0,2));
 const points=quarter.weeks.map(row=>{
  const other=previousQuarter?.weeks.find(w=>w.week===row.week);
  // A full prior week cannot be compared with a current partial/missing/future week.
  const comparable=row.state==='complete'&&other?.state==='complete'&&row.calendar_days===other.calendar_days;
  const current=['complete','partial'].includes(row.state)?row.values[key.id][metric]:null;
  return {key:String(row.week),label:'W'+row.week,current,previous:comparable?other.values[key.id][metric]:null,state:row.state,
   ranges:[row.start,row.through||row.end,...(comparable?[other.start,other.end]:[null,null])],
   note:row.state==='partial'?'Đến '+date(row.through)+' · '+weeklyState(row)+' · chưa đối chiếu tuần đủ ngày':weeklyState(row)};
 });
 return {name:key.name,metric,comparison:'weekly',points,currentLabel:quarter.id,previousLabel:previousQuarter?.id||'Cùng quý Apple năm trước',caption:quarter.weeks.length+' tuần Apple · cùng quý năm trước'};
}
function lineGeometry(points,width=760,height=276,metric='revenue'){
 const values=points.flatMap(p=>[metricValue(p.current,metric),metricValue(p.previous,metric)]).filter(Number.isFinite);
 let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max)max=min+1;
 const rough=(max-min)/4,power=10**Math.floor(Math.log10(rough)),factor=rough/power;
 const step=Math.max(metric==='quantity'?1:0,(factor<=1?1:factor<=2?2:factor<=5?5:10)*power);
 min=Math.floor(min/step)*step;max=Math.ceil(max/step)*step;
 const tick=v=>new Intl.NumberFormat('vi-VN',{maximumFractionDigits:Math.min(12,Math.max(0,-Math.floor(Math.log10(step))))}).format(v);
 const left=Math.min(width*.32,Math.max(46,Math.max(tick(min).length,tick(max).length)*7+12)),right=16,top=16,bottom=width<600&&points.length>8?48:38;
 return {width,height,min,max,step,left,right,top,bottom,tick,x:i=>left+(points.length<=1?(width-left-right)/2:i/(points.length-1)*(width-left-right)),y:v=>top+(max-v)/(max-min)*(height-top-bottom)};
}
function lineReadout(series,index){
 const p=series.points[index];if(!p)return '';
 const unit=series.metric==='quantity'?' SP':' tỷ',range=side=>{const i=side==='current'?0:2;return p.ranges?.[i]&&p.ranges?.[i+1]?date(p.ranges[i])+' – '+date(p.ranges[i+1]):'';};
 const value=(side,label)=>'<span class="rv-line-reading '+side+'"><small>'+esc(label)+'</small><strong>'+metricFormat(p[side],series.metric)+(p[side]===null?'':unit)+'</strong><small>'+esc(range(side))+'</small></span>';
 const growth=p.current!==null&&p.previous>0?(p.current/p.previous-1)*100:null;
 return '<div class="rv-line-reading-head"><strong>'+esc(p.label)+'</strong><span>'+esc(p.note)+'</span>'+badge(growth)+'</div><div class="rv-line-reading-values">'+value('current',series.currentLabel)+value('previous',series.previousLabel)+'</div>';
}
function lineChart(series,width=760,height=276,selected=-1){
 const points=series.points,c=lineGeometry(points,width,height,series.metric);
 if(selected<0)selected=Math.max(0,points.findLastIndex(p=>p.current!==null||p.previous!==null));
 const n=points.length,hasValues=points.some(p=>Number.isFinite(p.current)||Number.isFinite(p.previous));
 let grid='',paths='',markers='',labels='',hits='';
 for(let i=0;i<=Math.round((c.max-c.min)/c.step);i++){
  const v=c.min+i*c.step,y=c.y(v);
  grid+='<line class="rv-line-grid" x1="'+c.left+'" x2="'+(width-c.right)+'" y1="'+y+'" y2="'+y+'"/><text class="rv-line-axis" x="'+(c.left-9)+'" y="'+(y+4)+'" text-anchor="end">'+esc(c.tick(v))+'</text>';
 }
 for(const side of ['previous','current']){
  let d='',connected=false;
  points.forEach((p,i)=>{const v=metricValue(p[side],series.metric);if(!Number.isFinite(v)){connected=false;return;}
   const x=c.x(i),y=c.y(v);d+=(connected?' L':' M')+x.toFixed(2)+','+y.toFixed(2);connected=true;
   markers+='<circle class="rv-line-dot '+side+(p.state==='partial'?' partial':'')+'" data-line-dot="'+i+'" cx="'+x+'" cy="'+y+'" r="'+(i===selected?4.5:3)+'"/>';
  });
  if(d)paths+='<path class="rv-line-path '+side+'" d="'+d.trim()+'"/>';
 }
 points.forEach((p,i)=>{
  const labelY=height-(width<600&&n>8?20:12);
  labels+='<text class="rv-line-axis rv-line-x" x="'+c.x(i)+'" y="'+labelY+'" text-anchor="'+(width<600&&n>8?'end':'middle')+'"'+(width<600&&n>8?' transform="rotate(-45 '+c.x(i)+' '+labelY+')"':'')+'>'+esc(p.label)+'</text>';
  const left=i===0?c.left:(c.x(i-1)+c.x(i))/2,right=i===n-1?width-c.right:(c.x(i)+c.x(i+1))/2;
  const accessible=p.label+' · '+series.currentLabel+': '+metricFormat(p.current,series.metric)+' · '+series.previousLabel+': '+metricFormat(p.previous,series.metric)+' · '+p.note;
  hits+='<rect class="rv-line-hit" data-line-point="'+i+'" x="'+left+'" y="'+c.top+'" width="'+(right-left)+'" height="'+(height-c.top-c.bottom)+'" tabindex="'+(i===selected?'0':'-1')+'" role="button" aria-pressed="'+(i===selected)+'" aria-label="'+esc(accessible)+'"><title>'+esc(accessible)+'</title></rect>';
 });
 return '<div class="rv-line-caption"><strong>'+esc(series.caption)+'</strong><span>'+esc(metricInfo(series.metric).unit)+'</span></div><div class="rv-line-legend"><span><i class="current"></i>'+esc(series.currentLabel)+'</span><span><i class="previous"></i>'+esc(series.previousLabel)+'</span></div>'+
  (!hasValues?'<p class="rv-line-empty">Chưa đủ dữ liệu trong kỳ đang chọn.</p>':'')+
  '<svg class="rv-line-svg" viewBox="0 0 '+width+' '+height+'" role="group" aria-label="'+esc(series.name+' · '+series.caption+' · '+metricInfo(series.metric).unit)+'">'+grid+paths+markers+labels+'<line class="rv-line-cursor" x1="'+c.x(selected)+'" x2="'+c.x(selected)+'" y1="'+c.top+'" y2="'+(height-c.bottom)+'"/>'+hits+'</svg>'+
  '<div class="rv-line-readout" role="status" aria-live="polite">'+lineReadout(series,selected)+'</div>';
}
function lineCsv(series){
 const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const rows=[['Nhóm / Model','Kỳ','Hiện tại','Đối chiếu','Từ ngày','Đến ngày','Đối chiếu từ','Đối chiếu đến',metricInfo(series.metric).name+' hiện tại ('+metricInfo(series.metric).csvUnit+')',metricInfo(series.metric).name+' đối chiếu ('+metricInfo(series.metric).csvUnit+')','Trạng thái']];
 for(const p of series.points)rows.push([series.name,p.label,series.currentLabel,series.previousLabel,...(p.ranges||['','','','']),metricValue(p.current,series.metric),metricValue(p.previous,series.metric),p.note]);
 return '\ufeff'+rows.map(row=>row.map(quote).join(',')).join('\r\n');
}
function weeklyTable(quarter,rows,key,metric='revenue'){
 const info=metricInfo(metric),avg=v=>metric==='revenue'?money(v):v===null?'—':new Intl.NumberFormat('vi-VN',{maximumFractionDigits:1}).format(v);
 const short=s=>date(s).slice(0,5),renderRow=(row,total=false)=>'<tr class="rv-week-'+(total?'total':row.state)+'"><th scope="row">'+(total?'Tổng '+esc(quarter.id):'W'+row.week)+'<small>'+short(row.start)+' – '+short(row.end)+'</small></th><td class="rv-week-value">'+metricFormat(row.values[key.id][metric],metric)+'</td><td>'+avg(weeklyAverage(row,key.id,metric))+'</td><td><span class="rv-week-state">'+weeklyState(row)+'</span></td></tr>';
 return '<div class="rv-week-scroll" tabindex="0" role="region" aria-label="Sức bán theo tuần Apple"><table class="rv-week-table"><caption class="sr-only">'+esc(key.name)+' · '+esc(quarter.id)+' · '+info.unit+'</caption><thead><tr><th scope="col">Tuần Apple</th><th scope="col">'+info.name+'<small>'+info.unit+'</small></th><th scope="col">Bình quân/ngày</th><th scope="col">Dữ liệu</th></tr></thead><tbody>'+rows.map(row=>renderRow(row)).join('')+'</tbody><tfoot>'+renderRow(quarter.total,true)+'</tfoot></table></div>';
}
function weeklyCsv(quarter,key,metric='revenue'){
 const info=metricInfo(metric),quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const lines=[['Nhóm / Model','Năm Apple','Quý','Tuần','Từ ngày','Đến ngày','Chốt đến','Ngày đã có','Trạng thái',info.name+' ('+info.csvUnit+')','Bình quân/ngày ('+info.csvUnit+')']];
 for(const row of [...quarter.weeks,{...quarter.total,week:'Tổng'}])lines.push([key.name,quarter.year,quarter.id,row.week,row.start,row.end,row.through,row.covered_days,weeklyState(row),metricValue(row.values[key.id][metric],metric),metricValue(weeklyAverage(row,key.id,metric),metric)]);
 return '\ufeff'+lines.map(row=>row.map(quote).join(',')).join('\r\n');
}
function quarterOverviewItems(data,group='all',model='all'){
 const key=weeklyKey(data,group,model);
 return key.id==='total'?[...data.groups.map(g=>({id:g.id,name:g.name})),{id:'total',name:'Tổng Apple',total:true}]:[key];
}
function quarterOverviewTable(data,quarter,group='all',model='all'){
 const items=quarterOverviewItems(data,group,model),short=s=>date(s).slice(0,5);
 const head=quarter.weeks.map(w=>'<th scope="col" class="rv-quarter-'+w.state+'"><strong>W'+w.week+'</strong><small>'+short(w.start)+'<br>'+short(w.end)+'</small><span>'+weeklyState(w)+'</span></th>').join('');
 const cell=(row,item,total=false)=>{const v=row.values[item.id];return '<td class="'+(total?'rv-quarter-total':'rv-quarter-'+row.state)+'" title="'+esc((total?'Tổng '+quarter.id:'W'+row.week)+' · '+weeklyState(row))+'"><strong class="rv-quarter-revenue"><span class="sr-only">Doanh thu: </span>'+money(v.revenue)+'</strong><span class="rv-quarter-quantity"><span class="sr-only">Số lượng: </span>'+fmt(v.quantity)+(v.quantity===null?'':' SP')+'</span></td>';};
 const renderRows=rows=>rows.map(item=>'<tr><th scope="row">'+esc(item.name)+'</th>'+quarter.weeks.map(w=>cell(w,item)).join('')+cell(quarter.total,item,true)+'</tr>').join('');
 return '<div class="rv-quarter-scroll" tabindex="0" role="region" aria-label="Tổng quan '+quarter.weeks.length+' tuần '+esc(quarter.id)+'"><table class="rv-quarter-table"><caption class="sr-only">'+esc(quarter.id)+' · Doanh thu: tỷ đồng, gồm VAT · Số lượng: sản phẩm (SP)</caption><colgroup><col class="rv-quarter-name"><col span="'+quarter.weeks.length+'"><col class="rv-quarter-sum"></colgroup><thead><tr><th scope="col">Nhóm / Model<small>DT · tỷ đồng, VAT<br>SL · SP</small></th>'+head+'<th scope="col" class="rv-quarter-total">Tổng quý<small>'+esc(quarter.id)+'</small><span>'+weeklyState(quarter.total)+'</span></th></tr></thead><tbody>'+renderRows(items.filter(x=>!x.total))+'</tbody>'+(items.some(x=>x.total)?'<tfoot>'+renderRows(items.filter(x=>x.total))+'</tfoot>':'')+'</table></div>';
}
function quarterOverviewCsv(data,quarter,group='all',model='all'){
 const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"',rows=[...quarter.weeks,quarter.total];
 const lines=[['Nhóm / Model',...rows.flatMap(w=>{const label=(w.week?'W'+w.week:'Tổng '+quarter.id)+' · '+date(w.start)+'–'+date(w.end)+' · '+weeklyState(w)+' · chốt '+(w.through?date(w.through):'—');return [label+' · Doanh thu (tỷ đồng, VAT)',label+' · Số lượng (SP)'];})]];
 for(const item of quarterOverviewItems(data,group,model))lines.push([item.name,...rows.flatMap(w=>[Money.billions(w.values[item.id].revenue,'million_vnd'),w.values[item.id].quantity])]);
 return '\ufeff'+lines.map(row=>row.map(quote).join(',')).join('\r\n');
}
function table(period,scope,mode,items,label){
 const rows=period.scopes[scope],heads=columns(period,mode);
 const ranges=mode==='target'?null:period.ranges[mode],short=s=>s.slice(8)+'/'+s.slice(5,7);
 const dates=i=>ranges&&(i===1||i===2)?'<small>'+short(ranges[i===1?0:2])+' – '+short(ranges[i===1?1:3])+'</small>':'';
 return '<div class="rv-table-wrap"><table class="rv-table '+(mode==='target'?'rv-target-table':'rv-compare-table')+'"><caption class="sr-only">'+esc(label)+' · Tỷ đồng</caption><thead><tr>'+heads.map((h,i)=>'<th scope="col"'+(i===0?' class="rv-name"':'')+'>'+esc(h)+dates(i)+'</th>').join('')+'</tr></thead><tbody>'+items.map(item=>'<tr'+(item.total?' class="rv-total"':'')+'><th scope="row" class="rv-name">'+esc(item.name)+'</th>'+cells(rows[item.id],mode).map((v,i)=>'<td data-label="'+esc(heads[i+1])+'"'+(i===0?' class="rv-current"':'')+'>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}
function csv(data,period,scope){
 const rows=period.scopes[scope],items=data.groups.flatMap(g=>[{id:g.id,name:g.name},...g.details]);items.push({id:'nonphone',name:'Non-phone'},{id:'total',name:'Tổng Apple'});
 const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const header=['Phạm vi','Ngày chốt','Đơn vị','Nhóm / dòng sản phẩm','Tháng trước cùng ngày','Tháng này cùng ngày','% tăng tháng','Cùng tháng năm trước','Thực tế tháng','% tăng cùng tháng','Quý năm trước','Quý năm nay','% tăng quý','Lũy kế năm trước','Lũy kế năm nay','% tăng năm','Target tháng','Ước cuối tháng','% ước đạt target'];
 return '\ufeff'+[header,...items.map(i=>{const r=rows[i.id];return ['Toàn hệ thống',period.end,'Tỷ đồng, gồm VAT',i.name,...['mom','yoy','qtd','ytd'].flatMap(k=>[Money.billions(r[k].previous,'million_vnd'),Money.billions(r[k].current,'million_vnd'),r[k].growth]),Money.billions(r.target,'million_vnd'),Money.billions(r.forecast,'million_vnd'),r.projected_attainment];})].map(r=>r.map(quote).join(',')).join('\r\n');
}
const api={validate,columns,cells,csv,analysis,matrixPeriods,matrixItems,matrixTable,matrixCsv,rowsPerPage,pageOf,weeklyKey,weeklyState,weeklyAverage,weeklyTable,weeklyCsv,quarterOverviewItems,quarterOverviewTable,quarterOverviewCsv,comparisonSeries,weeklySeries,lineGeometry,lineChart,lineReadout,lineCsv};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
if(typeof document==='undefined')return;
window.TaoRevenue=api;
const $=id=>document.getElementById(id);
if(!$('page-revenue'))return;
const scope='system';
let data=null,selected='',mode='yoy',group='all',model='all',metric='revenue',detailGroup='iphone',pageIndex=0,focusMode='',busy=false,lastRead=0;
let focusScroll=0,inertBefore=[],focusReturn=null,matrixSize=null;
let displayMode='matrix',fiscalYear=null,appleQuarter='',weeklyLayout='overview';
let matrixView='chart',chartComparison='yoy';
const chartState=new Map();
let needsRender=true,snapshotLoad=null,resizeTimer=null,wasVisible=false,followLatest=true;
let revision=0;
let retryTimer=null,retryDelay=5000,loadState='saved';
const visible=()=>!document.hidden&&(location.hash==='#revenue'||window.TAO_REVENUE_PREVIEW);
const markup=new Map();
function put(id,value){if(markup.get(id)!==value){$(id).innerHTML=value;markup.set(id,value);}}
const legacyFocus=()=>['summary','detail'].includes(focusMode);
const weeklyActive=()=>displayMode==='weekly'&&!legacyFocus();
function setFocus(value,restore=true){
 const next=['matrix','weekly','summary','detail'].includes(value)?value:'';
 if(next&&!focusMode){
  focusScroll=window.scrollY||0;focusReturn=document.activeElement;
  inertBefore=Array.from(document.querySelectorAll?.('body > :not(main), main > :not(#page-revenue)')||[]).map(el=>[el,el.inert]);
  inertBefore.forEach(([el])=>{el.inert=true;});
 }
 focusMode=next;
 if(['matrix','weekly'].includes(next))displayMode=next;
 $('page-revenue').setAttribute('data-focus',focusMode);
 document.body?.classList?.toggle('rv-focus-active',Boolean(focusMode));
 $('revenue-focus').textContent=focusMode?'Thoát':'Vừa màn hình';
 $('revenue-focus').setAttribute('aria-label',focusMode?'Thoát chế độ vừa màn hình (Esc)':'Xem bảng vừa màn hình');
 $('revenue-focus').setAttribute('aria-pressed',String(Boolean(focusMode)));
 $('revenue-focus-picker').hidden=!focusMode;$('revenue-focus-table').value=focusMode||'matrix';
 if(legacyFocus())$('revenue-secondary').open=true;
 if(!focusMode){inertBefore.forEach(([el,was])=>{el.inert=was;});inertBefore=[];if(restore){window.scrollTo?.({top:focusScroll,behavior:'instant'});focusReturn?.focus?.();}}
 render();
 if(focusMode)$('revenue-focus').focus?.();
}
function renderMatrix(p){
 if(matrixView==='table'){
 const items=matrixItems(data,p,group,model,metric),totals=items.filter(x=>x.total),rows=items.filter(x=>!x.total),width=window.innerWidth||1440;
 const size=width>760&&group==='all'&&model==='all'?Math.max(1,rows.length):Math.max(1,rowsPerPage(width,window.innerHeight||1000,focusMode==='matrix')-(width>760?totals.length:0));
 if(matrixSize&&matrixSize!==size)pageIndex=Math.floor(pageIndex*matrixSize/size);
 matrixSize=size;const page=pageOf(rows,pageIndex,size);
 pageIndex=page.page;$('revenue-matrix').innerHTML=matrixTable(p,[...page.items,...totals],metric);
 $('revenue-page-label').textContent='Dòng '+page.start+'–'+page.end+' / '+page.total+(page.pages>1?' · Trang '+(page.page+1)+'/'+page.pages:'');
 $('revenue-page-prev').disabled=page.page===0;$('revenue-page-next').disabled=page.page===page.pages-1;
 $('revenue-page-prev').hidden=page.pages===1;$('revenue-page-next').hidden=page.pages===1;
 }
 $('revenue-matrix').hidden=matrixView!=='table';$('revenue-pager').hidden=matrixView!=='table';
 $('revenue-matrix-legend').hidden=matrixView!=='table';$('revenue-chart-controls').hidden=matrixView!=='chart';$('revenue-line-chart').hidden=matrixView!=='chart';
 for(const view of ['chart','table'])$('revenue-matrix-view-'+view).setAttribute('aria-pressed',String(matrixView===view));
 $('revenue-chart-comparison').value=chartComparison;
 if(matrixView==='chart'&&!weeklyActive())renderLine('revenue-line-chart',comparisonSeries(data,p,group,model,metric,chartComparison));
}
function renderLine(id,series){
 const host=$(id),width=Math.max(240,Math.min(1100,host.clientWidth||Math.min(960,(window.innerWidth||1000)-64)));
 const height=focusMode?Math.max(160,Math.min(320,(window.innerHeight||900)-(width<600?460:390))):width<600?230:276;
 const saved=chartState.get(id),signature=series.name+'|'+series.comparison+'|'+series.currentLabel+'|'+selected+'|'+series.points.map(p=>p.key).join(',');
 const index=saved?.signature===signature?saved.index:Math.max(0,series.points.findLastIndex(p=>p.current!==null||p.previous!==null));
 chartState.set(id,{series,index,signature});host.innerHTML=lineChart(series,width,height,index);
}
function selectLinePoint(id,index,focus=false){
 const state=chartState.get(id),host=$(id);if(!state)return;
 const next=Math.max(0,Math.min(state.series.points.length-1,index));
 if(!Number.isInteger(next)||(!focus&&state.index===next))return;
 state.index=next;
 const readout=host.querySelector?.('.rv-line-readout');if(readout)readout.innerHTML=lineReadout(state.series,state.index);
 host.querySelectorAll?.('[data-line-point]').forEach(el=>{const active=Number(el.getAttribute('data-line-point'))===state.index;el.setAttribute('aria-pressed',String(active));el.setAttribute('tabindex',active?'0':'-1');if(active&&focus)el.focus();});
 host.querySelectorAll?.('[data-line-dot]').forEach(el=>el.setAttribute('r',Number(el.getAttribute('data-line-dot'))===state.index?'4.5':'3'));
 const active=host.querySelector?.('[data-line-point="'+state.index+'"]'),cursor=host.querySelector?.('.rv-line-cursor');
 if(active&&cursor){const svg=host.querySelector('.rv-line-svg'),box=svg.viewBox.baseVal,c=lineGeometry(state.series.points,box.width,box.height,state.series.metric);cursor.setAttribute('x1',c.x(state.index));cursor.setAttribute('x2',c.x(state.index));}
}
function selectedAppleQuarter(){
 const all=data.apple_weeks.quarters;
 if(!all.some(q=>q.year===fiscalYear))fiscalYear=all.at(-1).year;
 const available=all.filter(q=>q.year===fiscalYear),q=available.find(q=>q.id===appleQuarter)||available.at(-1);
 appleQuarter=q.id;return q;
}
function renderWeekly(){
 const q=selectedAppleQuarter(),key=weeklyKey(data,group,model),years=[...new Set(data.apple_weeks.quarters.map(q=>q.year))].reverse();
 $('revenue-apple-year').innerHTML=years.map(year=>'<option value="'+year+'">Y'+String(year).slice(-2)+'</option>').join('');$('revenue-apple-year').value=String(fiscalYear);
 $('revenue-apple-quarter').innerHTML=data.apple_weeks.quarters.filter(q=>q.year===fiscalYear).map(q=>'<option value="'+q.id+'">'+q.id+'</option>').join('');$('revenue-apple-quarter').value=q.id;
 $('revenue-week-title').textContent=key.name+' · '+q.id;
 if(weeklyLayout==='overview')put('revenue-week-overview',quarterOverviewTable(data,q,group,model));
 $('revenue-week-overview').hidden=weeklyLayout!=='overview';$('revenue-week-detail').hidden=weeklyLayout!=='detail';
 $('revenue-week-chart').hidden=weeklyLayout!=='chart';
 $('revenue-week-metrics').hidden=weeklyLayout==='overview';
 $('revenue-week-layout-overview').textContent='Tổng quan '+q.weeks.length+' tuần';
 for(const layout of ['overview','detail','chart'])$('revenue-week-layout-'+layout).setAttribute('aria-pressed',String(weeklyLayout===layout));
 if(weeklyLayout==='detail')put('revenue-weekly',weeklyTable(q,q.weeks,key,metric));
 if(weeklyLayout==='chart'&&weeklyActive())renderLine('revenue-week-chart',weeklySeries(data,q,group,model,metric));
 for(const key of ['revenue','quantity'])$('revenue-week-metric-'+key).setAttribute('aria-pressed',String(key===metric));
}
function kpi(label,value,note,tone=''){return '<article class="rv-kpi '+tone+'"><span>'+label+'</span><strong>'+value+'</strong><small>'+note+'</small></article>';}
function render(){
 if(!data||!visible())return;
 needsRender=false;
 const p=data.periods.find(x=>x.id===selected)||data.periods.at(-1);selected=p.id;
 const r=p.scopes[scope].total;
 const isWeekly=weeklyActive();
 $('page-revenue').setAttribute('data-view',isWeekly?'weekly':'matrix');
 $('revenue-month-field').hidden=isWeekly;$('revenue-year-field').hidden=!isWeekly;$('revenue-quarter-field').hidden=!isWeekly;
 $('revenue-matrix-panel').hidden=isWeekly;$('revenue-week-panel').hidden=!isWeekly;
 $('revenue-secondary').hidden=isWeekly;$('revenue-status').hidden=isWeekly;
 $('revenue-mode-matrix').setAttribute('aria-pressed',String(displayMode==='matrix'));$('revenue-mode-weekly').setAttribute('aria-pressed',String(displayMode==='weekly'));
 put('revenue-month',data.periods.slice().reverse().map(x=>'<option value="'+esc(x.id)+'">'+Number(x.id.slice(5))+'/'+x.id.slice(0,4)+'</option>').join(''));$('revenue-month').value=selected;
 put('revenue-group','<option value="all">Tổng quan 6 nhóm hàng</option>'+data.groups.map(g=>'<option value="'+esc(g.id)+'">'+esc(g.name)+'</option>').join(''));$('revenue-group').value=group;
 const available=data.models.filter(m=>group==='all'||m.group===group);
 if(!available.some(m=>m.id===model))model='all';
 put('revenue-model','<option value="all">'+(group==='all'?'Tổng quan nhóm hàng':isWeekly?'Tổng nhóm':'Tất cả model trong nhóm')+'</option>'+data.groups.filter(g=>group==='all'||g.id===group).map(g=>'<optgroup label="'+esc(g.name)+'">'+available.filter(m=>m.group===g.id).map(m=>'<option value="'+esc(m.id)+'">'+esc(m.name)+'</option>').join('')+'</optgroup>').join(''));$('revenue-model').value=model;
 const info=metricInfo(metric);if(isWeekly)renderWeekly();else if(!legacyFocus())renderMatrix(p);
 for(const key of ['revenue','quantity'])$('revenue-metric-'+key).setAttribute('aria-pressed',String(key===metric));
 const chosen=data.models.find(m=>m.id===model),chosenGroup=data.groups.find(g=>g.id===group);
 $('revenue-matrix-title').textContent=chosen?chosen.name:chosenGroup?(matrixView==='chart'?'':'Các model ')+chosenGroup.name:'Toàn ngành Apple';
 $('revenue-view').value=mode;
 const displayInfo=legacyFocus()?metricInfo('revenue'):info;
 $('revenue-range').textContent='Chốt '+date(isWeekly?selectedAppleQuarter().total.through:p.end)+' · '+(isWeekly&&weeklyLayout==='overview'?'Doanh thu: tỷ đồng, gồm VAT · Số lượng: SP':displayInfo.name+' · '+displayInfo.unit);
 $('revenue-title').textContent=focusMode==='summary'?'Tổng hợp & target':focusMode==='detail'?'Chi tiết dòng sản phẩm':isWeekly?'Sức bán theo tuần Apple':matrixView==='chart'?'Xu hướng & so sánh':'Theo dõi model';
 $('revenue-export').textContent=legacyFocus()?'Xuất báo cáo ↓':(isWeekly?weeklyLayout==='chart':matrixView==='chart')?'Xuất số liệu biểu đồ ↓':isWeekly?'Xuất các tuần ↓':'Xuất tất cả dòng ↓';
 $('revenue-export').disabled=false;
 if(isWeekly||(!$('revenue-secondary').open&&!legacyFocus()))return;
 $('revenue-kpis').className='rv-kpis'+(mode==='target'?' rv-target-kpis':'');
 if(mode==='target'){
  $('revenue-kpis').innerHTML=kpi('Đã thực hiện',money(r.actual),'Doanh thu tháng đến '+date(p.end),'rv-featured')+
   kpi('Target tháng',r.target===null?'Chưa nhập':money(r.target),'Thực hiện '+pct(r.attainment))+
   kpi('Ước cuối tháng',money(r.forecast),'Theo bình quân '+p.forecast_days+' ngày hoàn tất')+
   kpi('Ước đạt target',pct(r.projected_attainment),r.target===null?'Chưa có target tháng này':'Ước cuối tháng / Target');
 }else{
  const comparison=r[mode],headers=columns(p,mode),delta=comparison.current===null||comparison.previous===null?null:comparison.current-comparison.previous;
  $('revenue-kpis').innerHTML=kpi('Doanh thu · '+headers[1],money(comparison.current),'Tỷ đồng · '+headings[mode],'rv-featured')+
   kpi('Tăng / giảm',signed(comparison.growth),delta===null?'Chưa đủ số liệu đối chiếu':(delta>=0?'Tăng ':'Giảm ')+money(Math.abs(delta))+' tỷ so với kỳ đối chiếu')+
   kpi('Đối chiếu · '+headers[2],money(comparison.previous),'Tỷ đồng · cùng khoảng ngày');
 }
 const insights=analysis(data,p,scope,mode);
 $('revenue-chart-title').textContent='Tăng trưởng số lượng · '+headings[insights.metric];
 $('revenue-growth-chart').innerHTML=insights.chart;
 $('revenue-insights').innerHTML=insights.notes.map(n=>'<article><span>'+esc(n.title)+'</span><strong>'+esc(n.value)+'</strong><p>'+esc(n.note)+'</p></article>').join('');
 const items=data.groups.map(g=>({id:g.id,name:g.name}));items.push({id:'nonphone',name:'Ngoài iPhone',total:true},{id:'total',name:'Tổng Apple',total:true});
 $('revenue-summary').innerHTML=table(p,scope,mode,items,headings[mode]);
 const detailMode=mode==='target'?'yoy':mode;
 $('revenue-detail-group').innerHTML=data.groups.map(g=>'<option value="'+esc(g.id)+'">'+esc(g.name)+'</option>').join('');$('revenue-detail-group').value=detailGroup;
 $('revenue-details').innerHTML=data.groups.filter(g=>g.id===detailGroup).map(g=>{
  const details=g.details.filter(x=>!x.id.endsWith('_other')||['mom','yoy','qtd','ytd'].some(k=>p.scopes[scope][x.id][k].current||p.scopes[scope][x.id][k].previous));
  return '<section class="rv-detail" data-group="'+esc(g.id)+'"><div class="rv-detail-head"><h3>'+esc(g.name)+'</h3><span class="rv-detail-value">'+money(p.scopes[scope][g.id][detailMode].current)+' <small>tỷ</small></span></div>'+table(p,scope,detailMode,[...details,{id:g.id,name:'Tổng '+g.name,total:true}],g.name+' · '+headings[detailMode])+'</section>';
 }).join('');
 $('revenue-target-brief').hidden=mode!=='target'||p.id!=='2026-10';
 $('revenue-export').disabled=false;
}
function adopt(value,live=false){
 const next=validate(value);
 // Initial snapshot selection is automatic: advance it when the live API adds
 // a new month. An explicit user selection stays on that historical month.
 if(followLatest||!next.periods.some(p=>p.id===selected))selected=next.periods.at(-1).id;
 data=next;needsRender=true;render();if(live)loadState=data.source_kind==='database'?'live':'saved';renderStatus();
}
function renderStatus(){
 const through=data?' · đang hiển thị số chốt '+date(data.cutoff):'';
 $('revenue-refresh').textContent=busy?'Đang cập nhật…':'Làm mới';
 $('revenue-status').textContent=loadState==='loading'?'Đang đọc số liệu mới'+through+'.':loadState==='retry'?'Chưa đọc được số liệu mới'+through+'. App sẽ tự thử lại.':data?(loadState==='live'?'Đã đọc lịch sử mới nhất':'Bản số liệu đã tổng hợp')+' · hoàn tất đến '+date(data.cutoff)+' · nguồn cập nhật '+new Date(data.source_as_of).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'})+'.':'Chưa đọc được dữ liệu doanh thu.';
 $('revenue-status').setAttribute('role','status');
}
async function loadSnapshot(){
 if(data||snapshotLoad)return snapshotLoad;
 snapshotLoad=(async()=>{
  try{
   if(window.TAO_REVENUE_DATA){if(!data)adopt(window.TAO_REVENUE_DATA);return;}
   if(!window.TAO_REVENUE_GZIP||typeof DecompressionStream==='undefined')return;
   const bytes=Uint8Array.from(atob(window.TAO_REVENUE_GZIP),c=>c.charCodeAt(0));
   const saved=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
   // A delayed fallback must never overwrite a fresher API response.
   if(!data)adopt(saved);
   window.TAO_REVENUE_GZIP=null;
  }catch{/* Live API remains available if this browser cannot expand the fallback. */}
 })();
 return snapshotLoad;
}
async function refresh(){
 if(busy||window.TAO_REVENUE_PREVIEW)return;busy=true;$('revenue-refresh').disabled=true;
 clearTimeout(retryTimer);retryTimer=null;loadState='loading';renderStatus();
 const startedRevision=revision;
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{const response=await fetch('/tao/dashboard/api/revenue',{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('unavailable');const next=await response.json();if(data&&next.cutoff<data.cutoff)throw Error('Older data');adopt(next,true);lastRead=startedRevision===revision?Date.now():0;retryDelay=5000;}
 catch(error){lastRead=0;loadState='retry';if(visible()){retryTimer=setTimeout(()=>{retryTimer=null;if(visible())refresh();},retryDelay);retryDelay=Math.min(60000,retryDelay*2);}}
 finally{clearTimeout(timer);busy=false;$('revenue-refresh').disabled=false;renderStatus();if(startedRevision!==revision&&visible())refresh();}
}
window.TaoDataSync?.subscribe(()=>{revision++;lastRead=0;if(visible())refresh();});
$('revenue-month').addEventListener('change',e=>{selected=e.target.value;followLatest=false;pageIndex=0;render();});
$('revenue-group').addEventListener('change',e=>{group=e.target.value;model='all';pageIndex=0;if(group!=='all')detailGroup=group;render();});
$('revenue-model').addEventListener('change',e=>{model=e.target.value;pageIndex=0;const chosen=data?.models.find(m=>m.id===model);if(chosen)detailGroup=chosen.group;render();});
for(const key of ['revenue','quantity'])$('revenue-metric-'+key).addEventListener('click',()=>{metric=key;pageIndex=0;render();});
for(const key of ['revenue','quantity'])$('revenue-week-metric-'+key).addEventListener('click',()=>{metric=key;render();});
for(const layout of ['overview','detail','chart'])$('revenue-week-layout-'+layout).addEventListener('click',()=>{weeklyLayout=layout;render();});
for(const view of ['chart','table'])$('revenue-matrix-view-'+view).addEventListener('click',()=>{matrixView=view;render();});
$('revenue-chart-comparison').addEventListener('change',e=>{chartComparison=e.target.value;render();});
for(const id of ['revenue-line-chart','revenue-week-chart']){
 const host=$(id),point=e=>e.target.closest?.('[data-line-point]');
 host.addEventListener('pointermove',e=>{if(e.pointerType==='touch')return;const el=point(e);if(el)selectLinePoint(id,Number(el.getAttribute('data-line-point')));});
 host.addEventListener('click',e=>{const el=point(e);if(el)selectLinePoint(id,Number(el.getAttribute('data-line-point')),true);});
 host.addEventListener('focusin',e=>{const el=point(e);if(el)selectLinePoint(id,Number(el.getAttribute('data-line-point')));});
 host.addEventListener('keydown',e=>{
  if(!point(e))return;const state=chartState.get(id);if(!state)return;
  const index=e.key==='Home'?0:e.key==='End'?state.series.points.length-1:e.key==='ArrowLeft'?state.index-1:e.key==='ArrowRight'?state.index+1:['Enter',' '].includes(e.key)?state.index:null;
  if(index!==null){e.preventDefault();selectLinePoint(id,index,true);}
 });
}
for(const key of ['matrix','weekly'])$('revenue-mode-'+key).addEventListener('click',()=>{displayMode=key;if(focusMode)setFocus(key);else render();});
$('revenue-apple-year').addEventListener('change',e=>{fiscalYear=Number(e.target.value);appleQuarter='';render();});
$('revenue-apple-quarter').addEventListener('change',e=>{appleQuarter=e.target.value;render();});
$('revenue-detail-group').addEventListener('change',e=>{detailGroup=e.target.value;render();});
$('revenue-page-prev').addEventListener('click',()=>{pageIndex--;render();});
$('revenue-page-next').addEventListener('click',()=>{pageIndex++;render();});
$('revenue-focus').addEventListener('click',()=>setFocus(focusMode?'':displayMode));
$('revenue-summary-focus').addEventListener('click',()=>setFocus('summary'));
$('revenue-detail-focus').addEventListener('click',()=>setFocus('detail'));
$('revenue-focus-table').addEventListener('change',e=>setFocus(e.target.value));
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&focusMode){e.preventDefault();setFocus('');}});
window.addEventListener('resize',()=>{if(!data||!visible())return;clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(visible())render();},120);});
$('revenue-secondary').addEventListener('toggle',()=>{if($('revenue-secondary').open)render();});
$('revenue-view').addEventListener('change',e=>{mode=e.target.value;render();});
$('revenue-refresh').addEventListener('click',refresh);
$('revenue-export').addEventListener('click',()=>{if(!data)return;const p=data.periods.find(x=>x.id===selected),legacy=legacyFocus(),weekly=weeklyActive(),q=selectedAppleQuarter(),overview=weekly&&weeklyLayout==='overview',chart=!legacy&&(weekly?weeklyLayout==='chart':matrixView==='chart'),content=legacy?csv(data,p,scope):chart?lineCsv(weekly?weeklySeries(data,q,group,model,metric):comparisonSeries(data,p,group,model,metric,chartComparison)):overview?quarterOverviewCsv(data,q,group,model):weekly?weeklyCsv(q,weeklyKey(data,group,model),metric):matrixCsv(data,p,group,model,metric),url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=(chart?'Tao-bieu-do-duong-':legacy?'Tao-doanh-thu-chi-tiet-':overview?'Tao-tong-quan-quy-DT-SL-':(weekly?'Tao-tuan-Apple-':'Tao-model-')+(metric==='quantity'?'so-luong-':'doanh-thu-'))+(weekly?q.id:p.id)+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
function onRoute(){if(location.hash!=='#revenue'&&focusMode)setFocus('',false);const entering=!wasVisible;wasVisible=visible();if(!wasVisible){clearTimeout(retryTimer);retryTimer=null;return;}if(data&&(needsRender||entering))render();if(!data)loadSnapshot();if(Date.now()-lastRead>300000)refresh();}
window.addEventListener('hashchange',onRoute);
document.addEventListener('visibilitychange',onRoute);
if(!window.TAO_REVENUE_PREVIEW)setInterval(()=>{if(!document.hidden)onRoute();},300000);
try{if(window.TAO_REVENUE_DATA)adopt(window.TAO_REVENUE_DATA);else $('revenue-status').textContent='Đang chuẩn bị số liệu doanh thu…';}catch{$('revenue-status').textContent='Đang chuẩn bị số liệu doanh thu…';}
if(window.TAO_REVENUE_PREVIEW){$('revenue-refresh').hidden=true;$('revenue-status').textContent='BẢNG MẪU · Số thực tế từ lịch sử đã lưu · Không tự cập nhật trong file mẫu. Đơn vị: tỷ đồng, gồm VAT.';}else onRoute();
})();
