(() => {
  'use strict';
  const cfg = window.STUDIO360_CONFIG;
  const el = id => document.getElementById(id);
  const format = (n, places = 0) => n == null ? 'Not modeled' : Number(n).toLocaleString(undefined, {maximumFractionDigits: places});
  const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let mode = 'nonsurgical', baseline = null, model = null, results = {}, revision = 0;
  let busy = false, modelRequest = 0, calcTimer;
  let zones = [{area:'area3', density:'moderate', area_cm2:50, baseline_density:100,
                baseline_diameter_um:40, responsive_percent:100, grafts:1250}];
  const inputs = ['protocol','density-change','diameter-mode','diameter-change','horizon','hairs-per-graft','survival','visibility'];
  function status(message, error = false) { el('status').textContent = message; el('status').classList.toggle('error', error); }
  function number(id) { return el(id).value === '' ? null : Number(el(id).value); }
  function scenario() {
    return {protocol:el('protocol').value, density_change:number('density-change'),
      diameter_mode:el('diameter-mode').value, diameter_change:number('diameter-change'),
      horizon:el('horizon').value, hairs_per_graft:number('hairs-per-graft'),
      graft_survival_percent:number('survival'), visible_growth_percent:number('visibility'), zones:structuredClone(zones)};
  }
  async function post(url, data, form = false) {
    const response = await fetch(url, {method:'POST', credentials:'same-origin',
      headers:form ? {} : {'Content-Type':'application/json'}, body:form ? data : JSON.stringify(data)});
    if (response.redirected || !(response.headers.get('content-type') || '').includes('application/json'))
      throw Error('Your session is unavailable. Sign in through the Suite and try again.');
    const result = await response.json();
    if (!response.ok || result.error) throw Error(result.error || 'The request could not be completed.');
    return result;
  }
  function invalidate() {
    revision++; results = {}; model = null; el('reviewed').checked = false;
    clearTimeout(calcTimer); calcTimer = setTimeout(calculateModel, 180); drawPreviews();
  }
  function setPreset(resetThickness = true) {
    const protocol = cfg.protocols[el('protocol').value];
    el('growth-label').textContent = protocol.density_mode === 'absolute' ? 'Density increase (hairs/cm²)' : 'Density increase (%)';
    el('density-change').value = protocol.density_default;
    el('preset-density').textContent = `Supplied range: +${protocol.density_range.join('–')} ${protocol.density_mode === 'absolute' ? 'hairs/cm²' : '%'}`;
    if (resetThickness) setThicknessPreset();
  }
  function setThicknessPreset() {
    const protocol = cfg.protocols[el('protocol').value], absolute = el('diameter-mode').value === 'absolute';
    el('diameter-label').textContent = `Shaft diameter increase (${absolute ? 'μm' : '%'})`;
    el('diameter-change').value = absolute ? protocol.diameter_default_um : protocol.diameter_default_percent;
    const range = absolute ? protocol.diameter_range_um : protocol.diameter_range_percent;
    el('preset-thickness').textContent = `Supplied scenario range: +${range.join('–')} ${absolute ? 'μm' : '%'}`;
    el('study-preset').hidden = el('protocol').value !== 'laser';
  }
  function renderZones() {
    const fields = [['area_cm2','Area in cm²',.1,200,.1],['baseline_density','Baseline terminal density',0,400,1],
      ['baseline_diameter_um','Baseline diameter in μm',10,200,.1],['responsive_percent','Responsive portion percent',0,100,1],['grafts','Transplant grafts',0,10000,1]];
    el('zone-rows').innerHTML = zones.map((z,i) => {
      const label = cfg.areas[z.area].name;
      return `<tr><td><strong>${escape(label)}</strong><small>${escape(z.density)} plan</small></td>` + fields.map(([key,name,min,max,step]) =>
        `<td><input type="number" data-row="${i}" data-field="${key}" aria-label="${escape(label+' '+name)}" min="${min}" max="${max}" step="${step}" value="${z[key] == null ? '' : z[key]}"></td>`).join('') +
        `<td><button class="remove-zone" data-remove="${i}" aria-label="Remove ${escape(label)}">×</button></td></tr>`;
    }).join('');
    for (const option of el('add-zone-select').options) option.disabled = zones.some(z => z.area === option.value);
    const available = [...el('add-zone-select').options].find(o => !o.disabled);
    el('add-zone').disabled = !available;
    if (available) el('add-zone-select').value = available.value;
  }
  async function calculateModel() {
    const requestId = ++modelRequest, version = revision;
    try {
      const result = await post('/api/360/model', scenario());
      if (requestId !== modelRequest || version !== revision) return;
      model = result.model; status(''); renderModel(); drawPreviews();
    } catch (error) {
      if (requestId !== modelRequest || version !== revision) return;
      model = null; el('metrics').innerHTML = ''; el('comparison-body').innerHTML = ''; el('savings').hidden = true;
      status(error.message, true); drawPreviews();
    }
  }
  function metric(label,value,delta,unit) {
    return `<article class="metric"><span class="label">${escape(label)}</span><strong class="value">${escape(value)}</strong><span class="delta">${escape(delta)}</span><span class="unit">${escape(unit)}</span></article>`;
  }
  function renderModel() {
    if (!model) return;
    const t = model.totals, gain = t.nonsurgical_diameter_um == null ? null : t.nonsurgical_diameter_um-t.baseline_diameter_um;
    el('metrics').innerHTML = metric('NON-SURGICAL HAIR COUNT',format(t.nonsurgical_hairs),`+${format(t.added_hairs)} additional hairs`,'Terminal hairs in selected zones') +
      metric('NON-SURGICAL DENSITY',format(t.nonsurgical_density,1),`From ${format(t.baseline_density,1)} hairs/cm²`,'Terminal hairs per cm²') +
      metric('NATIVE SHAFT DIAMETER',format(t.nonsurgical_diameter_um,2),gain == null ? 'No baseline hairs' : `+${format(gain,2)} μm from baseline`,'Modeled average · μm') +
      metric('TRANSPLANTED GRAFTS',mode === 'combined' ? format(t.combined_grafts) : '0',mode === 'combined' ? `${format(t.grafts_saved)} fewer than transplant alone` : 'Non-surgical procedure','Grafts are distinct from hairs');
    el('savings').hidden = !['combined','compare'].includes(mode);
    el('saved-count').textContent = format(t.grafts_saved);
    el('saved-percent').textContent = format(t.grafts_saved_percent,1) + '%';
    el('saved-detail').textContent = `${format(t.transplant_grafts)} grafts alone → ${format(t.combined_grafts)} grafts with ${model.protocol_info.label.toLowerCase()}.`;
    const rows = [
      ['Terminal hair count',format(t.baseline_hairs),format(t.transplant_hairs),format(t.nonsurgical_hairs),format(t.combined_hairs)],
      ['Additional terminal hairs','—','+'+format(t.transplant_added_hairs),'+'+format(t.added_hairs),'+'+format(t.combined_hairs-t.baseline_hairs)],
      ['Terminal density · hairs/cm²',format(t.baseline_density,1),format(t.transplant_density,1),format(t.nonsurgical_density,1),format(t.combined_density,1)],
      ['Native shaft diameter · μm',format(t.baseline_diameter_um,2),format(t.baseline_diameter_um,2),format(t.nonsurgical_diameter_um,2),format(t.nonsurgical_diameter_um,2)],
      ['Transplanted grafts','0',format(t.transplant_grafts),'0',format(t.combined_grafts)],
      ['Grafts saved vs transplant alone','—','—','Not a matched transplant target',format(t.grafts_saved)],
    ];
    el('comparison-body').innerHTML = rows.map(row => '<tr>'+row.map(v=>`<td>${escape(v)}</td>`).join('')+'</tr>').join('');
    el('timepoint-note').textContent = model.horizon === 'six_months' ?
      `All paths are compared at month 6. Transplant assumptions: ${format(model.hairs_per_graft,1)} hairs/graft, ${format(model.graft_survival_percent)}% survival and ${format(model.visible_growth_percent)}% visible growth. Transplanted-shaft diameter is not predicted.` :
      'Non-surgical response is modeled at month 6. Transplant and combined graft counts are compared at the mature transplant target; this is a staged planning comparison, not simultaneous six-month outcomes. Transplanted-shaft diameter is not predicted.';
    el('density-evidence').textContent = model.protocol_info.density_note;
    el('thickness-evidence').textContent = model.protocol_info.diameter_note;
  }
  function drawPreviews() {
    const kinds = mode === 'compare' ? ['transplant','nonsurgical'] : mode === 'combined' ? ['baseline','combined'] : ['baseline','nonsurgical'];
    const titles = {baseline:'Baseline photograph',nonsurgical:'Non-surgical · month 6',transplant:'Transplant alone',combined:'Combined treatment'};
    const symbols = {baseline:'↑',nonsurgical:'6',transplant:'T',combined:'+'};
    el('preview-title').textContent = mode === 'compare' ? 'Transplant vs non-surgical' : mode === 'combined' ? 'One combined restoration plan' : 'Six-month non-surgical preview';
    el('preview-grid').innerHTML = kinds.map(kind => {
      const url = kind === 'baseline' ? baseline?.url : results[kind]?.resultUrl;
      const note = kind === 'baseline' ? 'Same photo for all comparisons' : kind === 'nonsurgical' ? '0 transplanted grafts' : model ? `${format(model.totals[kind+'_grafts'])} transplanted grafts · ${model.horizon==='six_months'?'month 6':'mature target'}` : 'Set the planning inputs';
      return `<article class="preview-card"><div class="image-stage">${url ? `<img src="${escape(url)}" alt="${escape(titles[kind])}">` : `<div class="preview-empty"><div class="orb">${symbols[kind]}</div>${kind==='baseline'?'Upload a baseline photo':'Generate a preview from your reviewed scenario'}</div>`}</div><div class="preview-caption"><strong>${titles[kind]}</strong><small>${escape(note)}</small>${kind === 'baseline' ? '' : `<button class="button" data-generate="${kind}" ${busy||!baseline||!model||!el('reviewed').checked?'disabled':''}>${busy ? 'Generating…' : url ? 'View saved simulation' : 'Generate preview'}</button>`}${url && kind!=='baseline' ? `<a href="${escape(url)}?download=1">Download labeled image</a>` : ''}</div></article>`;
    }).join('');
  }
  async function generate(kind) {
    if (busy || !baseline || !model) return;
    if (results[kind]) { status('This saved simulation already matches the current photo and assumptions.'); return; }
    if (!el('reviewed').checked) { status('Review the measurements and assumptions first.', true); return; }
    const version = revision, snapshot = scenario(), imageId = baseline.imageId;
    busy = true; drawPreviews(); status('Generating your simulation. This may take a few minutes.');
    try {
      const result = await post('/api/360/generate', {view:kind, scenario:snapshot, image_id:imageId, reviewed:true});
      if (version !== revision || imageId !== baseline?.imageId) { status('The inputs changed during generation. Update the current plan before generating again.'); return; }
      results[kind] = result;
      status(result.billingRecorded === false ? 'Simulation ready. Usage recording is awaiting confirmation.' : 'Simulation ready. The image is an illustration of this planning scenario.');
    } catch (error) { status(error.message, true); }
    finally { busy = false; drawPreviews(); }
  }
  function sendToLegacy() {
    const frame = el('transplant-frame');
    if (frame.getAttribute('src') && baseline) frame.contentWindow.postMessage({type:'studio360:baseline', baseline, selections:zones.map(z=>({area:z.area,density:z.density}))}, location.origin);
  }
  function useBaseline(data, notifyFrame = true) {
    if (!data?.imageId || !/^[a-f0-9]{32}$/.test(data.imageId)) return;
    baseline = {imageId:data.imageId, filename:data.filename, url:'/api/360/image/'+data.imageId};
    el('source-thumb').src = baseline.url; el('source-thumb').hidden = false; el('upload-placeholder').hidden = true;
    invalidate(); if (notifyFrame) sendToLegacy();
  }
  async function upload(file) {
    if (!file) return;
    if (file.size > 16*1024*1024) { status('Please choose an image under 16 MB.', true); return; }
    el('photo-input').disabled = true; status('Preparing the shared baseline photograph…');
    const form = new FormData(); form.append('image', file);
    try { const result = await post('/upload', form, true); useBaseline(result); status('Baseline photo ready. Review the measurements for this photo.'); }
    catch (error) { status(error.message, true); }
    finally { el('photo-input').disabled = false; el('photo-input').value = ''; }
  }
  function setMode(next) {
    mode = next;
    document.querySelectorAll('[data-mode]').forEach(button => {const active = button.dataset.mode === mode; button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
    el('legacy-panel').hidden = mode !== 'transplant'; el('planner-panel').hidden = mode === 'transplant';
    if (mode !== 'transplant') el('planner-panel').setAttribute('aria-labelledby','tab-'+mode);
    if (mode === 'transplant') {const frame = el('transplant-frame'); if (!frame.getAttribute('src')) frame.src=frame.dataset.src; else sendToLegacy();}
    renderModel(); drawPreviews();
  }
  document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click',()=>setMode(button.dataset.mode)));
  document.querySelector('.mode-tabs').addEventListener('keydown', event => {
    const buttons=[...document.querySelectorAll('[data-mode]')], current=buttons.indexOf(document.activeElement);
    if (current<0 || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault(); let next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
    setMode(buttons[next].dataset.mode);buttons[next].focus();
  });
  inputs.forEach(id => el(id).addEventListener('input',()=>{
    if(id==='protocol')setPreset();
    if(id==='diameter-mode')setThicknessPreset();
    if(id==='horizon')el('visibility').disabled=el('horizon').value==='mature';
    invalidate();
  }));
  el('reset-preset').addEventListener('click',()=>{setPreset();invalidate();});
  el('study-preset').addEventListener('click',()=>{el('diameter-mode').value='absolute';setThicknessPreset();el('diameter-change').value='2.38';invalidate();});
  el('photo-input').addEventListener('change',event=>upload(event.target.files[0]));
  el('reviewed').addEventListener('change',drawPreviews);
  el('zone-rows').addEventListener('input',event=>{
    const field=event.target.dataset.field, row=Number(event.target.dataset.row);
    if(field && zones[row]){zones[row][field]=event.target.value===''?null:Number(event.target.value);invalidate();}
  });
  el('zone-rows').addEventListener('click',event=>{
    const button=event.target.closest('[data-remove]');if(!button)return;
    zones.splice(Number(button.dataset.remove),1);renderZones();invalidate();
  });
  el('add-zone').addEventListener('click',()=>{
    const area=el('add-zone-select').value;if(!area||zones.some(z=>z.area===area))return;
    zones.push({area,density:'moderate',area_cm2:25,baseline_density:100,baseline_diameter_um:40,responsive_percent:100,grafts:cfg.graftCounts[area].moderate});renderZones();invalidate();
  });
  el('toggle-zones').addEventListener('click',()=>{const hidden=!el('zones-reference').hidden;el('zones-reference').hidden=hidden;el('toggle-zones').setAttribute('aria-expanded',String(!hidden));});
  el('preview-grid').addEventListener('click',event=>{const button=event.target.closest('[data-generate]');if(button)generate(button.dataset.generate);});
  el('transplant-frame').addEventListener('load',sendToLegacy);
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin||event.source!==el('transplant-frame').contentWindow)return;
    if(event.data?.type==='studio360:uploaded')useBaseline(event.data.data,false);
    if(event.data?.type==='studio360:selections' && Array.isArray(event.data.selections)){
      const valid=event.data.selections.filter(s=>cfg.graftCounts[s.area]?.[s.density]!=null);
      zones=valid.map(s=>({...zones.find(z=>z.area===s.area)||{area_cm2:25,baseline_density:100,baseline_diameter_um:40,responsive_percent:100},area:s.area,density:s.density,grafts:cfg.graftCounts[s.area][s.density]}));renderZones();invalidate();
    }
  });
  el('download-report').addEventListener('click',()=>{
    if(!model){status('Complete a valid scenario before saving a report.',true);return;}
    const report={application:'Hair Studio 360',created_at:new Date().toISOString(),status:'Illustrative planning simulation',assumptions:scenario(),results:model};
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='Hair-Studio-360-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  setPreset();renderZones();calculateModel();drawPreviews();
})();
