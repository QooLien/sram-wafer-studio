
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name=sram-token]').content;
const labels = {import:'匯入 ASC',maps:'Wafer Maps',data:'資料核對',batch:'批次匯出',settings:'TNO 設定'};
const layers = {fail:'Fail BLK Count',wr:'W&R 四宮格',loss:'Fail BLK / Loss',cat:'Cat Wafer Map',repair:'BL=0 Failure Analysis',vmin:'Chip Vmin Map'};
const tables = {audit:'Missing BLK Address',address:'Fail Address',fbc:'BLK_FBC_Comparison',vmin:'Chip Vmin'};
const s = {page:'import', files:[], batch:[], config:{}, mode:'FBC0', wt:1, pattern:'', layer:'fail', selected:null, block:null, viewPage:0, targetAddress:null, demo:null, report:null, busy:false, last:null, versions:0, gridVersion:0, detailVersion:0};
const nfmt = new Intl.NumberFormat('zh-TW');
const vfmt = v => v == null ? '—' : Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:3}) + ' V';
const chipKey = row => row.x + ',' + row.y;
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function put(id, ...nodes) { $(id).replaceChildren(...nodes); }
function options(select, values, selected) {
  select.replaceChildren(...Object.entries(values).map(([key, text]) => {
    const opt = el('option', text); opt.value = key; return opt;
  }));
  if (String(selected) in values) select.value = selected;
}
async function api(path, body) {
  const resp = await fetch('/api/' + path, {
    method:body === undefined ? 'GET' : 'POST',
    headers:{'X-SRAM-Token':token,'Content-Type':'application/json'},
    body:body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || resp.statusText);
  return data;
}
function notice(text, type='') {
  const node = $('notice'); node.hidden = !text; node.textContent = text;
  node.className = type;
}
function safe(fn) {
  return async event => {
    try { await fn(event); }
    catch (error) { notice(error.message, 'failure'); }
  };
}
function navigate(page) {
  s.page = page;
  for (const key of Object.keys(labels)) $('page-' + key).hidden = key !== page;
  document.querySelectorAll('.nav').forEach(button => {
    const selected = button.dataset.page === page;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-current', selected ? 'page' : 'false');
  });
  $('breadcrumb').textContent = '工作區 / ' + labels[page];
  if (page === 'maps' && s.report) return refreshMap();
  if (page === 'data' && s.report) return refreshTable();
  if (page === 'settings') renderSettings();
}
document.addEventListener('click', safe(event => {
  const btn = event.target.closest('button[data-page]');
  if (btn) return navigate(btn.dataset.page);
}));
function renderFiles(batch=false) {
  const list = batch ? s.batch : s.files;
  const id = batch ? 'batch-files' : 'full-files';
  const container = $(id);
  container.classList.toggle('empty', !list.length);
  $(batch ? 'batch-count' : 'file-count').textContent = list.length ? list.length + ' 份 ASC' : '尚未選取檔案';
  if (!list.length) return put(id, el('span', '選擇一份或多份 .asc 檔案'));
  put(id, ...list.map((path, i) => {
    const row = el('div', null, 'file-row');
    const name = path.split(/[\\/]/).pop();
    const description = el('div');
    description.append(el('span', name), el('br'), el('small', path));
    const remove = el('button','移除','quiet'); remove.disabled = s.busy;
    remove.onclick = () => { list.splice(i,1); renderFiles(batch); };
    row.append(el('b','ASC','file-icon'), description, remove); return row;
  }));
}
function modes() {
  const values = Object.fromEntries(Array.from({length:11}, (_,n)=>['FBC'+n,'FBC'+n]).concat([['FBC90%','FBC90%']]));
  options($('vmin-mode'), values, s.mode);
}
function setBusy(value) {
  s.busy = value;
  for(const id of ['pick-full','pick-batch','run-full','run-batch','open-export','open-xlsm','demo','save-config']) $(id).disabled = value;
  renderFiles(); renderFiles(true);
}
async function selectAsc(batch) {
  const data = await api('pick',{kind:'asc'});
  if (!data.paths.length) return;
  if (batch) s.batch = [...new Set([...s.batch,...data.paths])];
  else {
    if (data.paths.length > 3) throw new Error('完整版最多可選 3 份 ASC。');
    s.files = data.paths; s.demo = null; $('full-profile').textContent = '使用完整版 TNO 設定';
  }
  renderFiles(batch);
}
function setReport(report) {
  s.report = report; s.wt = 1; s.selected = null; s.block = null; s.viewPage = 0;
  s.pattern = report.patterns[0] || '';
  s.layer = report.source_mode === 'address' ? 'cat' : 'fail';
  const pats = Object.fromEntries(report.patterns.map(p=>[p,p]));
  options($('pattern'),pats,s.pattern);
  options($('data-pattern'),{'':'所有 Pattern',...pats},'');
  options($('data-wt'),Object.fromEntries(Array.from({length:report.phases},(_,i)=>[i+1,'WT'+(i+1)])),1);
  const mapLayers = {...layers}, available = {...tables};
  if(report.source_mode === 'address'){
    delete mapLayers.fail; delete mapLayers.wr; delete mapLayers.loss; delete mapLayers.vmin; delete mapLayers.repair;
    delete available.fbc; delete available.audit; delete available.vmin;
  }
  if(report.source_mode === 'fbc'){
    delete mapLayers.wr; delete mapLayers.loss; delete available.address; delete available.audit;
  }
  options($('layer'),mapLayers,s.layer);
  options($('data-view'),available);
  $('map-empty').hidden = $('data-empty').hidden = true;
  $('map-results').hidden = $('data-results').hidden = false;
  $('distribution').hidden = $('block-detail').hidden = true;
  $('map-caption').textContent = report.label+' · '+report.manifest[0].lot;
}
function showPaths(output, warnings) {
  const block = el('section',null,'card paths');
  if (output.length) {
    block.append(el('h2','已輸出 '+output.length+' 份檔案'));
    const list = el('ul');
    for(const path of output) list.append(el('li',path));
    block.append(list);
  }
  if(warnings.length) {
    const details = el('details'); details.open = true;
    details.append(el('summary',warnings.length+' 則匯入診斷'));
    for(const warning of warnings) details.append(el('p',warning));
    block.append(details);
  }
  return block;
}
async function waitJob(kind) {
  setBusy(true);
  for (;;) {
    const result = await api('status'); s.last = result;
    notice(result.error || result.message, result.error ? 'failure' : result.working ? 'busy' : '');
    if (result.working) { await new Promise(resolve=>setTimeout(resolve,350)); continue; }
    setBusy(false);
    if (kind === 'batch') put('batch-results',showPaths(result.output,result.warnings));
    if (kind === 'export' && result.output.length) notice('已匯出 '+result.output.join('\n'));
    if (['analyze','reopen'].includes(kind) && !result.error && result.data) {
      setReport(result.data);
      if (result.warnings.length) notice('分析完成。'+result.warnings.length+' 則診斷可在「匯入資訊」查看。');
      await navigate(kind === 'reopen' || result.data.source_mode === 'address' ? 'data' : 'maps');
    }
    break;
  }
}
async function run(kind, data) {
  await api(kind,data);
  try { await waitJob(kind); } finally { setBusy(false); }
}
$('pick-full').onclick = safe(()=>selectAsc(false));
$('pick-batch').onclick = safe(()=>selectAsc(true));
$('demo').onclick = safe(async ()=>{
  const demo = await api('demo',{mode:s.mode}); s.files = demo.paths; s.demo = demo.config;
  $('full-profile').textContent = '使用 128 芯片範例的 TNO 設定'; renderFiles();
});
$('vmin-mode').onchange = () => {s.mode = $('vmin-mode').value;};
$('run-full').onclick = safe(()=>{
  if(!s.files.length) throw new Error('請先選擇 ASC，或載入 128 芯片範例。');
  return run('analyze',{paths:s.files, rows:(s.demo || s.config.full).rows, mode:s.mode, source_mode:$('source-mode').value});
});
$('run-batch').onclick = safe(()=>{
  if(!s.batch.length) throw new Error('請先選擇 ASC。');
  return run('batch',{paths:s.batch, rows:s.config.batch.rows, mode:s.config.batch.mode});
});

$('open-xlsm').onclick = safe(async()=>{
  const data=await api('pick',{kind:'report'});
  if(data.paths.length) await run('reopen',{path:data.paths[0]});
});
function params(extra) {
  return 'view?'+new URLSearchParams({wt:s.wt,pattern:s.pattern,...extra}).toString();
}
function tint(row) {
  const val = row.value;
  if (s.layer === 'cat' || s.layer === 'repair') {
    const colors={1:'#c6efce',2:'#c6efce',3:'#bdd7ee',4:'#bdd7ee',9:'#ff9999',10:'#bfbfbf',11:'#bfbfbf',
      12:'#dbaddb',13:'#dbaddb',14:'#ffd966',15:'#d9d2e9',16:'#d9d2e9',17:'#d9d2e9',18:'#ffe699',19:'#9bc2e6',20:'#bfbfbf'};
    return [[val ?? '—',colors[val] || (val>=5&&val<=8?'#f8cbad':'#eef3f7')]];
  }
  if(s.layer === 'vmin') return [[val === null ? row.status : vfmt(val).split(' ')[0],val === null ? (row.status==='Pass'?'#dbeafe':'#e2e8f0') : '#f8cbad']];
  if(row.gray) return [['','#808080']];
  if(row.blue) return [['','#00b0f0']];
  if(s.layer === 'wr') return row.wr.map((v,i)=>[v||'',v?['#fff','#ffd966','#ff6600','#fff'][i]:'#fff',i === 3?'#8c8c8c':'']);
  if(s.layer === 'loss') return [[val||'','#fff'],[row.loss||'',row.loss?'#ff433c':'#fff',row.loss?'white':'']];
  return [[val||'',val>=50?'#bf8f00':val>=20?'#ffd966':val>=10?'#ffe699':val>0?'#fff2cc':'#fff']];
}
function renderLegend(id, pairs) {
  put(id,...pairs.map(([color, label])=>{
    const node=el('span');const colorBox=el('i');colorBox.style.backgroundColor=color;node.append(colorBox,label);return node;
  }));
}
function showKpis(rows) {
  const current = s.report.manifest[s.wt-1];
  const items = [[s.report.label,'Lot / Wafer'],[nfmt.format(rows.length),'Chip'],[nfmt.format(current.fbc),'FBC 紀錄'],
                 [nfmt.format(current.address),'WT'+s.wt+' Address']];
  put('kpis',...items.map(([value,key])=>{
    const box=el('div',null,'card kpi');box.append(el('span',key),el('b',value));return box;
  }));
}
function showChip(row) {
  if(!row) return put('chip-summary',el('h2','Chip 明細'),el('p','從 Wafer Map 點選一顆 Chip。'));
  const fields=[['WT','WT'+s.wt],['狀態',row.status]];
  if(s.layer === 'vmin'){
    fields.push(['Vmin',vfmt(row.value)],['觸發 BLK',row.blk ?? '—'],['TNO',row.tno ?? '—'],['Func.',row.func ?? '—'],
      ['Hard Fail',row.hard.length],['Tail BLK',row.tail.length],['Tail 門檻',row.cutoff==null?'—':Number(row.cutoff).toFixed(2)],
      ['剩餘／資料不足',row.remaining+'／'+row.incomplete]);
  } else if(row.wr){
    fields.push(['Fail BLK',row.value ?? '—'],['Loss BLK',row.loss],
                ['Read / Write',row.wr[0]+' / '+row.wr[1]],['RW / No Monitor',row.wr[2]+' / '+row.wr[3]]);
  }
  const details=el('dl');
  for(const [k,v] of fields){const line=el('div');line.append(el('dt',k),el('dd',v));details.append(line);}
  const link=el('button','查看 Chip 資料','secondary');
  link.onclick=safe(()=>{$('filter-chip').checked=true;s.viewPage=0;return navigate('data');});
  const title=el('h2','X'+row.x+' · Y'+row.y);
  put('chip-summary',title,details,link);
}
async function refreshMap() {
  if (!s.report) return;
  const id=++s.versions;
  const rows = await api(params({layer:s.layer}));
  if(id !== s.versions || s.page !== 'maps') return;
  showKpis(rows);
  put('wt-list',...Array.from({length:s.report.phases},(_,i)=>{
    const button=el('button','WT'+(i+1),s.wt===i+1?'active':'');
    button.setAttribute('aria-pressed',s.wt===i+1);
    button.onclick=safe(async()=>{s.wt=i+1;if(s.selected) $('data-wt').value=s.wt;await refreshMap();if(s.block!==null) await refreshDetail();});
    return button;
  }));
  $('pattern-label').hidden=!['fail','loss','wr'].includes(s.layer);
  const legend={fail:[['#fff2cc','1–9'],['#ffe699','10–19'],['#ffd966','20–49'],['#bf8f00','50+'],['#808080','依 Cat 灰底']],
    wr:[['#fff','左上 Read'],['#ffd966','右上 Write'],['#ff6600','左下 W&R'],['#fff','右下 No Monitor'],['#00b0f0','全 BLK 通過']],
    loss:[['#fff','左 Fail BLK'],['#ff433c','右 Loss BLK'],['#00b0f0','全 BLK 通過']],
    cat:[['#c6efce','C1–2'],['#bdd7ee','C3–4'],['#f8cbad','C5–8'],['#ff9999','C9'],['#bfbfbf','C10–11／C20']],
    repair:[['#c6efce','C1–2'],['#f8cbad','C5–8'],['#ff9999','C9']],
    vmin:[['#f8cbad','有效 Vmin (V)'],['#dbeafe','Pass'],['#e2e8f0','資料／門檻狀態']]};
  renderLegend('map-legend',legend[s.layer]);
  const x0=Math.min(...rows.map(r=>r.x)), x1=Math.max(...rows.map(r=>r.x));
  const y0=Math.min(...rows.map(r=>r.y)), y1=Math.max(...rows.map(r=>r.y));
  const nx=x1-x0+1,ny=y1-y0+1;
  if(Math.max(nx,ny)>100) throw new Error('Wafer Map 座標範圍超過 100。');
  const board=$('wafer-grid');board.replaceChildren();
  const size=Math.max(27,Math.min(44,Math.floor((board.parentElement.clientWidth-55)/nx),Math.floor(640/ny)));
  board.style.gridTemplateColumns='27px repeat('+nx+','+size+'px)';
  board.style.gridTemplateRows='21px repeat('+ny+','+size+'px)';
  const axis=(text,col,row)=>{const a=el('span',text,'axis');a.style.gridColumn=col;a.style.gridRow=row;board.append(a);};
  axis('Y/X',1,1);
  for(let x=x0;x<=x1;x++) axis(x,x-x0+2,1);
  for(let y=y0;y<=y1;y++) axis(y,1,y-y0+2);
  for(const row of rows){
    const values=tint(row);
    const chip=el('button',null,'chip'+(values.length===4?' quad':values.length===2?' half':''));
    chip.dataset.chip=chipKey(row);
    chip.style.gridColumn=row.x-x0+2;chip.style.gridRow=row.y-y0+2;
    chip.title='X'+row.x+' Y'+row.y+' · '+row.status+(row.value!=null?' · '+row.value:'');
    chip.setAttribute('aria-label',chip.title);
    chip.dataset.active=String(s.selected===chipKey(row));
    for(const [value,bg,fg] of values){ const span=el('span',value);span.style.backgroundColor=bg;if(fg)span.style.color=fg;chip.append(span); }
    chip.onclick=safe(async()=>{
      s.selected=chipKey(row);s.block=null;
      $('block-detail').hidden=true;
      board.querySelectorAll('.chip').forEach(btn=>{btn.dataset.active=String(btn.dataset.chip===s.selected);});
      showChip(row);
      if(s.report.source_mode!=='address') await refreshGrid();
    });
    board.append(chip);
  }
  showChip(rows.find(r=>chipKey(r)===s.selected));
}
$('layer').onchange=safe(()=>{s.layer=$('layer').value;return refreshMap();});
$('pattern').onchange=safe(()=>{s.pattern=$('pattern').value;return refreshMap();});
function selection() {
  if(!s.selected)return {};
  const [x,y]=s.selected.split(',');return {x,y};
}
const patternColor = name => {
  const patterns=s.report.patterns; const i=Math.max(0,patterns.indexOf(name));
  return ['#ffe0aa','#c8d9ef','#cde8ca','#f0ccee','#dddbf5'][i%5];
};
async function refreshGrid() {
  const id=++s.gridVersion;
  ++s.detailVersion;
  const entries=await api(params({view:'grid',...selection()}));
  if(id!==s.gridVersion || s.page!=='maps')return;
  $('distribution').hidden=false;
  const {x,y}=selection();$('dist-title').textContent='256 BLK Distribution · X'+x+' Y'+y;
  const board=$('blk-grid');board.replaceChildren();
  renderLegend('dist-legend',[['#00b0f0','Pass'],['#f35b53','Fail'],['#ffb9b4','Hard Fail'],['#d5dee7','No Data'],...s.report.patterns.map(p=>[patternColor(p),p])]);
  for(const entry of entries){
    const label=entry.trigger ? s.report.mode==='FBC90%' ? entry.trigger.func : vfmt(entry.trigger.voltage) : '';
    const btn=el('button',null,'block'+(entry.hard?' hard':entry.states.every(v=>v.status==='Pass')?' clean':''));
    btn.title='BLK '+entry.blk+(label?' · '+label:'');
    btn.setAttribute('aria-label',btn.title);
    btn.style.gridRow=entry.blk%16+1;btn.style.gridColumn=Math.floor(entry.blk/16)+1;
    if(entry.trigger&&!entry.hard)btn.style.background=patternColor(entry.trigger.pattern);
    btn.append(el('span','BLK '+entry.blk));
    if(label)btn.append(el('small',label));
    const bars=el('span',null,'bands');
    for(const i of entry.states){ const band=el('i',null,i.status.toLowerCase()); band.title=i.status;bars.append(band); }
    btn.append(bars);
    if(entry.states.some(i=>i.w||i.r)) btn.append(el('small',entry.states.map(i=>(i.w||'–')+'/'+(i.r||'–')).join(' ')));
    btn.onclick=safe(async()=>{s.block=entry.blk;board.querySelectorAll('.block.selected').forEach(b=>b.classList.remove('selected'));btn.classList.add('selected');await refreshDetail();$('block-detail').scrollIntoView({block:'nearest'});});
    board.append(btn);
  }
}
function table(headers, rows) {
  const table=el('table'), head=el('thead'), body=el('tbody'), bar=el('tr');
  for(const header of headers)bar.append(el('th',header));
  head.append(bar);table.append(head,body);
  if(!rows.length){const row=el('tr'),msg=el('td','沒有符合條件的資料','tab-note');msg.colSpan=headers.length;row.append(msg);body.append(row);}
  for(const values of rows){
    const row=el('tr');for(const value of values)row.append(value instanceof Node ? value : el('td',Array.isArray(value)?value.join(', '):value??'—'));body.append(row);
  }
  return table;
}
function section(title, node) {
  const block=el('section',null,'detail-section');
  const sc=el('div',null,'table-scroll');sc.append(node);
  block.append(el('h3',title),sc);return block;
}
function plot(sweep) {
  const wrap=el('div',null,'plot');
  const data=sweep.filter(r=>r.v!==null&&r.fbc!==null&&!['Hard Fail','Prior WT','Prior Pattern','No Data'].includes(r.state));
  if(!data.length)return el('p','沒有可繪製的 FBC 記錄。','tab-note');
  const low=Math.min(...data.map(r=>r.v)),high=Math.max(...data.map(r=>r.v));
  const max=Math.max(1,...data.map(r=>r.fbc));
  const xd=v=>58+(high-v)/(high-low||1)*575, yd=v=>173-v/max*142;
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 660 215');svg.setAttribute('role','img');svg.setAttribute('aria-label','測試電壓與 FBC 散點圖');
  const add=(tag,attrs,text)=>{
    const node=document.createElementNS(ns,tag);for(const [key,val] of Object.entries(attrs))node.setAttribute(key,val);
    if(text!==undefined)node.textContent=text;svg.append(node);return node;
  };
  for(let i=0;i<=4;i++){ const y=yd(max*i/4);add('line',{x1:58,x2:633,y1:y,y2:y,stroke:'#e1e9f0'});add('text',{x:51,y:y+4,'text-anchor':'end','font-size':11,fill:'#516679'},Number((max*i/4).toFixed(2))); }
  for(let i=0;i<=(high===low?0:4);i++){ const v=high-(high-low)*i/4;add('text',{x:xd(v),y:191,'text-anchor':'middle','font-size':11,fill:'#516679'},v.toFixed(3));}
  add('text',{x:9,y:14,'font-size':12,fill:'#516679'},'FBC');add('text',{x:346,y:209,'font-size':12,'text-anchor':'middle',fill:'#516679'},'Test Voltage (V)');
  for(const row of data){
    const dot=add('circle',{cx:xd(row.v),cy:yd(row.fbc),r:4,fill:patternColor(row.pattern),stroke:'#41566a'});
    const title=document.createElementNS(ns,'title');title.textContent=row.pattern+' · TNO '+row.tno+' · FBC '+row.fbc;dot.append(title);
  }
  wrap.append(svg);return wrap;
}
async function refreshDetail() {
  if(s.block===null)return;
  const id=++s.detailVersion;
  const details=await api(params({view:'detail',...selection(),blk:s.block}));
  if(id!==s.detailVersion||s.page!=='maps')return;
  const title=el('div',null,'section-title');
  title.append(el('h2','WT'+s.wt+' · BLK '+s.block),el('span',s.report.mode));
  const body=el('div',null,'details-body');
  body.append(section('Vmin 判定',table(['Pattern','狀態','TNO','Func.','Vmin','峰值 FBC'],
    details.crossings.map(c=>[c.pattern,c.status,c.tno,c.func,vfmt(c.voltage),c.peak]))));
  body.append(section('Voltage / FBC',plot(details.sweep)));
  body.append(section('Function sweep（Config 順序）',table(['Pattern','TNO','Func.','Test Voltage','FBC','狀態'],
    details.sweep.map(r=>[r.pattern,r.tno,r.func,vfmt(r.v),r.fbc,r.state]))));
  const addresses=details.addresses.map(r=>{
    const cell=el('td'), btn=el('button','查看地址','quiet');
    btn.onclick=safe(()=>{
      $('data-view').value='address';$('filter-chip').checked=true;
      s.targetAddress=r.address.join(',');s.viewPage=0;return navigate('data');
    });
    cell.append(btn);
    return [r.pattern,...r.address,r.function,r.write,r.read,r.category,cell];
  });
  body.append(section('Fail Address / Monitor 匹配',table(['Pattern','BLK','WL','BL','IO','Function TNO','Write TNO','Read TNO','分類','來源'],addresses)));
  $('block-detail').hidden=false;put('block-detail',title,body);
}
async function refreshTable() {
  const mode=$('data-view').value,id=++s.versions;
  $('data-scope').hidden=mode!=='audit';
  $('data-wt').parentElement.hidden=!['audit','vmin'].includes(mode);
  $('filter-chip').disabled=!s.selected;
  const result=await api(params({view:mode,wt:$('data-wt').value,pattern:$('data-pattern').value,
    page:s.viewPage,...(s.targetAddress?{target:s.targetAddress}:{}),...($('filter-chip').checked?selection():{})}));
  if(id!==s.versions||s.page!=='data')return;
  s.viewPage=result.page;s.targetAddress=null;
  const rendered=table(result.headers,result.rows);
  put('data-table',rendered);
  if(result.highlighted!==null){
    const row=rendered.tBodies[0].rows[result.highlighted];
    row.classList.add('address-match');row.scrollIntoView({block:'nearest'});
  }
  $('prev').disabled=s.viewPage===0;$('next').disabled=!result.more;
  $('page-no').textContent='第 '+(s.viewPage+1)+' 頁';
}
for(const id of ['data-view','data-wt','data-pattern','filter-chip']) $(id).onchange=safe(()=>{s.viewPage=0;return refreshTable();});
$('prev').onclick=safe(()=>{if(s.viewPage>0)s.viewPage--;return refreshTable();});
$('next').onclick=safe(()=>{s.viewPage++;return refreshTable();});
function modal(title, node) {
  $('modal-title').textContent=title;put('modal-content',node);$('modal').showModal();
}
$('close-modal').onclick=()=>$('modal').close();
$('open-import').onclick=safe(async()=>{
  const data=await api('status'), block=el('div');
  if(!data.data&&!data.output.length&&!data.warnings.length)block.append(el('p','目前沒有匯入記錄。'));
  if(data.data)block.append(section(data.data.label,table(['WT','STEP','版本','Chip','FBC','Address','忽略的 Address','重複 FBC','來源'],
    data.data.manifest.map(r=>['WT'+r.wt,r.step,r.version,r.chips,r.fbc,r.address,r.invalid,r.duplicates,r.path]))));
  if(data.output.length||data.warnings.length)block.append(showPaths(data.output,data.warnings));
  modal('匯入資訊',block);
});
$('open-export').onclick=safe(()=>{
  if(!s.report)throw new Error('請先匯入 ASC。');
  const block=el('div',null,'modal-files');
  block.append(el('p','預設存回第一份 ASC 的資料夾。'));
  if (s.selected) block.append(el('p','完整 Excel 的 BLK 矩陣使用 X'+selection().x+' Y'+selection().y+'。'));
  let folder='';
  const path=el('p','使用 ASC 來源資料夾','modal-path');
  const picker=el('button','選擇匯出資料夾','secondary');
  picker.onclick=safe(async()=>{const data=await api('pick',{kind:'folder'});if(data.paths.length){folder=data.paths[0];path.textContent=folder;}});
  block.append(picker,path);
  const modes={full:'完整 Excel 報表（原版版面）',address:'Fail Address Excel',fbc:'FBC Excel',cat:'Cat Map Excel',ppt:'Wafer Maps PowerPoint · 37 cm'};
  for(const [kind,label] of Object.entries(modes)){
    if(s.report.source_mode!=='full' && ![s.report.source_mode,'cat'].includes(kind))continue;
    const button=el('button',label,'secondary');
    button.onclick=safe(()=>{$('modal').close();return run('export',{kind,folder,chip:s.selected?.split(',')});});
    block.append(button);
  }
  modal('匯出報表',block);
});
function profile() {return $('profile').value;}
function renderSettings() {
  const current=s.config[profile()];if(!current)return;
  const full=profile()==='full', header=el('tr');
  const fields=[['tno','TNO'],['name','Func.'],['voltage','Voltage (V)'],['cat','Fail Cat.']];
  if(full)fields.push(['stop','Stop Sign']);
  for(const title of ['Group',...fields.map(f=>f[1]),'列操作'])header.append(el('th',title));
  put('config-head',header);
  put('config-rows',...current.rows.map((obj,i)=>{
    const row=el('tr'), group=el('td'), select=el('select');
    options(select,{Monitor:'Monitor',Function:'Function'},obj.group);
    select.setAttribute('aria-label','Group '+(i+1));select.onchange=()=>{obj.group=select.value;};group.append(select);row.append(group);
    for(const [key,title] of fields){
      const cell=el('td'), input=el('input');
      input.value=obj[key]??'';input.setAttribute('aria-label',title+' '+(i+1));
      if(key==='tno'||key==='cat')input.inputMode='numeric';if(key==='voltage')input.inputMode='decimal';
      input.oninput=()=>{obj[key]=input.value;};cell.append(input);row.append(cell);
    }
    const actions=el('td'), moves=el('div',null,'moves');
    for(const [icon,offset,name] of [['↑',-1,'上移'],['↓',1,'下移'],['✕',0,'移除']]){
      const button=el('button',icon,offset?'quiet':'quiet remove');button.setAttribute('aria-label',name+' '+(i+1));
      button.disabled=offset!==0&&(i+offset<0||i+offset>=current.rows.length);
      button.onclick=()=>{
        if(!offset)current.rows.splice(i,1);
        else [current.rows[i],current.rows[i+offset]]=[current.rows[i+offset],current.rows[i]];
        renderSettings();
      };moves.append(button);
    }
    actions.append(moves);row.append(actions);return row;
  }));
}
$('profile').onchange=renderSettings;
$('add-row').onclick=()=>{s.config[profile()].rows.push({group:'Function',tno:'',name:'',voltage:'',cat:'',stop:''});renderSettings();$('config-rows').lastChild?.scrollIntoView({block:'nearest'});};
$('pick-config').onclick=safe(async()=>{
  const result=await api('pick',{kind:'settings'});
  if(result.config){s.config[profile()]=result.config;renderSettings();notice('已載入 '+result.paths[0].split(/[\\/]/).pop()+'，可編輯後儲存。');}
});
$('save-config').onclick=safe(async()=>{
  const key=profile(), data=s.config[key];
  s.config[key]=await api('save-settings',{profile:key,rows:data.rows,mode:key==='full'?s.mode:data.mode});
  renderSettings();notice('已儲存 '+(key==='full'?'完整版':'批次匯出')+'設定。');
});
safe(async()=>{
  const settings=await api('settings');s.config=settings.settings;s.mode=s.config.full.mode;modes();
  renderFiles();renderFiles(true);
  const result=await api('status');s.last=result;
  if(result.data)setReport(result.data);
  if(result.working)await waitJob('analyze');
})();
