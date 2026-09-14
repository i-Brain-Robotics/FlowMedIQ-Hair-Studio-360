// ============================================
// FUEsion AI Hair Studio - Application Logic
// Updated with new scalp zone system (Areas 1-7)
// ============================================

var uploadedFilename = null;
var beforeImageUrl = null;
var afterImageUrl = null;
var currentSelections = [];
var totalEstimatedGrafts = 0;

// Graft counts for each area and density level (based on scalp zone diagram)
// Area 7 (Donor) is never selected
const graftCounts = {
    area1: {
        full: 750,
        moderate: 600
    },
    area2: {
        full: 1250,
        moderate: 1000
    },
    area3: {
        full: 1600,
        moderate: 1250,
        camouflage: 900
    },
    area4: {
        full: 1200,
        moderate: 900,
        camouflage: 600
    },
    area5a: {
        full: 750,
        moderate: 500,
        camouflage: 350
    },
    area5b: {
        full: 750,
        moderate: 500,
        camouflage: 350
    },
    area6a: {
        full: 600,
        moderate: 450,
        camouflage: 300
    },
    area6b: {
        full: 600,
        moderate: 450,
        camouflage: 300
    }
};

// Area display names
const areaNames = {
    area1: 'Area 1 - Temporal Peaks',
    area2: 'Area 2 - Frontal Hairline Band',
    area3: 'Area 3 - Frontal Forelock',
    area4: 'Area 4 - Mid-Scalp Bridge Zone',
    area5a: 'Area 5A - Anterior Crown Ring',
    area5b: 'Area 5B - Post-Crown Ring',
    area6a: 'Area 6A - Front Crown',
    area6b: 'Area 6B - Back Crown'
};

// Area descriptions
const areaDescriptions = {
    area1: 'Frontal hairline edge',
    area2: 'Behind the hairline',
    area3: 'Central top of scalp',
    area4: 'Between frontal & crown',
    area5a: 'In front of crown',
    area5b: 'Behind crown',
    area6a: 'Front half of crown',
    area6b: 'Back half of crown'
};

// Density display info
const densityInfo = {
    full: { name: 'Full', fu: '40-45 FU/cm²' },
    moderate: { name: 'Moderate', fu: '30-35 FU/cm²' },
    camouflage: { name: 'Camouflage', fu: '20 FU/cm²' }
};

// ── Upload spinner helpers ──────────────────────────────────────────────────
const UPLOAD_MSGS = [
    'Removing background…',
    'Isolating hair regions…',
    'Preparing photo for analysis…'
];
let _uploadMsgTimer = null;
function showUploadSpinner() {
    const areaBox  = document.getElementById('upload-area-box');
    const uploadUI = document.getElementById('upload-ui');
    const proc     = document.getElementById('upload-processing');
    const lbl      = document.getElementById('upload-spinner-label');
    if (!proc) return;
    if (areaBox)  areaBox.style.pointerEvents = 'none';
    if (uploadUI) uploadUI.style.display = 'none';
    proc.classList.add('active');
    let idx = 0;
    if (lbl) lbl.textContent = UPLOAD_MSGS[0];
    _uploadMsgTimer = setInterval(() => {
        idx = (idx + 1) % UPLOAD_MSGS.length;
        if (lbl) {
            lbl.style.opacity = '0';
            setTimeout(() => { lbl.textContent = UPLOAD_MSGS[idx]; lbl.style.opacity = '1'; }, 220);
        }
    }, 1800);
}
function hideUploadSpinner() {
    const areaBox  = document.getElementById('upload-area-box');
    const uploadUI = document.getElementById('upload-ui');
    const proc     = document.getElementById('upload-processing');
    if (!proc) return;
    clearInterval(_uploadMsgTimer);
    proc.classList.remove('active');
    if (uploadUI) uploadUI.style.display = '';
    if (areaBox)  areaBox.style.pointerEvents = '';
}

// ── Generation spinner cycling ────────────────────────────────────────────
const GEN_MSGS = [
    { main: 'Analysing hair pattern…',         sub: 'Mapping follicle density and zones' },
    { main: 'Applying restoration model…',     sub: 'AI is placing virtual grafts' },
    { main: 'Rendering transformation…',       sub: 'Blending with your natural hair' },
    { main: 'Refining final details…',         sub: 'Almost there — polishing the result' },
    { main: 'Creating your preview…',          sub: 'Finalising the before & after image' }
];
let _genMsgTimer = null;
function startGenSpinner() {
    const msgEl = document.getElementById('gen-msg');
    const subEl = document.getElementById('gen-sub');
    if (!msgEl) return;
    let idx = 0;
    msgEl.textContent = GEN_MSGS[0].main;
    if (subEl) subEl.textContent = GEN_MSGS[0].sub;
    _genMsgTimer = setInterval(() => {
        idx = (idx + 1) % GEN_MSGS.length;
        msgEl.classList.remove('visible');
        setTimeout(() => {
            msgEl.textContent = GEN_MSGS[idx].main;
            if (subEl) subEl.textContent = GEN_MSGS[idx].sub;
            msgEl.classList.add('visible');
        }, 300);
    }, 3500);
}
function stopGenSpinner() {
    clearInterval(_genMsgTimer);
}

// Handle image upload
document.getElementById('imageInput').addEventListener('change', async function(e) {
    const file = e.target.files[0];
    if (!file) return;
    showUploadSpinner();
    const formData = new FormData();
    formData.append('image', file);
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        hideUploadSpinner();
        if (data.success) {
            uploadedFilename = data.filename;
            window.dispatchEvent(new CustomEvent('studio360-upload', {detail: data}));
            beforeImageUrl = data.url;
            // Show preview
            document.getElementById('uploadedImage').src = data.url;
            document.getElementById('imagePreview').style.display = 'block';
            // Voice announcement
            if (window.FUEsionVoice) {
                window.FUEsionVoice.announceStatus('Photo uploaded successfully. You can continue to options, or ask me to create a treatment plan for you.');
            }
        } else {
            showNotification('Upload failed: ' + data.error, 'error');
        }
    } catch (error) {
        hideUploadSpinner();
        showNotification('Upload error: ' + error.message, 'error');
    }
});

// Rotate the currently uploaded image 90 degrees clockwise (server-side, free action)
async function rotateUploadedImage() {
    if (!uploadedFilename) {
        showNotification('Please upload or take a photo first', 'warning');
        return;
    }
    const btn = document.getElementById('rotateImageBtn');
    if (btn) btn.disabled = true;
    try {
        const response = await fetch('/rotate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: uploadedFilename, degrees: 90 })
        });
        const data = await response.json();
        if (data.success) {
            window.dispatchEvent(new CustomEvent('studio360-upload', {detail: data}));
            // data.url carries a cache-busting token so the browser reloads the rotated image
            beforeImageUrl = data.url;
            const img = document.getElementById('uploadedImage');
            if (img) img.src = data.url;
            const optionsPhoto = document.getElementById('optionsPatientPhoto');
            if (optionsPhoto) optionsPhoto.src = data.url;
            if (window.FUEsionVoice && window.FUEsionVoice.announceStatus) {
                window.FUEsionVoice.announceStatus('Photo rotated.');
            }
        } else {
            showNotification('Rotate failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        showNotification('Rotate error: ' + error.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}
window.rotateUploadedImage = rotateUploadedImage;

// Initialize event listeners for area checkboxes and density options

// ── CRM Integration ──────────────────────────────────────────────
async function setCrmKey(slug, linkId) {
    const key = prompt('Paste your FlowGeniQ CRM API key (starts with fcrm_...)\nLeave blank to disconnect CRM:', '');
    if (key === null) return; // cancelled
    try {
        const resp = await fetch('/demo/api/set-crm-key/' + slug, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ crm_api_key: key.trim() })
        });
        const data = await resp.json();
        if (data.success) {
            showNotification(data.crm_connected ? 'CRM connected! Leads will auto-push.' : 'CRM disconnected.', 'success');
            loadDemoLinks();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (err) {
        showNotification('Error: ' + err.message, 'error');
    }
}
// ─────────────────────────────────────────────────────────────────

// ── Retroactive CRM Push ──────────────────────────────────────────
async function pushAllToCrm() {
    const btn = document.getElementById('push-all-crm-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Pushing...'; }
    try {
        const resp = await fetch('/demo/api/retry-crm-push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.success) {
            const msg = data.pushed === 0
                ? 'No new leads to push (already pushed or no CRM key set)'
                : `Pushed ${data.pushed} lead${data.pushed !== 1 ? 's' : ''} to CRM!`;
            showNotification(msg, data.pushed > 0 ? 'success' : 'info');
        } else {
            showNotification('CRM push failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (err) {
        showNotification('Error: ' + err.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = 'Push All Verified to CRM'; }
}
// ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    // Add event listeners to area checkboxes
    const areaCheckboxes = document.querySelectorAll('input[name="area"]');
    areaCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateGraftSummary);
    });
    
    // Add event listeners to density radio buttons
    const densityRadios = document.querySelectorAll('input[type="radio"][name^="density-"]');
    densityRadios.forEach(radio => {
        radio.addEventListener('change', updateGraftSummary);
    });
    
    // Initial update
    updateGraftSummary();
});

function updateGraftSummary() {
    const selectedAreas = getSelectedAreasWithDensity();
    const summaryDetails = document.getElementById('summary-details');
    const totalGraftsDiv = document.getElementById('total-grafts');
    const totalGraftCount = document.getElementById('total-graft-count');
    
    if (selectedAreas.length === 0) {
        summaryDetails.innerHTML = '<p class="no-selection">Please select at least one area to see the estimate</p>';
        totalGraftsDiv.style.display = 'none';
        return;
    }
    
    let total = 0;
    let detailsHtml = '<ul class="summary-list">';
    
    selectedAreas.forEach(item => {
        const grafts = graftCounts[item.area][item.density];
        total += grafts;
        
        const densityLabel = densityInfo[item.density].name;
        const fuInfo = densityInfo[item.density].fu;
        
        detailsHtml += `<li>
            <span><strong>${areaNames[item.area]}</strong> <span style="color: #888;">(${densityLabel} - ${fuInfo})</span></span>
            <span style="color: #e94560; font-weight: 600;">${grafts} Grafts</span>
        </li>`;
    });
    
    detailsHtml += '</ul>';
    summaryDetails.innerHTML = detailsHtml;
    
    // Show total
    totalGraftCount.textContent = total;
    totalGraftsDiv.style.display = 'flex';
}

function getSelectedAreasWithDensity() {
    const selectedAreas = [];
    const areaCheckboxes = document.querySelectorAll('input[name="area"]:checked');
    
    areaCheckboxes.forEach(checkbox => {
        const area = checkbox.value;
        const densityRadio = document.querySelector(`input[name="density-${area}"]:checked`);
        const density = densityRadio ? densityRadio.value : 'moderate';
        
        selectedAreas.push({
            area: area,
            density: density
        });
    });
    
    return selectedAreas;
}

function continueToOptions() {
    // Copy uploaded image to the options step preview
    const uploadedImg = document.getElementById('uploadedImage');
    const optionsPhoto = document.getElementById('optionsPatientPhoto');
    if (uploadedImg && optionsPhoto) {
        optionsPhoto.src = uploadedImg.src;
    }
    document.getElementById('step-upload').style.display = 'none';
    document.getElementById('step-options').style.display = 'block';
    updateGraftSummary();
}

function backToUpload() {
    document.getElementById('step-options').style.display = 'none';
    document.getElementById('step-upload').style.display = 'block';
}

async function generateHair() {
    if (!uploadedFilename) {
        showNotification('Please upload an image first', 'warning');
        return;
    }
    
    // Get selected areas with their density levels
    const selectedAreas = getSelectedAreasWithDensity();
    
    if (selectedAreas.length === 0) {
        showNotification('Please select at least one area', 'warning');
        return;
    }
    
    // Store current selections for later use
    currentSelections = selectedAreas;
    
    // Show results step with loading
    document.getElementById('step-options').style.display = 'none';
    document.getElementById('step-results').style.display = 'block';
    document.getElementById('loadingIndicator').style.display = 'block';
    document.getElementById('resultsContainer').style.display = 'none';
    startGenSpinner();
    
    try {
        const response = await fetch('/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                filename: uploadedFilename,
                areaSelections: selectedAreas
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            afterImageUrl = data.resultUrl;
            
            // Show results
            document.getElementById('beforeImage').src = data.originalUrl;
            document.getElementById('afterImage').src = data.resultUrl;
            
            // Display results summary
            displayResultsSummary(selectedAreas, data.graftSummary);
            
            // Update usage display in UI
            if (data.usage) {
                updateUsageDisplay(data.usage);
            }
            
            stopGenSpinner();
            document.getElementById('loadingIndicator').style.display = 'none';
            document.getElementById('resultsContainer').style.display = 'block';
            
            // Voice announcement
            if (window.FUEsionVoice) {
                window.FUEsionVoice.announceStatus('Your hair restoration preview is ready! You can download the results, share them, or generate a 360 degree turntable view.');
            }
        } else {
            // Insufficient-credit / limit-reached path: show actionable CTA
            if (data.limitReached || /insufficient|limit|credit/i.test(String(data.error || ''))) {
                showInsufficientCreditsNotification(data.error || 'Insufficient credits to generate. Top up to continue.');
            } else if (data.retryable) {
                document.getElementById('step-results').style.display = 'none';
                document.getElementById('step-options').style.display = 'block';
                showNotification(data.error || 'Image generation is temporarily unavailable. Please try again in a few minutes.', 'warning');
            } else {
                showNotification('Generation failed: ' + data.error, 'error');
            }
            stopGenSpinner();
            document.getElementById('loadingIndicator').style.display = 'none';
            if (window.FUEsionVoice) {
                window.FUEsionVoice.announceStatus(
                    data.retryable
                        ? 'Image generation is temporarily unavailable. Please try again in a few minutes.'
                        : 'Generation failed. Please try again.'
                );
            }
        }
    } catch (error) {
        stopGenSpinner();
        showNotification('Generation error: ' + error.message, 'error');
        document.getElementById('loadingIndicator').style.display = 'none';
        if (window.FUEsionVoice) {
            window.FUEsionVoice.announceStatus('There was an error during generation. Please try again.');
        }
    }
}

function displayResultsSummary(selectedAreas, graftSummary) {
    const resultsDetails = document.getElementById('results-details');
    
    let total = 0;
    let html = '<ul class="results-list">';
    
    selectedAreas.forEach(item => {
        const grafts = graftCounts[item.area][item.density];
        total += grafts;
        
        const densityLabel = densityInfo[item.density].name;
        const fuInfo = densityInfo[item.density].fu;
        
        html += `<li>
            <span><strong>${areaNames[item.area]}</strong> <span style="color: #888;">(${densityLabel} - ${fuInfo})</span></span>
            <span style="color: #e94560; font-weight: 600;">${grafts} Grafts</span>
        </li>`;
    });
    
    html += '</ul>';
    html += `<div class="results-total"><strong>Total Estimated Grafts: ${total}</strong></div>`;
    
    resultsDetails.innerHTML = html;

    // Store total for the cost estimate feature and reset any prior result
    totalEstimatedGrafts = total;
    const costResultEl = document.getElementById('cost-estimate-result');
    if (costResultEl) {
        costResultEl.style.display = 'none';
        costResultEl.innerHTML = '';
    }
    const costBtn = document.getElementById('cost-estimate-btn');
    if (costBtn) {
        costBtn.style.display = 'inline-flex';
    }
}

// Map an estimated graft count to an indicative cost range.
// Uses window.USER_COST_TIERS (injected at page load from the server) so each
// practitioner's custom pricing is reflected without a page reload.
function formatPrice(n) {
    if (n == null) return '';
    return '$' + Number(n).toLocaleString();
}

function getCostRangeForGrafts(grafts) {
    const tiers = (window.USER_COST_TIERS && window.USER_COST_TIERS.length === 6)
        ? window.USER_COST_TIERS
        : [
            {maxGrafts: 1500,  min: 7000,  max: 7500,  fixed: null},
            {maxGrafts: 2500,  min: 7500,  max: 8250,  fixed: null},
            {maxGrafts: 3000,  min: 8250,  max: 8750,  fixed: null},
            {maxGrafts: 3500,  min: 8750,  max: 9500,  fixed: null},
            {maxGrafts: 4000,  min: 9500,  max: 10000, fixed: null},
            {maxGrafts: null,  min: null,  max: null,  fixed: 10500},
          ];

    for (let i = 0; i < tiers.length; i++) {
        const tier = tiers[i];
        // Last tier (maxGrafts === null) always matches
        if (tier.maxGrafts === null || grafts < tier.maxGrafts) {
            if (tier.fixed != null) {
                return formatPrice(tier.fixed);
            }
            return `${formatPrice(tier.min)} - ${formatPrice(tier.max)}`;
        }
    }
    // Fallback to last tier
    const last = tiers[tiers.length - 1];
    if (last.fixed != null) return formatPrice(last.fixed);
    return `${formatPrice(last.min)} - ${formatPrice(last.max)}`;
}

function getCostEstimate() {
    const grafts = totalEstimatedGrafts || 0;
    const resultEl = document.getElementById('cost-estimate-result');
    if (!resultEl) return;

    if (grafts <= 0) {
        resultEl.innerHTML = '<div class="cost-estimate-note">Generate a preview first to estimate your cost.</div>';
        resultEl.style.display = 'block';
        return;
    }

    const range = getCostRangeForGrafts(grafts);

    resultEl.innerHTML = `
        <div class="cost-estimate-label">Estimated Procedure Cost</div>
        <div class="cost-estimate-value">${range}</div>
        <div class="cost-estimate-grafts">Based on ~${grafts.toLocaleString()} estimated grafts</div>
        <div class="cost-estimate-note">This is an indicative estimate only. Your final quote is determined during an in-clinic consultation with a qualified hair restoration specialist.</div>
    `;
    resultEl.style.display = 'block';

    if (window.FUEsionVoice) {
        window.FUEsionVoice.announceStatus(`Your estimated procedure cost is ${range}, based on approximately ${grafts} grafts. This is an indicative estimate, subject to an in-clinic consultation.`);
    }
}

function downloadImage(type) {
    const url = type === 'before' ? beforeImageUrl : afterImageUrl;
    if (!url) return;
    
    const filename = url.split('/').pop();
    const a = document.createElement('a');
    a.href = `/download/${filename}`;
    a.download = `${type}_image_${filename}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function downloadCombinedImage() {
    if (!beforeImageUrl || !afterImageUrl) {
        showNotification('Images not available', 'error');
        return;
    }
    
    try {
        // Create canvas for combined image
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        
        // Load both images
        const beforeImg = await loadImage(beforeImageUrl);
        const afterImg = await loadImage(afterImageUrl);
        
        // Calculate dimensions
        const padding = 40;
        const labelHeight = 60;
        const gap = 30;
        const summaryHeight = 250;
        const disclaimerHeight = 100;
        
        const imgWidth = Math.max(beforeImg.width, afterImg.width);
        const imgHeight = Math.max(beforeImg.height, afterImg.height);
        
        canvas.width = (imgWidth * 2) + gap + (padding * 2);
        canvas.height = imgHeight + labelHeight + summaryHeight + disclaimerHeight + (padding * 2);
        
        // Background
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Header gradient
        const headerGradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
        headerGradient.addColorStop(0, '#1a1a2e');
        headerGradient.addColorStop(1, '#16213e');
        ctx.fillStyle = headerGradient;
        ctx.fillRect(0, 0, canvas.width, labelHeight);
        
        // Title
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 24px Inter, Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('FUEsion AI Hair Studio - Before & After', canvas.width / 2, 38);
        
        // Draw images
        const imgY = labelHeight + 20;
        
        // Before image with border
        ctx.strokeStyle = '#d0d0d0';
        ctx.lineWidth = 2;
        ctx.strokeRect(padding - 2, imgY - 2, imgWidth + 4, imgHeight + 4);
        ctx.drawImage(beforeImg, padding, imgY, imgWidth, imgHeight);
        
        // After image with border
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.strokeRect(padding + imgWidth + gap - 2, imgY - 2, imgWidth + 4, imgHeight + 4);
        ctx.drawImage(afterImg, padding + imgWidth + gap, imgY, imgWidth, imgHeight);
        
        // Labels
        ctx.font = 'bold 16px Inter, Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillStyle = '#4a5568';
        ctx.fillText('BEFORE', padding + (imgWidth / 2), imgY + imgHeight + 25);
        ctx.fillStyle = '#10b981';
        ctx.fillText('AFTER', padding + imgWidth + gap + (imgWidth / 2), imgY + imgHeight + 25);
        
        // Summary section
        const summaryY = imgY + imgHeight + 50;
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(padding, summaryY, canvas.width - (padding * 2), summaryHeight - 30);
        
        ctx.fillStyle = '#1a1a2e';
        ctx.font = 'bold 18px Inter, Arial, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Treatment Summary', padding + 20, summaryY + 30);
        
        // Draw summary items
        let yPos = summaryY + 55;
        let total = 0;
        ctx.font = '14px Inter, Arial, sans-serif';
        
        currentSelections.forEach(item => {
            const grafts = graftCounts[item.area][item.density];
            total += grafts;
            const densityLabel = densityInfo[item.density].name;
            const fuInfo = densityInfo[item.density].fu;
            
            ctx.fillStyle = '#4a5568';
            ctx.fillText(`${areaNames[item.area]} (${densityLabel} - ${fuInfo})`, padding + 20, yPos);
            ctx.fillStyle = '#e94560';
            ctx.textAlign = 'right';
            ctx.fillText(`${grafts} Grafts`, canvas.width - padding - 20, yPos);
            ctx.textAlign = 'left';
            yPos += 22;
        });
        
        // Total
        yPos += 10;
        ctx.fillStyle = '#1a1a2e';
        ctx.font = 'bold 16px Inter, Arial, sans-serif';
        ctx.fillText('Total Estimated Grafts:', padding + 20, yPos);
        ctx.fillStyle = '#e94560';
        ctx.textAlign = 'right';
        ctx.fillText(total.toString(), canvas.width - padding - 20, yPos);
        
        // Disclaimer
        const disclaimerY = summaryY + summaryHeight - 10;
        ctx.fillStyle = '#fffbeb';
        ctx.fillRect(padding, disclaimerY, canvas.width - (padding * 2), disclaimerHeight - 20);
        ctx.strokeStyle = '#f0d78c';
        ctx.lineWidth = 1;
        ctx.strokeRect(padding, disclaimerY, canvas.width - (padding * 2), disclaimerHeight - 20);
        
        ctx.fillStyle = '#6b5a3e';
        ctx.font = '11px Inter, Arial, sans-serif';
        ctx.textAlign = 'left';
        const disclaimerText = 'Important Disclaimer: This visualization is a rough estimate generated by AI for illustrative purposes only. It does not guarantee actual surgical results. Individual outcomes vary based on hair characteristics, donor area quality, scalp laxity, and surgical technique. Please consult with a qualified hair restoration specialist.';
        wrapText(ctx, disclaimerText, padding + 15, disclaimerY + 20, canvas.width - (padding * 2) - 30, 14);
        
        // Download
        const link = document.createElement('a');
        link.download = `fuesian_before_after_${Date.now()}.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();
        
    } catch (error) {
        showNotification('Error creating combined image: ' + error.message, 'error');
    }
}

function loadImage(src) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = src;
    });
}

function wrapText(ctx, text, x, y, maxWidth, lineHeight) {
    const words = text.split(' ');
    let line = '';
    
    for (let n = 0; n < words.length; n++) {
        const testLine = line + words[n] + ' ';
        const metrics = ctx.measureText(testLine);
        const testWidth = metrics.width;
        
        if (testWidth > maxWidth && n > 0) {
            ctx.fillText(line, x, y);
            line = words[n] + ' ';
            y += lineHeight;
        } else {
            line = testLine;
        }
    }
    ctx.fillText(line, x, y);
}

async function downloadPDF() {
    if (!beforeImageUrl || !afterImageUrl) {
        showNotification('Images not available', 'error');
        return;
    }
    
    try {
        // Prepare selection data for PDF
        const selections = currentSelections.map(item => ({
            area: areaNames[item.area],
            density: densityInfo[item.density].name,
            fuPerCm2: densityInfo[item.density].fu,
            grafts: graftCounts[item.area][item.density]
        }));
        
        let total = 0;
        currentSelections.forEach(item => {
            total += graftCounts[item.area][item.density];
        });
        
        const response = await fetch('/generate-pdf', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                beforeImage: beforeImageUrl,
                afterImage: afterImageUrl,
                selections: selections,
                total: total,
                date: new Date().toLocaleDateString('en-US', { 
                    year: 'numeric', 
                    month: 'long', 
                    day: 'numeric' 
                })
            })
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `fuesian_report_${Date.now()}.pdf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } else {
            const error = await response.json();
            showNotification('PDF generation failed: ' + error.error, 'error');
        }
    } catch (error) {
        showNotification('PDF download error: ' + error.message, 'error');
    }
}

function startOver() {
    // Reset state
    uploadedFilename = null;
    beforeImageUrl = null;
    afterImageUrl = null;
    currentSelections = [];
    
    // Reset turntable state
    turntableSessionId = null;
    turntableImages = [];
    currentTurntableIndex = 0;
    if (autoRotateInterval) {
        clearInterval(autoRotateInterval);
        autoRotateInterval = null;
    }
    isAutoRotating = false;
    
    // Reset UI
    document.getElementById('imageInput').value = '';
    document.getElementById('uploadedImage').src = '';
    document.getElementById('imagePreview').style.display = 'none';
    
    // Reset turntable UI
    document.getElementById('turntable-start').style.display = 'block';
    document.getElementById('turntable-progress').style.display = 'none';
    document.getElementById('turntable-viewer').style.display = 'none';
    document.getElementById('turntable-progress-bar').style.width = '0%';
    document.getElementById('turntable-thumbnails').innerHTML = '';
    
    // Uncheck all areas
    document.querySelectorAll('input[name="area"]').forEach(cb => cb.checked = false);
    
    // Reset density to moderate for all areas
    document.querySelectorAll('input[type="radio"][value="moderate"]').forEach(radio => radio.checked = true);
    
    // Show upload step
    document.getElementById('step-results').style.display = 'none';
    document.getElementById('step-options').style.display = 'none';
    document.getElementById('step-upload').style.display = 'block';
    
    // Update summary
    updateGraftSummary();
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">×</button>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 5000);
}

/**
 * Show an insufficient-credit notification with a clickable
 * "Get more credits" button that deep-links to the Suite hub's
 * credit-packs modal. Stays visible for 12s (longer than a normal toast).
 */
function showInsufficientCreditsNotification(message) {
    const suiteBase = (window.SUITE_URL || 'https://suite.flowmediq.io').replace(/\/$/, '');
    const buyPacksUrl = `${suiteBase}/?openPacks=1`;
    const subscribeUrl = `${suiteBase}/?openPlans=1`;
    const notification = document.createElement('div');
    notification.className = 'notification notification-error';
    notification.style.flexDirection = 'column';
    notification.style.alignItems = 'flex-start';
    notification.style.gap = '10px';
    notification.style.maxWidth = '380px';
    notification.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:flex-start;width:100%;gap:8px;">
            <span>${message || 'Insufficient credits to complete this action.'}</span>
            <button onclick="this.closest('.notification').remove()" style="background:none;border:none;color:inherit;font-size:18px;cursor:pointer;line-height:1;">×</button>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;width:100%;">
            <a href="${buyPacksUrl}" target="_blank" rel="noopener"
               style="padding:8px 14px;background:#fff;color:#111;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;display:inline-flex;align-items:center;gap:6px;">
                Get more credits
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M7 17 17 7"/><path d="M7 7h10v10"/></svg>
            </a>
            <a href="${subscribeUrl}" target="_blank" rel="noopener"
               style="padding:8px 14px;background:transparent;color:inherit;border:1px solid currentColor;border-radius:8px;text-decoration:none;font-size:13px;font-weight:500;display:inline-flex;align-items:center;gap:6px;">
                Subscribe
            </a>
        </div>
    `;
    document.body.appendChild(notification);
    setTimeout(() => { if (notification.parentElement) notification.remove(); }, 12000);
}

function updateUsageDisplay(usage) {
    // Update the user bar from the Suite's shared-credit-pool response.
    // app_remaining/app_cap remain as compatibility fallbacks for older APIs.
    const usageDisplay = document.getElementById('usage-display');
    if (usageDisplay && usage) {
        let displayText = 'Credits: ';
        const remaining = usage.pool_remaining !== undefined
            ? usage.pool_remaining
            : (usage.app_remaining !== undefined ? usage.app_remaining : 0);
        const total = usage.pool_total !== undefined
            ? usage.pool_total
            : usage.app_cap;
        if (usage.unlimited || remaining === 'Unlimited' || total === 'Unlimited') {
            displayText += 'Unlimited';
        } else if (total !== undefined && total !== null && total > 0) {
            displayText += `${remaining} / ${total} remaining`;
        } else {
            displayText += `${remaining} remaining`;
        }
        usageDisplay.textContent = displayText;
    }
}

// ============================================
// 360° Turntable Feature
// ============================================

var turntableSessionId = null;
var turntableImages = [];
var currentTurntableIndex = 0;
var autoRotateInterval = null;
var isAutoRotating = false;
var isDragging = false;
var dragStartX = 0;
var dragStartIndex = 0;

async function startTurntableGeneration() {
    if (!afterImageUrl) {
        showNotification('Please generate a preview image first', 'warning');
        return;
    }
    
    // Hide start button, show progress
    document.getElementById('turntable-start').style.display = 'none';
    document.getElementById('turntable-progress').style.display = 'block';
    document.getElementById('turntable-viewer').style.display = 'none';
    
    try {
        // Prepare graft summary for sharing
        let graftSummaryForShare = null;
        if (currentSelections.length > 0) {
            let total = 0;
            const areas = currentSelections.map(item => {
                const grafts = graftCounts[item.area][item.density];
                total += grafts;
                return {
                    area: areaNames[item.area],
                    density: densityInfo[item.density].name,
                    fuPerCm2: densityInfo[item.density].fu,
                    grafts: grafts
                };
            });
            graftSummaryForShare = { areas: areas, total: total };
        }
        
        const response = await fetch('/generate-turntable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                afterImageUrl: afterImageUrl,
                beforeImageUrl: beforeImageUrl,
                graftSummary: graftSummaryForShare
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            turntableSessionId = data.sessionId;
            pollTurntableProgress();
        } else if (data.limitReached) {
            // Insufficient credits
            showInsufficientCreditsNotification(data.error || 'Insufficient credits for 360° turntable. You need 8 credits.');
            document.getElementById('turntable-start').style.display = 'block';
            document.getElementById('turntable-progress').style.display = 'none';
        } else {
            showNotification('Failed to start turntable generation: ' + data.error, 'error');
            document.getElementById('turntable-start').style.display = 'block';
            document.getElementById('turntable-progress').style.display = 'none';
        }
    } catch (error) {
        showNotification('Error starting turntable generation: ' + error.message, 'error');
        document.getElementById('turntable-start').style.display = 'block';
        document.getElementById('turntable-progress').style.display = 'none';
    }
}

async function pollTurntableProgress() {
    if (!turntableSessionId) return;
    
    try {
        const response = await fetch(`/turntable-progress/${turntableSessionId}`);
        const data = await response.json();
        
        // Update progress UI
        const progressBar = document.getElementById('turntable-progress-bar');
        const statusText = document.getElementById('turntable-status-text');
        const progressCount = document.getElementById('turntable-progress-count');
        const currentAngle = document.getElementById('turntable-current-angle');
        
        const percent = (data.completed / data.total) * 100;
        progressBar.style.width = percent + '%';
        progressCount.textContent = `${data.completed} / ${data.total}`;
        currentAngle.textContent = `Generating: ${data.currentView || data.currentAngle + '°'} (Credits used: ${data.creditsUsed || 0}/8)`;
        
        if (data.status === 'analyzing') {
            statusText.textContent = 'Analyzing image features...';
        } else if (data.status === 'generating') {
            statusText.textContent = 'Generating rotation images...';
        } else if (data.status === 'complete') {
            statusText.textContent = `Complete! (${data.creditsUsed || 8} credits used)`;
            progressBar.style.width = '100%';
            
            // Refresh the usage display in the header to reflect deducted credits
            try {
                const userInfoResp = await fetch('/api/user-info');
                const userInfo = await userInfoResp.json();
                if (userInfo.usage) {
                    updateUsageDisplay(userInfo.usage);
                }
            } catch (e) {
                console.error('Error refreshing usage display:', e);
            }
            
            // Load the turntable viewer
            turntableImages = data.images;
            initTurntableViewer();
            return;
        } else if (data.status === 'error') {
            statusText.textContent = 'Error: ' + data.error;
            showNotification('Turntable generation failed: ' + data.error, 'error');
            document.getElementById('turntable-start').style.display = 'block';
            document.getElementById('turntable-progress').style.display = 'none';
            return;
        }
        
        // Continue polling every 3 seconds
        setTimeout(pollTurntableProgress, 3000);
        
    } catch (error) {
        console.error('Error polling progress:', error);
        setTimeout(pollTurntableProgress, 5000);
    }
}

function initTurntableViewer() {
    if (turntableImages.length === 0) return;
    
    // Hide progress, show viewer
    document.getElementById('turntable-progress').style.display = 'none';
    document.getElementById('turntable-viewer').style.display = 'block';
    document.getElementById('turntable-start').style.display = 'none';
    
    // Preload all images
    turntableImages.forEach(img => {
        const preload = new Image();
        preload.src = img.url;
    });
    
    // Set initial image
    currentTurntableIndex = 0;
    updateTurntableImage();
    
    // Build thumbnail strip
    buildThumbnailStrip();
    
    // Set up mouse/touch interaction
    setupTurntableInteraction();
    
    // Set up keyboard interaction
    setupKeyboardInteraction();
    
    // Voice announcement
    if (window.FUEsionVoice) {
        window.FUEsionVoice.announceStatus('Your 360 degree turntable view is ready! You can drag to rotate, use arrow keys, or say auto rotate. You can also share these results with the turntable images.');
    }
}

function navigateTurntable(direction) {
    if (turntableImages.length === 0) return;
    currentTurntableIndex = (currentTurntableIndex + direction + turntableImages.length) % turntableImages.length;
    updateTurntableImage();
}

function updateTurntableImage() {
    if (turntableImages.length === 0) return;
    
    const img = document.getElementById('turntable-image');
    const angleDisplay = document.getElementById('viewer-angle');
    const stepDisplay = document.getElementById('viewer-step');
    
    const currentImg = turntableImages[currentTurntableIndex];
    img.src = currentImg.url;
    angleDisplay.textContent = currentImg.angle + '°';
    
    // Update view name
    const viewNameDisplay = document.getElementById('viewer-view-name');
    if (viewNameDisplay) {
        viewNameDisplay.textContent = currentImg.name || currentImg.short || '';
    }
    if (stepDisplay) {
        stepDisplay.textContent = `(${currentTurntableIndex + 1} / ${turntableImages.length})`;
    }
    
    // Update active thumbnail
    document.querySelectorAll('.turntable-thumb').forEach((thumb, i) => {
        thumb.classList.toggle('active', i === currentTurntableIndex);
    });
    
    // Scroll active thumbnail into view
    const activeThumb = document.querySelector('.turntable-thumb.active');
    if (activeThumb) {
        activeThumb.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
}

function buildThumbnailStrip() {
    const container = document.getElementById('turntable-thumbnails');
    container.innerHTML = '';
    
    turntableImages.forEach((img, index) => {
        const thumb = document.createElement('div');
        thumb.className = 'turntable-thumb' + (index === 0 ? ' active' : '');
        const thumbLabel = img.short || img.name || (img.angle + '°');
        thumb.innerHTML = `
            <img src="${img.url}" alt="${thumbLabel}" draggable="false">
            <span class="thumb-angle">${thumbLabel}</span>
        `;
        thumb.onclick = () => {
            currentTurntableIndex = index;
            updateTurntableImage();
        };
        container.appendChild(thumb);
    });
}

function setupTurntableInteraction() {
    const container = document.getElementById('viewer-container');
    const overlay = document.getElementById('viewer-overlay');
    
    // Mouse events
    container.addEventListener('mousedown', (e) => {
        isDragging = true;
        dragStartX = e.clientX;
        dragStartIndex = currentTurntableIndex;
        overlay.style.opacity = '0';
        container.style.cursor = 'grabbing';
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        
        const deltaX = e.clientX - dragStartX;
        const sensitivity = 40; // pixels per frame change (wider for 8 images)
        const indexDelta = Math.round(deltaX / sensitivity);
        
        let newIndex = (dragStartIndex + indexDelta) % turntableImages.length;
        if (newIndex < 0) newIndex += turntableImages.length;
        
        if (newIndex !== currentTurntableIndex) {
            currentTurntableIndex = newIndex;
            updateTurntableImage();
        }
    });
    
    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            container.style.cursor = 'grab';
        }
    });
    
    // Touch events
    container.addEventListener('touchstart', (e) => {
        isDragging = true;
        dragStartX = e.touches[0].clientX;
        dragStartIndex = currentTurntableIndex;
        overlay.style.opacity = '0';
        e.preventDefault();
    }, { passive: false });
    
    container.addEventListener('touchmove', (e) => {
        if (!isDragging) return;
        
        const deltaX = e.touches[0].clientX - dragStartX;
        const sensitivity = 40;
        const indexDelta = Math.round(deltaX / sensitivity);
        
        let newIndex = (dragStartIndex + indexDelta) % turntableImages.length;
        if (newIndex < 0) newIndex += turntableImages.length;
        
        if (newIndex !== currentTurntableIndex) {
            currentTurntableIndex = newIndex;
            updateTurntableImage();
        }
        e.preventDefault();
    }, { passive: false });
    
    container.addEventListener('touchend', () => {
        isDragging = false;
    });
    
    // Mouse wheel
    container.addEventListener('wheel', (e) => {
        e.preventDefault();
        const direction = e.deltaY > 0 ? 1 : -1;
        currentTurntableIndex = (currentTurntableIndex + direction + turntableImages.length) % turntableImages.length;
        updateTurntableImage();
    }, { passive: false });
}

function setupKeyboardInteraction() {
    document.addEventListener('keydown', (e) => {
        if (turntableImages.length === 0) return;
        if (document.getElementById('turntable-viewer').style.display === 'none') return;
        
        if (e.key === 'ArrowLeft') {
            currentTurntableIndex = (currentTurntableIndex - 1 + turntableImages.length) % turntableImages.length;
            updateTurntableImage();
            e.preventDefault();
        } else if (e.key === 'ArrowRight') {
            currentTurntableIndex = (currentTurntableIndex + 1) % turntableImages.length;
            updateTurntableImage();
            e.preventDefault();
        }
    });
}

// ============================================
// Unified Share System (Before/After and/or Turntable)
// ============================================

function getGraftSummaryForShare() {
    if (currentSelections.length === 0) return null;
    let total = 0;
    const areas = currentSelections.map(item => {
        const grafts = graftCounts[item.area][item.density];
        total += grafts;
        return {
            area: areaNames[item.area],
            density: densityInfo[item.density].name,
            fuPerCm2: densityInfo[item.density].fu,
            grafts: grafts
        };
    });
    return { areas: areas, total: total };
}

// Share before/after only (from download section)
async function shareBeforeAfter() {
    if (!beforeImageUrl || !afterImageUrl) {
        showNotification('No results to share yet', 'warning');
        return;
    }
    await createAndShowShare(false);
}

// Share with turntable (from turntable viewer)
async function shareWithTurntable() {
    if (!beforeImageUrl || !afterImageUrl) {
        showNotification('No results to share yet', 'warning');
        return;
    }
    if (!turntableSessionId) {
        showNotification('No turntable result to share. Generate the 360\u00b0 turntable first.', 'warning');
        return;
    }
    await createAndShowShare(true);
}

async function createAndShowShare(includeTurntable) {
    // Show loading in the share modal
    showShareModal(null, includeTurntable ? 'full_360' : 'before_after', true);
    
    try {
        const payload = {
            beforeImage: beforeImageUrl,
            afterImage: afterImageUrl,
            graftSummary: getGraftSummaryForShare()
        };
        
        if (includeTurntable && turntableSessionId) {
            payload.turntableSessionId = turntableSessionId;
        }
        
        const response = await fetch('/api/create-share', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Update modal with the share URL + shareId so users can revoke instantly
            showShareModal(data.shareUrl, data.shareType, false, data.shareId);
        } else {
            closeShareModal();
            showNotification('Failed to create share link: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        closeShareModal();
        showNotification('Error creating share link: ' + error.message, 'error');
    }
}

function showShareModal(shareUrl, shareType, isLoading, shareId) {
    // Remove existing modal if any
    const existing = document.getElementById('share-modal-overlay');
    if (existing) existing.remove();
    
    const typeLabel = shareType === 'full_360' 
        ? 'before/after comparison and interactive 360\u00b0 turntable view' 
        : 'before/after comparison';
    
    const overlay = document.createElement('div');
    overlay.id = 'share-modal-overlay';
    overlay.className = 'share-modal-overlay';
    
    if (isLoading) {
        overlay.innerHTML = `
            <div class="share-modal">
                <div class="share-modal-header">
                    <h3>Creating Share Link...</h3>
                    <button class="share-modal-close" onclick="closeShareModal()">&times;</button>
                </div>
                <div style="text-align:center; padding: 32px 20px;">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--accent-color)" stroke-width="2" class="spin-icon">
                        <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
                    </svg>
                    <p style="margin-top:16px; color: var(--text-muted);">Generating your shareable link...</p>
                </div>
            </div>
        `;
    } else {
        overlay.innerHTML = `
            <div class="share-modal">
                <div class="share-modal-header">
                    <h3>Share Your Results</h3>
                    <button class="share-modal-close" onclick="closeShareModal()">&times;</button>
                </div>
                <div class="share-type-badge share-type-${shareType}">
                    ${shareType === 'full_360' ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg> Before/After + 360\u00b0 Turntable' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="12" y1="3" x2="12" y2="21"/></svg> Before/After Comparison'}
                </div>
                <p class="share-modal-desc">Share your ${typeLabel} with anyone using this link:</p>
                <div class="share-url-container">
                    <input type="text" id="share-url-input" value="${shareUrl}" readonly>
                    <button class="btn btn-primary btn-small" onclick="copyShareUrl()" id="copy-share-btn">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                        Copy
                    </button>
                </div>
                <div class="share-social-buttons">
                    <button class="share-social-btn share-whatsapp" onclick="shareVia('whatsapp', '${shareUrl}')" title="Share via WhatsApp">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
                        WhatsApp
                    </button>
                    <button class="share-social-btn share-email" onclick="shareVia('email', '${shareUrl}')" title="Share via Email">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                        Email
                    </button>
                    <button class="share-social-btn share-x" onclick="shareVia('x', '${shareUrl}')" title="Share on X">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                        X
                    </button>
                </div>
                <p class="share-modal-note">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;">
                        <circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>
                    </svg>
                    This link is <strong>public</strong> — anyone with the URL can view the results without logging in. You can revoke access at any time below or from the <em>My Shares</em> panel.
                </p>
                ${shareId ? `
                <div class="share-modal-revoke" style="margin-top:14px;display:flex;justify-content:flex-end;">
                    <button class="btn btn-small btn-delete-share" onclick="revokeShareFromModal('${shareId}')" id="revoke-share-btn" title="Revoke this public link immediately">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;vertical-align:middle;">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                        Revoke this link
                    </button>
                </div>` : ''}
            </div>
        `;
    }
    
    // Close on overlay click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeShareModal();
    });
    
    document.body.appendChild(overlay);
    
    // Animate in
    requestAnimationFrame(() => overlay.classList.add('active'));
}

function closeShareModal() {
    const overlay = document.getElementById('share-modal-overlay');
    if (overlay) {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 300);
    }
}

function copyShareUrl() {
    const input = document.getElementById('share-url-input');
    input.select();
    input.setSelectionRange(0, 99999);
    
    navigator.clipboard.writeText(input.value).then(() => {
        const btn = document.getElementById('copy-share-btn');
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
            </svg>
            Copied!
        `;
        btn.classList.add('copied');
        setTimeout(() => {
            btn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                Copy
            `;
            btn.classList.remove('copied');
        }, 2000);
    }).catch(() => {
        document.execCommand('copy');
        showNotification('Link copied to clipboard!', 'info');
    });
}

function shareVia(platform, url) {
    const text = 'Check out my AI hair restoration preview from FUEsion AI Hair Studio!';
    let shareLink = '';
    
    switch (platform) {
        case 'whatsapp':
            shareLink = `https://wa.me/?text=${encodeURIComponent(text + ' ' + url)}`;
            break;
        case 'email':
            shareLink = `mailto:?subject=${encodeURIComponent('My FUEsion AI Hair Studio Results')}&body=${encodeURIComponent(text + '\n\n' + url)}`;
            break;
        case 'x':
            shareLink = `https://x.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;
            break;
    }
    
    if (shareLink) {
        window.open(shareLink, '_blank', 'noopener,noreferrer');
    }
}

function toggleAutoRotate() {
    const btn = document.getElementById('auto-rotate-btn');
    
    if (isAutoRotating) {
        clearInterval(autoRotateInterval);
        autoRotateInterval = null;
        isAutoRotating = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            Auto Rotate
        `;
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-outline');
    } else {
        isAutoRotating = true;
        autoRotateInterval = setInterval(() => {
            currentTurntableIndex = (currentTurntableIndex + 1) % turntableImages.length;
            updateTurntableImage();
        }, 800);
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="6" y="4" width="4" height="16"/>
                <rect x="14" y="4" width="4" height="16"/>
            </svg>
            Stop Rotation
        `;
        btn.classList.remove('btn-outline');
        btn.classList.add('btn-primary');
    }
}


// ============================================
// Manage Shared Links Panel
// ============================================

function openManageShares() {
    const overlay = document.getElementById('manage-shares-overlay');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    loadSharedLinks();
}

function closeManageShares() {
    const overlay = document.getElementById('manage-shares-overlay');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
}

async function loadSharedLinks() {
    const loading = document.getElementById('manage-shares-loading');
    const empty = document.getElementById('manage-shares-empty');
    const list = document.getElementById('manage-shares-list');
    
    loading.style.display = 'flex';
    empty.style.display = 'none';
    list.innerHTML = '';
    
    try {
        const response = await fetch('/api/list-shares');
        const data = await response.json();
        
        loading.style.display = 'none';
        
        if (data.success && data.shares && data.shares.length > 0) {
            empty.style.display = 'none';
            renderShareCards(data.shares);
        } else {
            empty.style.display = 'flex';
        }
    } catch (error) {
        loading.style.display = 'none';
        list.innerHTML = `
            <div class="manage-shares-error">
                <p>Failed to load shared links. Please try again.</p>
                <button onclick="loadSharedLinks()" class="btn btn-small btn-outline">Retry</button>
            </div>
        `;
    }
}

function renderShareCards(shares) {
    const list = document.getElementById('manage-shares-list');
    list.innerHTML = '';
    
    shares.forEach(share => {
        const card = document.createElement('div');
        card.className = 'share-card';
        card.id = `share-card-${share.shareId}`;
        
        // Format date
        let dateStr = 'Unknown date';
        if (share.createdAt) {
            try {
                const date = new Date(share.createdAt);
                dateStr = date.toLocaleDateString('en-US', { 
                    year: 'numeric', month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit'
                });
            } catch(e) {
                dateStr = share.createdAt;
            }
        }
        
        // Graft total
        let graftTotal = '';
        if (share.graftSummary && share.graftSummary.total) {
            graftTotal = `<span class="share-card-grafts">${share.graftSummary.total.toLocaleString()} Grafts</span>`;
        }
        
        // Share type badge
        const isFullShare = share.shareType === 'full_360';
        const typeBadge = isFullShare 
            ? '<span class="share-card-type share-card-type-360"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg> Before/After + 360\u00b0</span>'
            : '<span class="share-card-type share-card-type-ba"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="12" y1="3" x2="12" y2="21"/></svg> Before/After</span>';
        
        // Image count
        const imageCount = isFullShare ? (share.turntableCount + 2) : 2;
        
        card.innerHTML = `
            <div class="share-card-preview">
                <div class="share-card-images">
                    ${share.beforeImage ? `<img src="${share.beforeImage}" alt="Before" class="share-card-thumb" onerror="this.style.display='none'">` : ''}
                    <div class="share-card-arrow">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <line x1="5" y1="12" x2="19" y2="12"/>
                            <polyline points="12 5 19 12 12 19"/>
                        </svg>
                    </div>
                    ${share.afterImage ? `<img src="${share.afterImage}" alt="After" class="share-card-thumb" onerror="this.style.display='none'">` : ''}
                    ${share.thumbnail ? `<img src="${share.thumbnail}" alt="360\u00b0" class="share-card-thumb share-card-thumb-turntable" onerror="this.style.display='none'">` : ''}
                </div>
            </div>
            <div class="share-card-info">
                <div class="share-card-meta">
                    ${typeBadge}
                    <span class="share-card-date">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <polyline points="12 6 12 12 16 14"/>
                        </svg>
                        ${dateStr}
                    </span>
                    <span class="share-card-count">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                            <circle cx="8.5" cy="8.5" r="1.5"/>
                            <polyline points="21 15 16 10 5 21"/>
                        </svg>
                        ${imageCount} images
                    </span>
                    ${graftTotal}
                </div>
                <div class="share-card-url-row">
                    <input type="text" value="${share.shareUrl}" readonly class="share-card-url" id="share-url-${share.shareId}">
                    <button onclick="copyCardShareUrl('${share.shareId}')" class="btn btn-small btn-copy-card" title="Copy link">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                    </button>
                </div>
                <div class="share-card-actions">
                    <a href="${share.shareUrl}" target="_blank" class="btn btn-small btn-outline share-card-view-btn">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                            <polyline points="15 3 21 3 21 9"/>
                            <line x1="10" y1="14" x2="21" y2="3"/>
                        </svg>
                        View
                    </a>
                    <button onclick="confirmDeleteShare('${share.shareId}')" class="btn btn-small btn-delete-share">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                            <line x1="10" y1="11" x2="10" y2="17"/>
                            <line x1="14" y1="11" x2="14" y2="17"/>
                        </svg>
                        Delete
                    </button>
                </div>
            </div>
        `;
        
        list.appendChild(card);
    });
}

function copyCardShareUrl(shareId) {
    const input = document.getElementById(`share-url-${shareId}`);
    input.select();
    input.setSelectionRange(0, 99999);
    
    navigator.clipboard.writeText(input.value).then(() => {
        showNotification('Link copied to clipboard!', 'success');
    }).catch(() => {
        document.execCommand('copy');
        showNotification('Link copied to clipboard!', 'info');
    });
}

async function revokeShareFromModal(shareId) {
    const btn = document.getElementById('revoke-share-btn');
    if (!shareId) return;
    if (!confirm('Revoke this public link now? Anyone who already has the URL will immediately lose access.')) return;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = 'Revoking...';
    }
    try {
        const response = await fetch(`/api/delete-share/${shareId}`, { method: 'DELETE' });
        const data = await response.json();
        if (response.ok && data.success !== false) {
            closeShareModal();
            showNotification('Share link revoked. It is no longer publicly accessible.', 'info');
        } else {
            showNotification('Failed to revoke link: ' + (data.error || 'Unknown error'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = 'Revoke this link'; }
        }
    } catch (e) {
        showNotification('Error revoking link: ' + e.message, 'error');
        if (btn) { btn.disabled = false; btn.innerHTML = 'Revoke this link'; }
    }
}

function confirmDeleteShare(shareId) {
    // Create a confirmation dialog
    const existing = document.getElementById('delete-confirm-overlay');
    if (existing) existing.remove();
    
    const overlay = document.createElement('div');
    overlay.id = 'delete-confirm-overlay';
    overlay.className = 'delete-confirm-overlay';
    overlay.innerHTML = `
        <div class="delete-confirm-dialog">
            <div class="delete-confirm-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="1.5">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="15" y1="9" x2="9" y2="15"/>
                    <line x1="9" y1="9" x2="15" y2="15"/>
                </svg>
            </div>
            <h3>Delete Shared Link?</h3>
            <p>This will permanently remove the shared link. Anyone with the link will no longer be able to view the results.</p>
            <div class="delete-confirm-actions">
                <button onclick="closeDeleteConfirm()" class="btn btn-small btn-outline">Cancel</button>
                <button onclick="executeDeleteShare('${shareId}')" class="btn btn-small btn-delete-confirm" id="delete-confirm-btn">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    Delete Permanently
                </button>
            </div>
        </div>
    `;
    
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeDeleteConfirm();
    });
    
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('active'));
}

function closeDeleteConfirm() {
    const overlay = document.getElementById('delete-confirm-overlay');
    if (overlay) {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 300);
    }
}

async function executeDeleteShare(shareId) {
    const btn = document.getElementById('delete-confirm-btn');
    btn.disabled = true;
    btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin-icon">
            <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        Deleting...
    `;
    
    try {
        const response = await fetch(`/api/delete-share/${shareId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        
        closeDeleteConfirm();
        
        if (data.success) {
            // Animate the card removal
            const card = document.getElementById(`share-card-${shareId}`);
            if (card) {
                card.style.transition = 'all 0.4s ease';
                card.style.opacity = '0';
                card.style.transform = 'translateX(30px) scale(0.95)';
                card.style.maxHeight = card.offsetHeight + 'px';
                setTimeout(() => {
                    card.style.maxHeight = '0';
                    card.style.padding = '0';
                    card.style.margin = '0';
                    card.style.border = 'none';
                }, 300);
                setTimeout(() => {
                    card.remove();
                    // Check if list is now empty
                    const list = document.getElementById('manage-shares-list');
                    if (list.children.length === 0) {
                        document.getElementById('manage-shares-empty').style.display = 'flex';
                    }
                }, 700);
            }
            
            showNotification('Shared link deleted successfully', 'success');
        } else {
            showNotification('Failed to delete: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        closeDeleteConfirm();
        showNotification('Error deleting share: ' + error.message, 'error');
    }
}

// Close manage shares panel on overlay click
document.addEventListener('DOMContentLoaded', function() {
    const overlay = document.getElementById('manage-shares-overlay');
    if (overlay) {
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeManageShares();
        });
    }
});


// ============================================
// Demo Links Management
// ============================================

function openDemoLinks() {
    const overlay = document.getElementById('demo-links-overlay');
    if (overlay) {
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        loadDemoLinks();
    }
}

function closeDemoLinks() {
    const overlay = document.getElementById('demo-links-overlay');
    if (overlay) {
        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }
}

async function loadDemoLinks() {
    const loading = document.getElementById('demo-links-loading');
    const empty = document.getElementById('demo-links-empty');
    const list = document.getElementById('demo-links-list');
    const leadsPanel = document.getElementById('demo-leads-panel');
    const linksBody = document.getElementById('demo-links-body');

    // Show links body, hide leads panel
    if (linksBody) linksBody.style.display = 'block';
    if (leadsPanel) leadsPanel.style.display = 'none';

    if (loading) loading.style.display = 'block';
    if (empty) empty.style.display = 'none';
    if (list) list.innerHTML = '';

    try {
        const resp = await fetch('/demo/api/list-links');
        const data = await resp.json();

        if (loading) loading.style.display = 'none';

        if (!data.success || !data.links || data.links.length === 0) {
            if (empty) empty.style.display = 'block';
            return;
        }

        data.links.forEach(link => {
            const card = document.createElement('div');
            card.style.cssText = 'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:16px 18px;';
            card.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">
                    <div style="flex:1;min-width:200px;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                            <span style="font-size:14px;font-weight:600;color:#e2e8f0;">${escapeHtml(link.label)}</span>
                            <span style="font-size:11px;padding:2px 8px;border-radius:8px;font-weight:600;${link.active ? 'background:rgba(16,185,129,0.12);color:#34d399;border:1px solid rgba(16,185,129,0.3);' : 'background:rgba(239,68,68,0.12);color:#f87171;border:1px solid rgba(239,68,68,0.3);'}">${link.active ? 'Active' : 'Inactive'}</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
                            <input type="text" value="${escapeHtml(link.url)}" readonly style="flex:1;padding:6px 10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:#94a3b8;font-size:12px;font-family:inherit;outline:none;" id="demo-url-${link.slug}">
                            <button onclick="copyDemoUrl('${link.slug}', this)" style="padding:6px 12px;background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.3);border-radius:8px;color:#c4b5fd;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;font-family:inherit;">Copy</button>
                            <button onclick="copyEmbedCode('${escapeHtml(link.url)}', this)" style="padding:6px 12px;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;color:#93c5fd;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;font-family:inherit;">Embed</button>
                        </div>
                        <div style="display:flex;gap:16px;font-size:12px;color:#64748b;">
                            <span><strong style="color:#94a3b8;">${link.leadCount}</strong> leads</span>
                            <span><strong style="color:#94a3b8;">${link.usedCount}</strong> used</span>
                            <span>Created ${new Date(link.createdAt).toLocaleDateString()}</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px;margin-top:4px;">
                            ${link.crmConnected ? '<span style="font-size:11px;color:#34d399;background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.25);border-radius:6px;padding:2px 8px;">&#10003; CRM Connected</span>' : '<span style="font-size:11px;color:#64748b;">No CRM</span>'}
                            <button onclick="setCrmKey('${link.slug}', ${link.id})" style="padding:2px 8px;background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.25);border-radius:6px;color:#c4b5fd;font-size:11px;cursor:pointer;font-family:inherit;">Set CRM Key</button>
                        </div>
                    </div>
                    <div style="display:flex;gap:6px;flex-shrink:0;">
                        <button onclick="viewDemoLeads('${link.slug}', '${escapeHtml(link.label)}')" style="padding:6px 12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:#94a3b8;font-size:11px;cursor:pointer;font-family:inherit;" title="View Leads">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                        </button>
                        <button onclick="toggleDemoLink('${link.slug}')" style="padding:6px 12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:#94a3b8;font-size:11px;cursor:pointer;font-family:inherit;" title="${link.active ? 'Deactivate' : 'Activate'}">
                            ${link.active ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>'}
                        </button>
                        <button onclick="deleteDemoLink('${link.slug}')" style="padding:6px 12px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:8px;color:#f87171;font-size:11px;cursor:pointer;font-family:inherit;" title="Delete">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </div>
                </div>
            `;
            list.appendChild(card);
        });

    } catch (err) {
        if (loading) loading.style.display = 'none';
        showNotification('Failed to load demo links: ' + err.message, 'error');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function copyDemoUrl(slug, btn) {
    const input = document.getElementById('demo-url-' + slug);
    if (!input) return;
    flashButton(btn, 'Copied!', '#34d399');
    navigator.clipboard.writeText(input.value).catch(() => {
        input.select();
        document.execCommand('copy');
    });
}

function flashButton(btn, text, color) {
    if (!btn) return;
    const origText = btn.textContent;
    const origColor = btn.style.color;
    const origBg = btn.style.background;
    const origBorder = btn.style.borderColor;
    btn.textContent = text;
    btn.style.color = color;
    btn.style.background = color === '#34d399' ? 'rgba(16,185,129,0.15)' : 'rgba(59,130,246,0.15)';
    btn.style.borderColor = color === '#34d399' ? 'rgba(16,185,129,0.4)' : 'rgba(59,130,246,0.4)';
    setTimeout(() => {
        btn.textContent = origText;
        btn.style.color = origColor;
        btn.style.background = origBg;
        btn.style.borderColor = origBorder;
    }, 2000);
}

async function createDemoLink() {
    const labelInput = document.getElementById('demo-link-label');
    const btn = document.getElementById('create-demo-link-btn');
    const label = (labelInput.value || '').trim() || 'Demo Link';

    btn.disabled = true;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin-icon"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Creating...';

    try {
        const resp = await fetch('/demo/api/create-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: label })
        });
        const data = await resp.json();

        if (data.success) {
            labelInput.value = '';
            showNotification('Demo link created! URL: ' + data.url, 'success');
            loadDemoLinks();
        } else {
            showNotification('Failed to create link: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (err) {
        showNotification('Error creating demo link: ' + err.message, 'error');
    }

    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Link';
}

async function toggleDemoLink(slug) {
    try {
        const resp = await fetch('/demo/api/toggle-link/' + slug, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showNotification('Link ' + (data.active ? 'activated' : 'deactivated'), 'success');
            loadDemoLinks();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (err) {
        showNotification('Error: ' + err.message, 'error');
    }
}

async function deleteDemoLink(slug) {
    if (!confirm('Delete this demo link and all its leads? This cannot be undone.')) return;

    try {
        const resp = await fetch('/demo/api/delete-link/' + slug, { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) {
            showNotification('Demo link deleted', 'success');
            loadDemoLinks();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (err) {
        showNotification('Error: ' + err.message, 'error');
    }
}

async function viewDemoLeads(slug, label) {
    const linksBody = document.getElementById('demo-links-body');
    const leadsPanel = document.getElementById('demo-leads-panel');
    const leadsTitle = document.getElementById('demo-leads-title');
    const leadsList = document.getElementById('demo-leads-list');
    const leadsEmpty = document.getElementById('demo-leads-empty');

    if (linksBody) linksBody.style.display = 'none';
    if (leadsPanel) leadsPanel.style.display = 'block';
    if (leadsTitle) leadsTitle.textContent = 'Leads — ' + label;
    if (leadsList) leadsList.innerHTML = '<div style="text-align:center;padding:20px;"><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="var(--accent-color)" stroke-width="2" class="spin-icon"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg></div>';
    if (leadsEmpty) leadsEmpty.style.display = 'none';

    try {
        const resp = await fetch('/demo/api/link-leads/' + slug);
        const data = await resp.json();

        if (!data.success || !data.leads || data.leads.length === 0) {
            leadsList.innerHTML = '';
            if (leadsEmpty) leadsEmpty.style.display = 'block';
            return;
        }

        leadsList.innerHTML = '';
        data.leads.forEach(lead => {
            const card = document.createElement('div');
            card.style.cssText = 'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px 16px;';

            const emailBadge = lead.email_verified
                ? '<span style="font-size:10px;padding:1px 6px;border-radius:6px;background:rgba(16,185,129,0.12);color:#34d399;border:1px solid rgba(16,185,129,0.3);">Email ✓</span>'
                : '<span style="font-size:10px;padding:1px 6px;border-radius:6px;background:rgba(251,191,36,0.1);color:#fbbf24;border:1px solid rgba(251,191,36,0.3);">Email ✗</span>';
            const phoneBadge = lead.phone_verified
                ? '<span style="font-size:10px;padding:1px 6px;border-radius:6px;background:rgba(16,185,129,0.12);color:#34d399;border:1px solid rgba(16,185,129,0.3);">Phone ✓</span>'
                : '<span style="font-size:10px;padding:1px 6px;border-radius:6px;background:rgba(251,191,36,0.1);color:#fbbf24;border:1px solid rgba(251,191,36,0.3);">Phone ✗</span>';
            const usedBadge = lead.generation_used
                ? '<span style="font-size:10px;padding:1px 6px;border-radius:6px;background:rgba(168,85,247,0.12);color:#c4b5fd;border:1px solid rgba(168,85,247,0.3);">Used</span>'
                : '<span style="font-size:10px;padding:1px 6px;border-radius:6px;background:rgba(255,255,255,0.06);color:#64748b;border:1px solid rgba(255,255,255,0.1);">Unused</span>';

            let shareLink = '';
            if (lead.share_id) {
                shareLink = `<a href="/shared/${lead.share_id}" target="_blank" style="font-size:11px;color:#a78bfa;text-decoration:none;">View Result →</a>`;
            }

            card.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;">
                    <div>
                        <div style="font-size:14px;font-weight:600;color:#e2e8f0;margin-bottom:4px;">${escapeHtml(lead.full_name)}</div>
                        <div style="font-size:12px;color:#94a3b8;margin-bottom:4px;">${escapeHtml(lead.email)} · ${escapeHtml(lead.phone)}</div>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
                            ${emailBadge} ${phoneBadge} ${usedBadge} ${shareLink}
                        </div>
                    </div>
                    <div style="font-size:11px;color:#64748b;white-space:nowrap;">${new Date(lead.created_at).toLocaleDateString()}</div>
                </div>
            `;
            leadsList.appendChild(card);
        });

    } catch (err) {
        leadsList.innerHTML = '<div style="text-align:center;padding:20px;color:#f87171;">Failed to load leads</div>';
    }
}

function backToDemoLinks() {
    const linksBody = document.getElementById('demo-links-body');
    const leadsPanel = document.getElementById('demo-leads-panel');
    if (linksBody) linksBody.style.display = 'block';
    if (leadsPanel) leadsPanel.style.display = 'none';
}

function copyEmbedCode(url, btn) {
    const embedCode = `<iframe src="${url}" width="100%" height="800" frameborder="0" allow="camera" style="border:none;border-radius:12px;max-width:600px;margin:0 auto;display:block;"></iframe>`;
    flashButton(btn, 'Copied!', '#34d399');
    navigator.clipboard.writeText(embedCode).catch(() => {
        prompt('Copy this embed code:', embedCode);
    });
}

// Close demo links panel on overlay click
document.addEventListener('DOMContentLoaded', function() {
    const overlay = document.getElementById('demo-links-overlay');
    if (overlay) {
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeDemoLinks();
        });
    }
});
