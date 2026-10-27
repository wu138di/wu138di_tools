'use strict';
const $ = id => document.getElementById(id);
let ready=false, allMedia=false, busy=false, initialized=false, lastRows='', lastPhase='', pollTimer=null;
const activePhases=new Set(['resolving','downloading','converting']);
const phaseTitles={idle:'',resolving:'解析中',downloading:'下载中',converting:'转换 GIF',done:'下载完成',partial:'部分完成',error:'下载失败',cancelled:'已取消'};
let springX=0,springVelocity=0,springTarget=0,springRAF=0,springTime=0;
let previewItems=[], previewIndex=0, previewKey='', previewPhase='idle', previewTimer=null;
function schedulePreview(){clearTimeout(previewTimer);if(ready)previewTimer=setTimeout(async()=>{try{await api('preview_post',$('postUrl').value,allMedia);render(await api('get_state'));}catch{}},500);}
function showPreview(){
 const stage=$('previewStage');const old=stage.querySelector('video');if(old){old.pause();old.removeAttribute('src');old.load();}stage.replaceChildren();
 const item=previewItems[previewIndex];$('previewPrev').disabled=!item||previewIndex===0;$('previewNext').disabled=!item||previewIndex>=previewItems.length-1;
 $('previewCounter').textContent=item?`${previewIndex+1} / ${previewItems.length}`:'—';$('previewMeta').textContent=item?[item.name,item.width&&item.height?`${item.width} × ${item.height}`:''].filter(Boolean).join(' · '):'';
 if(!item){const placeholder=document.createElement('span');placeholder.className='preview-empty';placeholder.innerHTML=previewPhase==='loading'?'<span class="preview-spinner"></span>':previewPhase==='error'?'<span>预览暂未加载</span>':'<svg><use href="#i-photo"/></svg>';stage.append(placeholder);return;}
 const media=document.createElement(item.kind==='photo'?'img':'video');media.setAttribute('aria-label',item.name);
 if(item.kind==='photo'){media.alt=item.name;}else{media.playsInline=true;media.preload='auto';media.controls=item.kind!=='gif';media.muted=item.kind==='gif';media.loop=item.kind==='gif';media.autoplay=item.kind==='gif';}
 media.addEventListener('error',()=>{const note=document.createElement('span');note.className='preview-load-error';note.textContent='预览暂未加载';stage.append(note);});media.src=item.src;stage.append(media);if(item.kind==='gif')media.play().catch(()=>{media.controls=true;});
}
function renderPreview(value){value=value||{phase:'idle',items:[]};const key=JSON.stringify(value);if(key===previewKey)return;previewKey=key;previewPhase=value.phase;previewItems=value.items;previewIndex=0;showPreview();}
function syncSelectedRows(){const selected=previewItems[previewIndex]?.index;document.querySelectorAll('.media-row').forEach(row=>{const active=Number(row.dataset.index)===selected;row.classList.toggle('is-selected',active);row.setAttribute('aria-pressed',String(active));});}
function selectPreview(index){const target=previewItems.findIndex(item=>item.index===index);if(target<0)return;previewIndex=target;showPreview();syncSelectedRows();}
function animateSegment(target){
 springTarget=target;
 if(matchMedia('(prefers-reduced-motion: reduce)').matches){springX=target;springVelocity=0;$('segmentHighlight').style.transform=`translateX(${target}px)`;return;}
 if(springRAF)return;
 springTime=performance.now();
 function frame(now){const dt=Math.min((now-springTime)/1000,.024);springTime=now;const stiffness=420,damping=41;
  springVelocity+=(-stiffness*(springX-springTarget)-damping*springVelocity)*dt;springX+=springVelocity*dt;
  $('segmentHighlight').style.transform=`translateX(${springX}px)`;
  if(Math.abs(springVelocity)<.1&&Math.abs(springX-springTarget)<.1){springX=springTarget;springVelocity=0;springRAF=0;$('segmentHighlight').style.transform=`translateX(${springX}px)`;}else springRAF=requestAnimationFrame(frame);}
 springRAF=requestAnimationFrame(frame);
}
function setScope(all){const changed=allMedia!==all;allMedia=all;$('scopeLink').classList.toggle('selected',!all);$('scopeAll').classList.toggle('selected',all);$('scopeLink').setAttribute('aria-pressed',String(!all));$('scopeAll').setAttribute('aria-pressed',String(all));animateSegment(all?$('scopeAll').offsetLeft-3:0);if(changed)schedulePreview();}
function toast(text){$('toast').textContent=text;$('toast').classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').classList.remove('visible'),2600);}
async function api(method,...args){if(!ready)throw new Error('程序仍在准备，请稍等片刻。');return window.pywebview.api[method](...args);}
function validateUrl(){const value=$('postUrl').value.trim();const valid=!value||/https:\/\/(?:www\.|mobile\.|m\.)?(?:x|twitter)\.com\/(?:[^\s/]+|i\/web)\/status\/\d+/i.test(value);$('urlHint').classList.toggle('hidden',valid);$('urlHint').textContent=valid?'':'请检查帖子链接';return valid;}
function formatBytes(value){if(!value)return '准备中';if(value<1024)return value+' B';if(value<1048576)return(value/1024).toFixed(1)+' KB';return(value/1048576).toFixed(1)+' MB';}
function renderRows(items){const key=JSON.stringify(items);if(key===lastRows)return;lastRows=key;const container=$('mediaList');container.replaceChildren();items.forEach(item=>{
 const row=document.createElement('div');row.className='media-row';row.dataset.index=String(item.index);row.tabIndex=0;row.setAttribute('role','button');row.setAttribute('aria-label','预览'+item.name);row.addEventListener('click',()=>selectPreview(item.index));row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectPreview(item.index);}});
 const icon=document.createElement('span');icon.className='media-icon';const kinds={photo:'photo',video:'play',gif:'gif'};icon.innerHTML=`<svg><use href="#i-${kinds[item.kind]||'photo'}"/></svg>`;
 if(item.thumbnail_src){const thumb=document.createElement('img');thumb.className='media-thumbnail';thumb.src=item.thumbnail_src;thumb.alt=item.name;thumb.width=40;thumb.height=40;thumb.addEventListener('error',()=>thumb.remove());icon.append(thumb);}
 const details=document.createElement('div');details.className='media-details';const name=document.createElement('strong');name.textContent=item.name;const description=document.createElement('small');description.textContent=item.error||[item.width&&item.height?`${item.width} × ${item.height}`:'原始媒体',formatBytes(item.bytes),item.files.length>1?'MP4 + GIF':''].filter(Boolean).join(' · ');details.append(name,description);
 const status=document.createElement('span');status.className='media-status'+(item.status==='已保存'?' ok':item.status==='未完成'?' fail':'');status.textContent=item.status;row.append(icon,details,status);container.append(row);
 });container.classList.toggle('hidden',items.length===0);syncSelectedRows();}
function render(state){
 busy=activePhases.has(state.phase);$('statusTitle').textContent=phaseTitles[state.phase]||'下载状态';$('statusMessage').textContent=state.message;
 $('statusCard').classList.toggle('hidden',state.phase==='idle');$('statusCard').classList.toggle('active',busy);$('statusCard').classList.toggle('done',state.phase==='done');$('statusCard').classList.toggle('error',['error','partial'].includes(state.phase));
 $('statusOrb').innerHTML=`<svg><use href="#i-${state.phase==='done'?'check':'down'}"/></svg>`;
 $('download').disabled=busy||!ready;$('download').classList.toggle('busy',busy);$('downloadLabel').textContent=busy?'下载中…':state.phase==='error'||state.phase==='partial'?'重试':'下载';
 $('cancel').classList.toggle('hidden',!busy);$('percent').classList.toggle('hidden',!busy||state.phase==='resolving');$('percent').textContent=Math.round(state.progress)+'%';
 $('progressTrack').classList.toggle('hidden',!busy&&state.phase!=='done'&&state.phase!=='partial');$('progressTrack').classList.toggle('indeterminate',state.phase==='resolving'||state.phase==='converting');$('progressFill').style.width=state.progress+'%';
 $('chooseDirectory').textContent=state.directory;$('chooseDirectory').title=state.directory;$('chooseDirectory').disabled=busy;$('changeDirectory').disabled=busy;$('scopeLink').disabled=busy;$('scopeAll').disabled=busy;$('gifToggle').disabled=busy;
 const hasFiles=state.file_count>0||state.items.some(x=>x.files.length);$('openFolder').classList.toggle('hidden',!hasFiles);
 renderRows(state.items);
 renderPreview(state.preview);
 if(!initialized){$('gifToggle').checked=state.preferences.gif;setScope(state.preferences.all_media);initialized=true;}
 if(state.phase==='done'&&lastPhase!=='done'){document.title='wu138di X GIF下载器 v1.0';}else if(busy){document.title='wu138di X GIF下载器 v1.0';}else{document.title='wu138di X GIF下载器 v1.0';}
 lastPhase=state.phase;
}
async function poll(){try{render(await api('get_state'));}catch(error){if(ready)console.warn(error);}pollTimer=setTimeout(poll,busy||previewPhase==='loading'?350:1000);}
$('downloadForm').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;if(!$('postUrl').value.trim()){$('postUrl').focus();toast('先粘贴一个帖子链接吧');return;}if(!validateUrl()){$('postUrl').focus();return;}try{$('download').disabled=true;const result=await api('start_download',$('postUrl').value,$('gifToggle').checked,allMedia);if(!result.ok)toast(result.message);render(await api('get_state'));}catch(error){toast(error.message);$('download').disabled=false;}});
$('postUrl').addEventListener('input',()=>{validateUrl();schedulePreview();});
$('paste').addEventListener('click',async()=>{try{const value=await navigator.clipboard.readText();if(value){$('postUrl').value=value.trim();validateUrl();schedulePreview();$('postUrl').focus();}else toast('剪贴板里还没有链接');}catch{toast('点击输入框，按 Ctrl+V 粘贴链接');$('postUrl').focus();}});
$('scopeLink').addEventListener('click',()=>setScope(false));$('scopeAll').addEventListener('click',()=>setScope(true));
$('cancel').addEventListener('click',async()=>{await api('cancel_download');render(await api('get_state'));});
async function chooseDirectory(){try{const result=await api('choose_directory');if(!result.ok)toast(result.message);render(await api('get_state'));}catch(error){toast('暂未更换保存位置：'+error.message);}}
$('chooseDirectory').addEventListener('click',chooseDirectory);$('changeDirectory').addEventListener('click',chooseDirectory);
$('openFolder').addEventListener('click',async()=>{try{await api('open_directory');}catch(error){toast('打开文件夹失败：'+error.message);}});
['minimize','maximize','close'].forEach(id=>$(id).addEventListener('click',()=>api({minimize:'minimize',maximize:'toggle_maximize',close:'close_window'}[id])));
$('optionsToggle').addEventListener('click',()=>{const open=$('downloadOptions').classList.toggle('hidden')===false;$('optionsToggle').setAttribute('aria-expanded',String(open));if(open)setScope(allMedia);});
$('support').addEventListener('click',()=>$('supportDialog').showModal());$('closeSupport').addEventListener('click',()=>$('supportDialog').close());$('rewardImage').addEventListener('click',()=>$('supportDialog').classList.toggle('expanded'));$('supportDialog').addEventListener('click',e=>{if(e.target===$('supportDialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('previewPrev').addEventListener('click',()=>{if(previewIndex>0){previewIndex--;showPreview();syncSelectedRows();}});$('previewNext').addEventListener('click',()=>{if(previewIndex<previewItems.length-1){previewIndex++;showPreview();syncSelectedRows();}});
window.addEventListener('resize',()=>{if(!springRAF)setScope(allMedia);});
window.addEventListener('pywebviewready',()=>{ready=true;poll();$('postUrl').focus();});
$('download').disabled=true;
