'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
(async()=>{
 const root=path.resolve(__dirname,'../../taowork_assets/login'),html=fs.readFileSync(path.join(root,'index.html'),'utf8'),code=fs.readFileSync(path.join(root,'login.js'),'utf8');
 const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],{id:m[1],dataset:{},disabled:m[1]==='login-submit',hidden:false,value:'',checked:false,type:'password',textContent:'',firstElementChild:{textContent:''},events:{},addEventListener(n,f){this.events[n]=f;},setAttribute(){},focus(){},reportValidity(){return true;}}]));
 const calls=[],location={hash:'',search:'',replace(value){this.next=value;}};
 const context={document:{hidden:false,getElementById:id=>nodes.get(id)||null,addEventListener(){}},window:{addEventListener(){}},location,AbortController,setTimeout:()=>1,clearTimeout(){},fetch:async(url,options={})=>{calls.push({url,options});return {ok:true,json:async()=>url.endsWith('/session')?{configured:true,authenticated:false}:{ok:true}};}};
 vm.runInNewContext(code,context);await new Promise(setImmediate);
 assert.equal(nodes.get('login-submit').disabled,false,'Configured cloud account must enable login');
 nodes.get('username').value='cloud-test';nodes.get('password').value='test-only-password';nodes.get('remember').checked=true;
 await nodes.get('login-form').events.submit({preventDefault(){}});
 const call=calls.find(x=>x.url.endsWith('/login'));assert(call);assert.equal(call.url,'/tao/dashboard/auth/login');
 assert.deepEqual(JSON.parse(call.options.body),{username:'cloud-test',password:'test-only-password',remember:true});
 assert.equal(location.next,'/tao/dashboard/');assert.equal(nodes.get('password').value,'');
 assert(!html.includes('line-scdn'));assert(!html.includes('Tồn kho'));console.log('Cloud login DOM, account check, password submit and redirect passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
