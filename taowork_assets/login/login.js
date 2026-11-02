'use strict';
(() => {
  const $=id=>document.getElementById(id),form=$('login-form'),button=$('login-submit'),message=$('login-message');
  let busy=false,checking=false,retryTimer=null,retryDelay=2000,leaving=false;
  const retry=$('retry-connection');
  function show(text,error=false){message.textContent=text;message.dataset.error=String(error);}
  function stopRetry(){clearTimeout(retryTimer);retryTimer=null;}
  function enter(){leaving=true;stopRetry();location.replace('/tao/dashboard/'+(/^#[a-z0-9-]+$/.test(location.hash)?location.hash:''));}
  async function request(url,options={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try{
      const res=await fetch(url,{cache:'no-store',credentials:'same-origin',...options,signal:controller.signal});
      const data=await res.json();if(!res.ok)throw Error(data.error||'Chưa đăng nhập được. Vui lòng thử lại.');return data;
    }finally{clearTimeout(timer);}
  }
  $('show-password').addEventListener('click',()=>{
    const visible=$('password').type==='password';$('password').type=visible?'text':'password';
    $('show-password').textContent=visible?'Ẩn':'Hiện';$('show-password').setAttribute('aria-pressed',String(visible));
    $('show-password').setAttribute('aria-label',visible?'Ẩn mật khẩu':'Hiện mật khẩu');
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||button.disabled||!form.reportValidity())return;
    busy=true;stopRetry();retry.hidden=true;button.disabled=true;button.firstElementChild.textContent='Đang đăng nhập…';show('');
    try{
      await request('/tao/dashboard/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:$('username').value.trim(),password:$('password').value,remember:$('remember').checked})});
      $('password').value='';enter();
    }catch(error){show(error.name==='AbortError'?'Kết nối đang chậm. Em thử đăng nhập lại nhé.':error.message,true);$('password').value='';$('password').focus();}
    finally{busy=false;button.disabled=false;button.firstElementChild.textContent='Đăng nhập';}
  });
  async function checkSession(){
    stopRetry();if(checking||busy||document.hidden||leaving)return;
    checking=true;retry.disabled=true;
    try{
      const state=await request('/tao/dashboard/auth/session');
      if(state.authenticated){enter();return;}
      retryDelay=2000;retry.hidden=true;button.disabled=!state.configured;
      show(state.configured?(location.search==='?created=1'?'Đã tạo tài khoản. Em đăng nhập để tiếp tục.':''):'Tài khoản cloud chưa được kích hoạt.');
    }catch{
      retry.hidden=false;show('Kết nối đang gián đoạn. TáoWork sẽ tự thử lại khi có mạng.',true);
      if(!document.hidden&&!leaving){retryTimer=setTimeout(checkSession,retryDelay);retryDelay=Math.min(retryDelay*2,30000);}
    }finally{checking=false;retry.disabled=false;}
  }
  retry.addEventListener('click',checkSession);
  window.addEventListener('online',()=>{retryDelay=2000;checkSession();});
  window.addEventListener('pagehide',()=>{leaving=true;stopRetry();});
  window.addEventListener('pageshow',()=>{leaving=false;checkSession();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopRetry();else checkSession();});
  checkSession();
})();
