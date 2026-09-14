(() => {
  if (window.parent === window || !new URLSearchParams(location.search).has('studio360')) return;
  let receiving = false;
  window.addEventListener('studio360-upload', event => {
    if (!receiving) window.parent.postMessage({type:'studio360:uploaded',data:event.detail},location.origin);
  });
  document.addEventListener('change', event => {
    if (!receiving && (event.target.matches('input[name="area"]') || event.target.name?.startsWith('density-')))
      window.parent.postMessage({type:'studio360:selections',selections:getSelectedAreasWithDensity()},location.origin);
  });
  window.addEventListener('message', event => {
    if(event.origin!==location.origin || event.source!==window.parent || event.data?.type!=='studio360:baseline')return;
    const baseline=event.data.baseline;
    if(!/^[a-f0-9]{32}\.png$/.test(baseline?.filename||'')||!/^\/api\/360\/image\/[a-f0-9]{32}$/.test(baseline?.url||''))return;
    receiving=true;
    const changed=uploadedFilename!==baseline.filename;
    uploadedFilename=baseline.filename;beforeImageUrl=baseline.url;
    document.getElementById('uploadedImage').src=baseline.url;
    document.getElementById('optionsPatientPhoto').src=baseline.url;
    document.getElementById('imagePreview').style.display='block';
    if(changed){afterImageUrl=null;document.getElementById('step-upload').style.display='block';document.getElementById('step-options').style.display='none';document.getElementById('step-results').style.display='none';}
    if(Array.isArray(event.data.selections)){
      document.querySelectorAll('input[name="area"]').forEach(box=>{box.checked=event.data.selections.some(s=>s.area===box.value);box.dispatchEvent(new Event('change',{bubbles:true}));});
      for(const s of event.data.selections){if(!graftCounts[s.area]?.[s.density])continue;const radio=document.querySelector(`input[name="density-${s.area}"][value="${s.density}"]`);if(radio)radio.checked=true;}
      updateGraftSummary();
    }
    receiving=false;
  });
})();
