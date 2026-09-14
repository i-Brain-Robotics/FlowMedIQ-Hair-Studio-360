// ============================================
// FUEsion AI Hair Studio - Voice Command System
// Command-prefix model: "Okay FUEsion, [command]"
// No continuous listening — eliminates feedback loops
// ============================================

(function() {
    'use strict';

    // ---- State ----
    let recognition = null;
    var isListening = false;
    var isProcessing = false;
    var isSpeaking = false;
    var voiceEnabled = true;
    let currentUtterance = null;
    let currentAudio = null;
    let ttsAbortController = null;
    let hotwordRecognition = null;
    var hotwordActive = false;
    let micButton = null;
    let voicePanel = null;
    let voiceStatusEl = null;
    let voiceTranscriptEl = null;
    let voiceResponseEl = null;
    let selectedLanguage = 'en-US';
    let detectedResponseLang = 'en';

    // Camera state
    let cameraStream = null;
    let cameraOverlay = null;
    let capturedImageData = null;
    let capturedRotation = 0; // rotation applied to the captured photo, in degrees (0/90/180/270)
    let liveRotation = 0; // rotation applied to the LIVE camera feed, in degrees (0/90/180/270)

    // Supported languages for speech recognition
    const LANGUAGES = [
        { code: 'en-US', name: 'English', flag: '\u{1F1FA}\u{1F1F8}', ttsLang: 'en' },
        { code: 'es-ES', name: 'Espa\u00f1ol', flag: '\u{1F1EA}\u{1F1F8}', ttsLang: 'es' },
        { code: 'fr-FR', name: 'Fran\u00e7ais', flag: '\u{1F1EB}\u{1F1F7}', ttsLang: 'fr' },
        { code: 'de-DE', name: 'Deutsch', flag: '\u{1F1E9}\u{1F1EA}', ttsLang: 'de' },
        { code: 'it-IT', name: 'Italiano', flag: '\u{1F1EE}\u{1F1F9}', ttsLang: 'it' },
        { code: 'pt-BR', name: 'Portugu\u00eas', flag: '\u{1F1E7}\u{1F1F7}', ttsLang: 'pt' },
        { code: 'hi-IN', name: '\u0939\u093f\u0928\u094d\u0926\u0940', flag: '\u{1F1EE}\u{1F1F3}', ttsLang: 'hi' },
        { code: 'ar-SA', name: '\u0627\u0644\u0639\u0631\u0628\u064a\u0629', flag: '\u{1F1F8}\u{1F1E6}', ttsLang: 'ar' },
        { code: 'zh-CN', name: '\u4e2d\u6587', flag: '\u{1F1E8}\u{1F1F3}', ttsLang: 'zh' },
        { code: 'ja-JP', name: '\u65e5\u672c\u8a9e', flag: '\u{1F1EF}\u{1F1F5}', ttsLang: 'ja' },
        { code: 'ko-KR', name: '\ud55c\uad6d\uc5b4', flag: '\u{1F1F0}\u{1F1F7}', ttsLang: 'ko' },
        { code: 'tr-TR', name: 'T\u00fcrk\u00e7e', flag: '\u{1F1F9}\u{1F1F7}', ttsLang: 'tr' },
        { code: 'ru-RU', name: '\u0420\u0443\u0441\u0441\u043a\u0438\u0439', flag: '\u{1F1F7}\u{1F1FA}', ttsLang: 'ru' },
        { code: 'nl-NL', name: 'Nederlands', flag: '\u{1F1F3}\u{1F1F1}', ttsLang: 'nl' },
        { code: 'pl-PL', name: 'Polski', flag: '\u{1F1F5}\u{1F1F1}', ttsLang: 'pl' },
        { code: 'sv-SE', name: 'Svenska', flag: '\u{1F1F8}\u{1F1EA}', ttsLang: 'sv' },
        { code: 'th-TH', name: '\u0e44\u0e17\u0e22', flag: '\u{1F1F9}\u{1F1ED}', ttsLang: 'th' },
        { code: 'vi-VN', name: 'Ti\u1ebfng Vi\u1ec7t', flag: '\u{1F1FB}\u{1F1F3}', ttsLang: 'vi' },
        { code: 'id-ID', name: 'Bahasa Indonesia', flag: '\u{1F1EE}\u{1F1E9}', ttsLang: 'id' },
        { code: 'ms-MY', name: 'Bahasa Melayu', flag: '\u{1F1F2}\u{1F1FE}', ttsLang: 'ms' },
        { code: 'fil-PH', name: 'Filipino', flag: '\u{1F1F5}\u{1F1ED}', ttsLang: 'fil' },
        { code: 'uk-UA', name: '\u0423\u043a\u0440\u0430\u0457\u043d\u0441\u044c\u043a\u0430', flag: '\u{1F1FA}\u{1F1E6}', ttsLang: 'uk' },
        { code: 'he-IL', name: '\u05e2\u05d1\u05e8\u05d9\u05ea', flag: '\u{1F1EE}\u{1F1F1}', ttsLang: 'he' },
        { code: 'bn-IN', name: '\u09ac\u09be\u0982\u09b2\u09be', flag: '\u{1F1EE}\u{1F1F3}', ttsLang: 'bn' },
        { code: 'ta-IN', name: '\u0ba4\u0bae\u0bbf\u0bb4\u0bcd', flag: '\u{1F1EE}\u{1F1F3}', ttsLang: 'ta' },
        { code: 'te-IN', name: '\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41', flag: '\u{1F1EE}\u{1F1F3}', ttsLang: 'te' },
        { code: 'ur-PK', name: '\u0627\u0631\u062f\u0648', flag: '\u{1F1F5}\u{1F1F0}', ttsLang: 'ur' }
    ];

    // ---- Hotword prefixes ----
    // These are stripped from the transcript to extract the command
    const HOTWORD_PREFIXES = [
        'okay fusion', 'okay fuesion', 'okay few sion', 'okay few shun',
        'ok fusion', 'ok fuesion', 'ok few sion',
        'hey fusion', 'hey fuesion', 'hey few sion', 'hey few shun',
        'a fusion', 'okay fusion ai', 'ok fusion ai', 'hey fusion ai',
        'okay fuse', 'ok fuse', 'hey fuse',
        'okay fugen', 'ok fugen', 'hey fugen',
        'okay few', 'ok few', 'hey few',
        'okay fuse ion', 'ok fuse ion', 'hey fuse ion',
        'okay fushan', 'ok fushan', 'hey fushan',
        'okay few john', 'ok few john', 'hey few john',
        'okay fuchsia', 'ok fuchsia', 'hey fuchsia',
        'okay fusion hair', 'ok fusion hair', 'hey fusion hair',
        'he fusion', 'hay fusion'
    ];

    // ---- Initialization ----
    function init() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            console.warn('Voice: Speech Recognition not supported in this browser.');
            return;
        }

        createVoiceUI();
        createCameraOverlay();
        setupSpeechRecognition();
        setupHotwordRecognition();
        console.log('[Voice] Initialized — say "Okay FUEsion" followed by a command');
        // Start hotword listener after a short delay
        setTimeout(function() {
            startHotwordListener();
        }, 2000);
    }

    // ---- Create the Voice UI (floating mic button + panel) ----
    function createVoiceUI() {
        micButton = document.createElement('button');
        micButton.id = 'voice-mic-btn';
        micButton.className = 'voice-mic-btn';
        micButton.title = 'Push to talk or say "Okay FUEsion"';
        micButton.innerHTML = `
            <svg class="mic-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
            </svg>
            <svg class="mic-icon-active" width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="display:none;">
                <rect x="9" y="1" width="6" height="15" rx="3" fill="currentColor"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" fill="none" stroke="currentColor" stroke-width="2"/>
                <line x1="12" y1="19" x2="12" y2="23" stroke="currentColor" stroke-width="2"/>
                <line x1="8" y1="23" x2="16" y2="23" stroke="currentColor" stroke-width="2"/>
            </svg>
            <div class="voice-pulse-ring"></div>
        `;
        micButton.addEventListener('click', toggleListening);
        document.body.appendChild(micButton);

        const langOptions = LANGUAGES.map(l =>
            `<option value="${l.code}" ${l.code === selectedLanguage ? 'selected' : ''}>${l.flag} ${l.name}</option>`
        ).join('');

        voicePanel = document.createElement('div');
        voicePanel.id = 'voice-panel';
        voicePanel.className = 'voice-panel';
        voicePanel.innerHTML = `
            <div class="voice-panel-header">
                <div class="voice-panel-title">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                    </svg>
                    Voice Assistant
                </div>
                <button class="voice-panel-close" onclick="window.FUEsionVoice.closePanel()" title="Close">&times;</button>
            </div>
            <div class="voice-panel-body">
                <div class="voice-lang-selector">
                    <label for="voice-lang-select">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="2" y1="12" x2="22" y2="12"/>
                            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
                        </svg>
                        Language:
                    </label>
                    <select id="voice-lang-select" onchange="window.FUEsionVoice.setLanguage(this.value)">
                        ${langOptions}
                    </select>
                </div>
                <div id="voice-status" class="voice-status">
                    <span class="voice-status-dot"></span>
                    <span class="voice-status-text">Say "Okay FUEsion" followed by a command</span>
                </div>
                <div id="voice-transcript" class="voice-transcript" style="display:none;">
                    <div class="voice-transcript-label">You said:</div>
                    <div class="voice-transcript-text"></div>
                </div>
                <div id="voice-response" class="voice-response" style="display:none;">
                    <div class="voice-response-label">Assistant:</div>
                    <div class="voice-response-text"></div>
                </div>
                <div id="voice-actions" class="voice-actions" style="display:none;"></div>
            </div>
            <div class="voice-panel-footer">
                <button class="voice-mute-btn" id="voice-mute-btn" onclick="window.FUEsionVoice.toggleMute()" title="Mute/unmute voice responses">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
                    </svg>
                    Voice On
                </button>
                <div class="voice-hint">Say: "Okay FUEsion, create a natural plan"</div>
            </div>
        `;
        document.body.appendChild(voicePanel);

        voiceStatusEl = voicePanel.querySelector('#voice-status');
        voiceTranscriptEl = voicePanel.querySelector('#voice-transcript');
        voiceResponseEl = voicePanel.querySelector('#voice-response');
    }

    // ---- Create Camera Overlay ----
    function createCameraOverlay() {
        cameraOverlay = document.createElement('div');
        cameraOverlay.id = 'camera-overlay';
        cameraOverlay.className = 'camera-overlay';
        cameraOverlay.style.display = 'none';
        cameraOverlay.innerHTML = `
            <div class="camera-container">
                <div class="camera-header">
                    <h3>
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
                            <circle cx="12" cy="13" r="4"/>
                        </svg>
                        Camera Capture
                    </h3>
                    <button class="camera-close-btn" onclick="window.FUEsionVoice.closeCamera()" title="Close Camera">&times;</button>
                </div>
                <div class="camera-body">
                    <div class="camera-viewfinder" id="camera-viewfinder">
                        <video id="camera-video" autoplay playsinline></video>
                        <canvas id="camera-canvas" style="display:none;"></canvas>
                        <img id="camera-preview" style="display:none;" alt="Captured photo"/>

                    </div>
                </div>
                <div class="camera-controls" id="camera-controls">
                    <div class="camera-controls-live" id="camera-controls-live">
                        <button class="camera-btn camera-btn-switch" id="camera-switch-btn" onclick="window.FUEsionVoice.switchCamera()" title="Switch Camera">
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="23 4 23 10 17 10"/>
                                <polyline points="1 20 1 14 7 14"/>
                                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                            </svg>
                        </button>
                        <button class="camera-btn camera-btn-capture" id="camera-capture-btn" onclick="window.FUEsionVoice.takeSnapshot()">
                            <div class="camera-btn-capture-inner"></div>
                        </button>
                        <button class="camera-btn camera-btn-rotate-live" id="camera-rotate-live-btn" onclick="window.FUEsionVoice.rotateLiveFeed()" title="Rotate camera view 90°">
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="23 4 23 10 17 10"/>
                                <path d="M20.49 9A9 9 0 1 0 22 12"/>
                            </svg>
                        </button>
                        <button class="camera-btn camera-btn-close" onclick="window.FUEsionVoice.closeCamera()" title="Cancel">
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"/>
                                <line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                        </button>
                    </div>
                    <div class="camera-controls-preview" id="camera-controls-preview" style="display:none;">
                        <button class="camera-btn-action camera-btn-retake" onclick="window.FUEsionVoice.retakePhoto()">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="23 4 23 10 17 10"/>
                                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                            </svg>
                            Retake
                        </button>
                        <button class="camera-btn-action camera-btn-rotate" onclick="window.FUEsionVoice.rotatePhoto()" title="Rotate photo 90° clockwise">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="23 4 23 10 17 10"/>
                                <path d="M20.49 9A9 9 0 1 0 22 12"/>
                            </svg>
                            Rotate
                        </button>
                        <button class="camera-btn-action camera-btn-use" onclick="window.FUEsionVoice.useCameraPhoto()">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="20 6 9 17 4 12"/>
                            </svg>
                            Use This Photo
                        </button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(cameraOverlay);
    }

    // ============================================
    // Speech Recognition Setup (for push-to-talk only)
    // ============================================
    function setupSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = selectedLanguage;
        recognition.maxAlternatives = 1;

        recognition.onstart = function() {
            // GUARD: If system is speaking, abort immediately
            if (isSpeaking) {
                console.log('[Voice] Recognition started while speaking \u2014 aborting');
                try { recognition.stop(); } catch(e) {}
                isListening = false;
                return;
            }
            isListening = true;
            updateMicState('listening');
            updateStatus('Listening...', 'listening');
            showPanel();
        };

        recognition.onresult = function(event) {
            // GUARD: Ignore results while speaking
            if (isSpeaking) {
                console.log('[Voice] Ignoring recognition result while speaking');
                try { recognition.stop(); } catch(e) {}
                return;
            }

            let interimTranscript = '';
            let finalTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const t = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += t;
                } else {
                    interimTranscript += t;
                }
            }

            if (interimTranscript) {
                showTranscript(interimTranscript, true);
            }

            if (finalTranscript) {
                showTranscript(finalTranscript, false);
                processVoiceCommand(finalTranscript.trim());
            }
        };

        recognition.onerror = function(event) {
            console.warn('[Voice] Recognition error:', event.error);
            isListening = false;

            if (event.error === 'no-speech') {
                updateStatus('No speech detected. Tap mic or say "Okay FUEsion".', 'idle');
                updateMicState('idle');
            } else if (event.error === 'not-allowed') {
                updateStatus('Microphone access denied. Please allow mic access.', 'error');
                updateMicState('idle');
            } else if (event.error === 'aborted') {
                console.log('[Voice] Recognition aborted (expected)');
            } else {
                updateStatus('Error: ' + event.error, 'idle');
                updateMicState('idle');
            }
            // After any error, restart hotword listener
            scheduleHotwordRestart();
        };

        recognition.onend = function() {
            isListening = false;
            if (!isProcessing && !isSpeaking) {
                updateMicState('idle');
                // Restart hotword listener
                scheduleHotwordRestart();
            }
        };
    }

    // ---- Language Selection ----
    function setLanguage(langCode) {
        selectedLanguage = langCode;
        if (recognition) recognition.lang = langCode;
        const lang = LANGUAGES.find(l => l.code === langCode);
        if (lang) {
            updateStatus(`Language set to ${lang.name}. Say "Okay FUEsion" to speak.`, 'idle');
        }
    }

    // ---- Toggle Listening (push-to-talk via mic button) ----
    function toggleListening() {
        if (isProcessing) return;

        if (isSpeaking) {
            // If speaking, stop speech first
            stopSpeaking();
            return;
        }

        if (isListening) {
            stopListening();
        } else {
            startListening();
        }
    }

    function startListening() {
        if (isSpeaking) return;
        stopSpeaking();
        stopHotwordListener();
        if (recognition) recognition.lang = selectedLanguage;
        try {
            recognition.start();
        } catch (e) {
            try { recognition.stop(); } catch(e2) {}
            setTimeout(function() {
                try { recognition.start(); } catch(e3) { console.error(e3); }
            }, 200);
        }
    }

    function stopListening() {
        try { recognition.stop(); } catch (e) {}
        isListening = false;
        updateMicState('idle');
    }

    // ---- Schedule hotword restart ----
    // Restarts the hotword listener after a delay, with guards
    function scheduleHotwordRestart() {
        setTimeout(function() {
            if (!isSpeaking && !isListening && !isProcessing && !hotwordActive) {
                startHotwordListener();
            }
        }, 500);
    }

    // ============================================
    // Process Voice Command
    // ============================================
    async function processVoiceCommand(transcript) {
        if (!transcript) return;

        isProcessing = true;
        updateMicState('processing');
        updateStatus('Processing your command...', 'processing');

        // Check for quick local commands first
        const localResult = handleLocalCommand(transcript);
        if (localResult) {
            isProcessing = false;
            if (isSpeaking) {
                updateMicState('speaking');
                updateStatus('Speaking...', 'speaking');
            } else {
                updateMicState('idle');
                updateStatus('Say "Okay FUEsion" for next command', 'idle');
                scheduleHotwordRestart();
            }
            return;
        }

        // Determine current app state
        const currentStep = getCurrentStep();
        const hasImage = !!window.uploadedFilename;
        const hasAfterImage = !!window.afterImageUrl;
        const hasTurntable = !!(window.turntableImages && window.turntableImages.length > 0);

        try {
            const response = await fetch('/api/voice-command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    transcript: transcript,
                    currentStep: currentStep,
                    hasImage: hasImage,
                    uploadedFilename: window.uploadedFilename || null,
                    currentSelections: window.currentSelections || [],
                    hasAfterImage: hasAfterImage,
                    hasTurntable: hasTurntable
                })
            });

            const data = await response.json();

            if (data.error) {
                showResponse('Sorry, there was an error: ' + data.error);
                speak('Sorry, there was an error processing your command.');
                isProcessing = false;
                updateMicState('idle');
                return;
            }

            if (data.detected_language) {
                detectedResponseLang = data.detected_language;
            }

            showResponse(data.speech || 'Command processed.');

            if (voiceEnabled && data.speech) {
                speak(data.speech, data.detected_language);
            }

            if (data.intent === 'smart_plan' && data.selections && data.selections.length > 0) {
                executeSmartPlan(data.selections, data.totalGrafts, data.speech);
            } else if (data.intent === 'navigate' && data.action) {
                executeNavigationCommand(data.action);
            } else if (data.intent === 'unknown') {
                updateStatus('Command not recognized. Try again.', 'idle');
            }

        } catch (error) {
            console.error('Voice command error:', error);
            showResponse('Sorry, I encountered an error. Please try again.');
            speak('Sorry, I encountered an error. Please try again.');
        }

        isProcessing = false;

        if (isSpeaking) {
            // Speech is playing \u2014 onSpeechFinished() will restart hotword when done
            updateStatus('Speaking...', 'speaking');
        } else {
            updateMicState('idle');
            updateStatus('Say "Okay FUEsion" for next command', 'idle');
            scheduleHotwordRestart();
        }
    }

    // ---- Handle Quick Local Commands ----
    function handleLocalCommand(transcript) {
        const t = transcript.toLowerCase().trim();

        const stopWords = ['stop', 'cancel', 'never mind', 'parar', 'cancelar', 'annuler', 'abbrechen', 'fermare', '\u0930\u0941\u0915\u094b', '\u0930\u0926\u094d\u0926', '\u0625\u0644\u063a\u0627\u0621', '\u062a\u0648\u0642\u0641', '\u505c\u6b62', '\u53d6\u6d88', '\u3084\u3081\u3066', '\uc911\uc9c0', 'dur', 'iptal', '\u0441\u0442\u043e\u043f', '\u043e\u0442\u043c\u0435\u043d\u0430'];
        if (stopWords.some(w => t === w || t.startsWith(w + ' '))) {
            stopSpeaking();
            updateStatus('Cancelled.', 'idle');
            speak('Cancelled.');
            return true;
        }

        const yesWords = ['yes', 'proceed', 'go ahead', 'do it', 'generate', 'yes please', 's\u00ed', 'oui', 'ja', 's\u00ec', '\u0939\u093e\u0901', '\u0646\u0639\u0645', '\u662f', '\u306f\u3044', '\ub124', 'evet', '\u0434\u0430', 'sim'];
        if (yesWords.some(w => t === w || t.startsWith(w)) && getCurrentStep() === 'options') {
            speak('Starting generation now.');
            executeNavigationCommand('generate_preview');
            return true;
        }

        return false;
    }

    // ---- Execute Smart Plan ----
    function executeSmartPlan(selections, totalGrafts, speechText) {
        const currentStep = getCurrentStep();
        if (currentStep === 'upload') {
            if (!window.uploadedFilename) {
                speak('Please upload a photo first before I can create a plan.');
                return;
            }
            if (typeof window.continueToOptions === 'function') {
                window.continueToOptions();
            }
        }

        setTimeout(() => {
            document.querySelectorAll('input[name="area"]').forEach(cb => { cb.checked = false; });
            document.querySelectorAll('input[type="radio"][value="moderate"]').forEach(radio => { radio.checked = true; });

            selections.forEach(sel => {
                const areaCheckbox = document.querySelector(`input[name="area"][value="${sel.area}"]`);
                if (areaCheckbox) {
                    areaCheckbox.checked = true;
                    const densityRadio = document.querySelector(`input[name="density-${sel.area}"][value="${sel.density}"]`);
                    if (densityRadio) densityRadio.checked = true;
                }
            });

            if (typeof window.updateGraftSummary === 'function') {
                window.updateGraftSummary();
            }

            showPlanActions(selections, totalGrafts);
        }, currentStep === 'upload' ? 500 : 100);
    }

    function showPlanActions(selections, totalGrafts) {
        const actionsEl = voicePanel.querySelector('#voice-actions');
        actionsEl.style.display = 'block';
        actionsEl.innerHTML = `
            <div class="voice-plan-summary">
                <strong>${selections.length} area${selections.length > 1 ? 's' : ''} selected</strong> \u2014 ${(totalGrafts || 0).toLocaleString()} total grafts
            </div>
            <div class="voice-action-buttons">
                <button class="voice-action-btn voice-action-proceed" onclick="window.FUEsionVoice.proceedWithGeneration()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                    Generate Preview
                </button>
                <button class="voice-action-btn voice-action-modify" onclick="window.FUEsionVoice.startListening()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                    </svg>
                    Modify (Speak Again)
                </button>
            </div>
        `;
    }

    // ---- Execute Navigation Commands ----
    function executeNavigationCommand(action) {
        const actionsEl = voicePanel.querySelector('#voice-actions');
        if (actionsEl) actionsEl.style.display = 'none';

        switch (action) {
            case 'upload_photo': document.getElementById('imageInput').click(); break;
            case 'open_camera': openCamera(); break;
            case 'take_snapshot': takeSnapshot(); break;
            case 'retake_photo': retakePhoto(); break;
            case 'rotate_photo':
                // If we're still on the live feed, rotate the feed; otherwise rotate the captured photo.
                if (document.getElementById('camera-controls-live') && document.getElementById('camera-controls-live').style.display !== 'none' && cameraStream) {
                    rotateLiveFeed();
                } else {
                    rotatePhoto();
                }
                break;
            case 'use_camera_photo': useCameraPhoto(); break;
            case 'continue_to_options':
                if (typeof window.continueToOptions === 'function') window.continueToOptions();
                break;
            case 'go_back':
                if (getCurrentStep() === 'options' && typeof window.backToUpload === 'function') window.backToUpload();
                else if (getCurrentStep() === 'results' && typeof window.startOver === 'function') window.startOver();
                break;
            case 'generate_preview':
                if (typeof window.generateHair === 'function') window.generateHair();
                break;
            case 'download_before':
                if (typeof window.downloadImage === 'function') window.downloadImage('before');
                break;
            case 'download_after':
                if (typeof window.downloadImage === 'function') window.downloadImage('after');
                break;
            case 'download_combined':
                if (typeof window.downloadCombinedImage === 'function') window.downloadCombinedImage();
                break;
            case 'download_pdf':
                if (typeof window.downloadPDF === 'function') window.downloadPDF();
                break;
            case 'share_results':
                if (typeof window.shareBeforeAfter === 'function') window.shareBeforeAfter();
                break;
            case 'share_with_turntable':
                if (typeof window.shareWithTurntable === 'function') window.shareWithTurntable();
                break;
            case 'generate_turntable':
                if (typeof window.startTurntableGeneration === 'function') window.startTurntableGeneration();
                break;
            case 'start_over':
                if (typeof window.startOver === 'function') window.startOver();
                break;
            case 'auto_rotate':
                if (typeof window.toggleAutoRotate === 'function') window.toggleAutoRotate();
                break;
            default:
                console.warn('[Voice] Unknown navigation action:', action);
        }
    }

    function proceedWithGeneration() {
        const actionsEl = voicePanel.querySelector('#voice-actions');
        if (actionsEl) actionsEl.style.display = 'none';
        speak('Starting generation now. This may take a moment.');
        if (typeof window.generateHair === 'function') window.generateHair();
    }

    // ============================================
    // Camera System
    // ============================================
    let currentFacingMode = 'user';

    // Match the viewfinder aspect ratio to the actual camera stream so the
    // live feed always fills the frame upright (no sideways crop / letterbox).
    function applyOrientation(video) {
        const viewfinder = document.getElementById('camera-viewfinder');
        if (!viewfinder || !video) return;
        const w = video.videoWidth;
        const h = video.videoHeight;
        if (!w || !h) return;
        if (w > h) {
            viewfinder.classList.add('is-landscape');
        } else {
            viewfinder.classList.remove('is-landscape');
        }
    }

    function adjustViewfinderOrientation(video) {
        if (!video) return;
        // videoWidth/Height may not be ready immediately after play()
        if (video.videoWidth && video.videoHeight) {
            applyOrientation(video);
            applyLiveRotation();
        } else {
            video.addEventListener('loadedmetadata', () => { applyOrientation(video); applyLiveRotation(); }, { once: true });
        }
    }

    // Visually rotate the LIVE video preview by liveRotation degrees so the
    // operator sees an upright feed even when the webcam delivers a rotated
    // frame. For 90/270 we scale the video so it still fills the frame after
    // the rotation swaps width/height.
    function applyLiveRotation() {
        const video = document.getElementById('camera-video');
        const viewfinder = document.getElementById('camera-viewfinder');
        if (!video || !viewfinder) return;
        const rot = ((liveRotation % 360) + 360) % 360;

        if (rot === 0) {
            video.style.transform = '';
            return;
        }

        const vw = viewfinder.clientWidth || 1;
        const vh = viewfinder.clientHeight || 1;
        let transform = `rotate(${rot}deg)`;
        if (rot === 90 || rot === 270) {
            // After a quarter turn the video's width maps to the frame height
            // and vice-versa; scale so it still covers the frame.
            const scale = Math.max(vw / vh, vh / vw);
            transform += ` scale(${scale})`;
        }
        video.style.transformOrigin = 'center center';
        video.style.transform = transform;
    }

    // Rotate the live camera feed 90 degrees clockwise (cycles 0/90/180/270).
    function rotateLiveFeed() {
        const video = document.getElementById('camera-video');
        if (!video || !video.srcObject) { speak('Please open the camera first.'); return; }
        liveRotation = (liveRotation + 90) % 360;
        applyLiveRotation();
        speak('Camera view rotated.');
    }

    async function openCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            speak('Camera is not supported in this browser. Please upload a photo instead.');
            showResponse('Camera not supported in this browser.');
            return;
        }

        cameraOverlay.style.display = 'flex';
        capturedImageData = null;
        document.getElementById('camera-controls-live').style.display = 'flex';
        document.getElementById('camera-controls-preview').style.display = 'none';

        const video = document.getElementById('camera-video');
        const preview = document.getElementById('camera-preview');
        video.style.display = 'block';
        preview.style.display = 'none';

        try {
            if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: currentFacingMode, width: { ideal: 1280 }, height: { ideal: 960 } },
                audio: false
            });
            video.srcObject = cameraStream;
            await video.play();
            adjustViewfinderOrientation(video);
            speak('Camera is ready. Position your face and say "Okay FUEsion, take photo" or tap the capture button.');
        } catch (err) {
            console.error('Camera error:', err);
            if (err.name === 'NotAllowedError') {
                speak('Camera access was denied. Please allow camera access in your browser settings.');
            } else if (err.name === 'NotFoundError') {
                speak('No camera found on this device. Please upload a photo instead.');
            } else {
                speak('Could not access the camera. Please try again or upload a photo instead.');
            }
            cameraOverlay.style.display = 'none';
        }
    }

    async function switchCamera() {
        currentFacingMode = currentFacingMode === 'user' ? 'environment' : 'user';
        if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
        const video = document.getElementById('camera-video');
        try {
            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: currentFacingMode, width: { ideal: 1280 }, height: { ideal: 960 } },
                audio: false
            });
            video.srcObject = cameraStream;
            await video.play();
            adjustViewfinderOrientation(video);
            speak('Camera switched.');
        } catch (err) {
            speak('Could not switch camera.');
            console.error('Switch camera error:', err);
        }
    }

    // Raw captured frame (un-rotated) kept so we can re-render at any rotation
    let capturedRawCanvas = null;

    // Render the raw captured frame into capturedImageData applying capturedRotation,
    // then update the on-screen preview. Rotation is normalized to 0/90/180/270.
    function renderCapturedPhoto() {
        if (!capturedRawCanvas) return;
        const preview = document.getElementById('camera-preview');
        const rot = ((capturedRotation % 360) + 360) % 360;
        const sw = capturedRawCanvas.width;
        const sh = capturedRawCanvas.height;

        const out = document.createElement('canvas');
        // For 90/270 the output dimensions are swapped
        if (rot === 90 || rot === 270) {
            out.width = sh;
            out.height = sw;
        } else {
            out.width = sw;
            out.height = sh;
        }

        const ctx = out.getContext('2d');
        ctx.save();
        ctx.translate(out.width / 2, out.height / 2);
        ctx.rotate(rot * Math.PI / 180);
        ctx.drawImage(capturedRawCanvas, -sw / 2, -sh / 2);
        ctx.restore();

        capturedImageData = out.toDataURL('image/jpeg', 0.92);
        if (preview) preview.src = capturedImageData;
    }

    function takeSnapshot() {
        const video = document.getElementById('camera-video');
        const canvas = document.getElementById('camera-canvas');
        const preview = document.getElementById('camera-preview');
        if (!video.srcObject) { speak('Please open the camera first.'); return; }

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

        // Preserve the raw frame so rotation can be applied/changed without quality loss
        capturedRawCanvas = document.createElement('canvas');
        capturedRawCanvas.width = canvas.width;
        capturedRawCanvas.height = canvas.height;
        capturedRawCanvas.getContext('2d').drawImage(canvas, 0, 0);

        // Inherit any live-feed rotation the operator applied so the captured
        // photo comes out upright by default. The post-capture Rotate button
        // can still adjust further.
        capturedRotation = liveRotation;
        renderCapturedPhoto();

        preview.style.display = 'block';
        video.style.display = 'none';
        document.getElementById('camera-controls-live').style.display = 'none';
        document.getElementById('camera-controls-preview').style.display = 'flex';

        const viewfinder = document.getElementById('camera-viewfinder');
        viewfinder.classList.add('camera-flash');
        setTimeout(() => viewfinder.classList.remove('camera-flash'), 300);

        speak('Photo captured! Say "Okay FUEsion, rotate" to fix the orientation, "Okay FUEsion, use this photo" to continue, or "Okay FUEsion, retake" to try again.');
    }

    // Rotate the captured preview 90 degrees clockwise (cycles 0 -> 90 -> 180 -> 270 -> 0)
    function rotatePhoto() {
        if (!capturedRawCanvas) { speak('Please take a photo first.'); return; }
        capturedRotation = (capturedRotation + 90) % 360;
        renderCapturedPhoto();
        speak('Rotated. Say "Okay FUEsion, rotate" again to keep turning, or "Okay FUEsion, use this photo" when it looks right.');
    }

    function retakePhoto() {
        capturedImageData = null;
        capturedRawCanvas = null;
        capturedRotation = 0;
        const video = document.getElementById('camera-video');
        const preview = document.getElementById('camera-preview');
        preview.style.display = 'none';
        video.style.display = 'block';
        document.getElementById('camera-controls-live').style.display = 'flex';
        document.getElementById('camera-controls-preview').style.display = 'none';
        speak('Ready to take another photo.');
    }

    async function useCameraPhoto() {
        if (!capturedImageData) { speak('No photo captured yet. Please take a photo first.'); return; }

        speak('Uploading your photo...');
        updateStatus('Uploading camera photo...', 'processing');

        try {
            const response = await fetch(capturedImageData);
            const blob = await response.blob();
            const file = new File([blob], 'camera-capture.jpg', { type: 'image/jpeg' });
            const formData = new FormData();
            formData.append('image', file);

            const uploadResponse = await fetch('/upload', { method: 'POST', body: formData });
            const data = await uploadResponse.json();

            if (data.success) {
                window.uploadedFilename = data.filename;
                window.beforeImageUrl = data.url;
                document.getElementById('uploadedImage').src = data.url;
                document.getElementById('imagePreview').style.display = 'block';
                closeCamera();
                speak('Photo uploaded successfully! Say "Okay FUEsion, create a plan" to continue.');
                updateStatus('Photo uploaded. Say "Okay FUEsion" for next command.', 'idle');
            } else {
                speak('Upload failed. Please try again.');
                showResponse('Upload failed: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Camera upload error:', error);
            speak('There was an error uploading the photo. Please try again.');
        }
    }

    function closeCamera() {
        if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
        capturedImageData = null;
        capturedRawCanvas = null;
        capturedRotation = 0;
        liveRotation = 0;
        if (cameraOverlay) cameraOverlay.style.display = 'none';
        const video = document.getElementById('camera-video');
        if (video) { video.srcObject = null; video.style.transform = ''; }
    }

    // ============================================
    // Text-to-Speech \u2014 OpenAI Streaming TTS
    // ============================================
    var speechCancelled = false;
    var speechId = 0;

    var audioContext = null;
    var analyserNode = null;
    var gainNode = null;
    var pcmBufferQueue = [];
    var isPlayingStream = false;
    var streamFinished = false;
    var currentSourceNode = null;
    var nextPlayTime = 0;
    var audioEndTime = 0;
    var speechEndPollTimer = null;
    var speechEndSafetyTimer = null;
    var silenceStartTime = 0;
    var speechFinishedCalled = false;

    function getAudioContext() {
        if (!audioContext || audioContext.state === 'closed') {
            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
            analyserNode = audioContext.createAnalyser();
            analyserNode.fftSize = 2048;
            analyserNode.smoothingTimeConstant = 0.3;
            gainNode = audioContext.createGain();
            gainNode.gain.value = 1.0;
            gainNode.connect(analyserNode);
            analyserNode.connect(audioContext.destination);
        }
        if (audioContext.state === 'suspended') audioContext.resume();
        return audioContext;
    }

    function getAudioRMS() {
        if (!analyserNode) return 0;
        var dataArray = new Float32Array(analyserNode.fftSize);
        try { analyserNode.getFloatTimeDomainData(dataArray); } catch(e) { return 0; }
        var sum = 0;
        for (var i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i];
        return Math.sqrt(sum / dataArray.length);
    }

    function pcmInt16ToFloat32(int16Array) {
        var float32 = new Float32Array(int16Array.length);
        for (var i = 0; i < int16Array.length; i++) float32[i] = int16Array[i] / 32768.0;
        return float32;
    }

    function scheduleChunk(float32Data) {
        var ctx = getAudioContext();
        var buffer = ctx.createBuffer(1, float32Data.length, 24000);
        buffer.getChannelData(0).set(float32Data);

        var source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(gainNode);

        var now = ctx.currentTime;
        if (nextPlayTime < now) nextPlayTime = now;
        source.start(nextPlayTime);
        nextPlayTime += buffer.duration;
        audioEndTime = nextPlayTime;
        currentSourceNode = source;

        var capturedSpeechId = speechId;
        source.onended = function() {
            if (capturedSpeechId === speechId && streamFinished && pcmBufferQueue.length === 0) {
                console.log('[Voice] source.onended \u2014 speech finished (Layer 3)');
                triggerSpeechFinished(capturedSpeechId);
            }
        };
    }

    function drainPCMQueue() {
        while (pcmBufferQueue.length > 0) {
            var chunk = pcmBufferQueue.shift();
            scheduleChunk(chunk);
        }
    }

    function triggerSpeechFinished(forSpeechId) {
        if (forSpeechId !== speechId) return;
        if (speechFinishedCalled) return;
        speechFinishedCalled = true;
        clearSpeechEndTimers();
        console.log('[Voice] triggerSpeechFinished for speechId:', forSpeechId);
        isSpeaking = false;
        isPlayingStream = false;
        currentSourceNode = null;
        onSpeechFinished();
    }

    function startSpeechEndPolling(forSpeechId) {
        clearSpeechEndTimers();
        silenceStartTime = 0;
        var SILENCE_THRESHOLD = 0.01;
        var SILENCE_DURATION_MS = 2000;

        speechEndPollTimer = setInterval(function() {
            if (speechCancelled || forSpeechId !== speechId) {
                clearSpeechEndTimers();
                return;
            }
            if (!audioContext || audioContext.state === 'closed') {
                console.log('[Voice] AudioContext closed \u2014 speech finished (Layer 1)');
                triggerSpeechFinished(forSpeechId);
                return;
            }

            // Layer 1: Time-based
            if (audioEndTime > 0 && audioContext.currentTime >= audioEndTime) {
                console.log('[Voice] Audio complete \u2014 time-based (Layer 1)');
                triggerSpeechFinished(forSpeechId);
                return;
            }

            // Layer 2: Silence detection
            var rms = getAudioRMS();
            if (rms < SILENCE_THRESHOLD) {
                if (silenceStartTime === 0) silenceStartTime = Date.now();
                else if (Date.now() - silenceStartTime >= SILENCE_DURATION_MS) {
                    console.log('[Voice] 2s silence \u2014 speech finished (Layer 2)');
                    triggerSpeechFinished(forSpeechId);
                    return;
                }
            } else {
                silenceStartTime = 0;
            }
        }, 100);

        // Layer 4: Safety timeout
        speechEndSafetyTimer = setTimeout(function() {
            if (forSpeechId === speechId && isSpeaking && !speechCancelled) {
                console.warn('[Voice] Safety timeout \u2014 forcing speech finished (Layer 4)');
                triggerSpeechFinished(forSpeechId);
            }
        }, 30000);
    }

    function clearSpeechEndTimers() {
        if (speechEndPollTimer) { clearInterval(speechEndPollTimer); speechEndPollTimer = null; }
        if (speechEndSafetyTimer) { clearTimeout(speechEndSafetyTimer); speechEndSafetyTimer = null; }
    }

    function speak(text, langCode) {
        if (!voiceEnabled) return;
        if (!text || text.trim() === '') return;

        console.log('[Voice] speak():', text.substring(0, 60) + (text.length > 60 ? '...' : ''));

        speechId++;
        var currentSpeechId = speechId;
        speechFinishedCalled = false;

        // CRITICAL: Set isSpeaking FIRST, then kill recognition
        isSpeaking = true;
        killAllRecognition();

        // Stop any currently playing audio
        speechCancelled = true;
        clearSpeechEndTimers();
        if (ttsAbortController) { ttsAbortController.abort(); ttsAbortController = null; }
        if (audioContext && audioContext.state !== 'closed') {
            try { audioContext.close(); } catch(e) {}
            audioContext = null; analyserNode = null; gainNode = null;
        }
        pcmBufferQueue = [];
        isPlayingStream = false;
        streamFinished = false;
        nextPlayTime = 0;
        audioEndTime = 0;
        currentSourceNode = null;
        silenceStartTime = 0;
        if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio = null; }
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
        speechCancelled = false;

        var ttsLang = langCode || detectedResponseLang || 'en';
        var langEntry = LANGUAGES.find(function(l) { return l.ttsLang === ttsLang || l.code.startsWith(ttsLang); });
        if (langEntry) ttsLang = langEntry.ttsLang;

        updateStatus('Speaking...', 'speaking');
        updateMicState('speaking');

        pcmBufferQueue = [];
        isPlayingStream = false;
        streamFinished = false;
        nextPlayTime = 0;
        audioEndTime = 0;

        getAudioContext();

        ttsAbortController = new AbortController();

        fetch('/api/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, voice: 'coral', language: ttsLang }),
            signal: ttsAbortController.signal
        })
        .then(function(response) {
            if (!response.ok) throw new Error('TTS API returned ' + response.status);
            if (speechCancelled || currentSpeechId !== speechId) return;

            var reader = response.body.getReader();
            var leftoverBytes = new Uint8Array(0);

            function processStream() {
                return reader.read().then(function(result) {
                    if (speechCancelled || currentSpeechId !== speechId) return;

                    if (result.done) {
                        if (leftoverBytes.length >= 2) {
                            var int16 = new Int16Array(leftoverBytes.buffer, leftoverBytes.byteOffset, Math.floor(leftoverBytes.length / 2));
                            pcmBufferQueue.push(pcmInt16ToFloat32(int16));
                            drainPCMQueue();
                        }
                        streamFinished = true;
                        console.log('[Voice] Stream finished. audioEndTime:', audioEndTime.toFixed(2));

                        if (!isPlayingStream) {
                            triggerSpeechFinished(currentSpeechId);
                        } else {
                            startSpeechEndPolling(currentSpeechId);
                        }
                        return;
                    }

                    if (!isPlayingStream) {
                        isPlayingStream = true;
                        updateStatus('Speaking...', 'speaking');
                    }

                    var newData = result.value;
                    var combined;
                    if (leftoverBytes.length > 0) {
                        combined = new Uint8Array(leftoverBytes.length + newData.length);
                        combined.set(leftoverBytes);
                        combined.set(newData, leftoverBytes.length);
                    } else {
                        combined = newData;
                    }

                    var usableBytes = Math.floor(combined.length / 2) * 2;
                    var remainder = combined.length - usableBytes;

                    if (usableBytes > 0) {
                        var usableData = combined.slice(0, usableBytes);
                        var int16 = new Int16Array(usableData.buffer, usableData.byteOffset, usableBytes / 2);
                        pcmBufferQueue.push(pcmInt16ToFloat32(int16));
                        drainPCMQueue();
                    }

                    leftoverBytes = remainder > 0 ? combined.slice(usableBytes) : new Uint8Array(0);
                    return processStream();
                });
            }

            return processStream();
        })
        .catch(function(error) {
            if (currentSpeechId !== speechId) return;
            if (error.name === 'AbortError') {
                console.log('[Voice] TTS aborted');
                return;
            }
            console.warn('[Voice] TTS failed, using browser fallback:', error);
            speakFallback(text, ttsLang);
        });
    }

    function killAllRecognition() {
        try { if (recognition) recognition.stop(); } catch(e) {}
        isListening = false;
        stopHotwordListener();
    }

    // Called when speech finishes \u2014 restarts hotword listener
    function onSpeechFinished() {
        isSpeaking = false;
        clearSpeechEndTimers();
        console.log('[Voice] === Speech finished ===');

        updateStatus('Say "Okay FUEsion" for next command', 'idle');
        updateMicState('idle');

        // Restart hotword listener after speech ends
        // Use a 2-second delay to let speaker audio fully decay
        setTimeout(function() {
            if (!isSpeaking && !isListening && !hotwordActive) {
                console.log('[Voice] Restarting hotword listener after speech');
                startHotwordListener();
            }
        }, 2000);
    }

    function speakFallback(text, ttsLang) {
        if (!('speechSynthesis' in window)) {
            isSpeaking = false;
            onSpeechFinished();
            return;
        }

        console.log('[Voice] Using browser speechSynthesis fallback');
        isSpeaking = true;
        speechFinishedCalled = false;
        killAllRecognition();

        window.speechSynthesis.cancel();

        var utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        utterance.volume = 1.0;

        var targetLangPrefix = (ttsLang || 'en').substring(0, 2);
        var langEntryFb = LANGUAGES.find(function(l) { return l.ttsLang === ttsLang || l.code.startsWith(ttsLang); });
        utterance.lang = langEntryFb ? langEntryFb.code : ttsLang;

        var voices = window.speechSynthesis.getVoices();
        var preferredVoice = voices.find(function(v) {
            return v.lang.startsWith(targetLangPrefix) && !v.localService;
        }) || voices.find(function(v) {
            return v.lang.startsWith(targetLangPrefix);
        });
        if (preferredVoice) utterance.voice = preferredVoice;

        var fallbackSpeechId = speechId;

        utterance.onstart = function() {
            if (fallbackSpeechId !== speechId) return;
            isSpeaking = true;
            killAllRecognition();
            updateStatus('Speaking...', 'speaking');
            updateMicState('speaking');
        };

        utterance.onend = function() {
            if (fallbackSpeechId !== speechId) return;
            console.log('[Voice] Browser TTS ended');
            isSpeaking = false;
            onSpeechFinished();
        };

        utterance.onerror = function(e) {
            if (fallbackSpeechId !== speechId) return;
            console.warn('[Voice] Browser TTS error:', e);
            isSpeaking = false;
            onSpeechFinished();
        };

        currentUtterance = utterance;
        window.speechSynthesis.speak(utterance);

        // Safety timeout for Chrome bug where onend doesn't fire
        var estimatedDurationMs = Math.max(3000, text.length * 80);
        setTimeout(function() {
            if (fallbackSpeechId === speechId && isSpeaking) {
                console.warn('[Voice] Browser TTS safety timeout');
                window.speechSynthesis.cancel();
                isSpeaking = false;
                onSpeechFinished();
            }
        }, estimatedDurationMs);
    }

    function stopSpeaking() {
        speechCancelled = true;
        clearSpeechEndTimers();
        if (ttsAbortController) { ttsAbortController.abort(); ttsAbortController = null; }
        if (audioContext && audioContext.state !== 'closed') {
            try { audioContext.close(); } catch(e) {}
            audioContext = null; analyserNode = null; gainNode = null;
        }
        pcmBufferQueue = [];
        isPlayingStream = false;
        streamFinished = false;
        nextPlayTime = 0;
        audioEndTime = 0;
        currentSourceNode = null;
        silenceStartTime = 0;
        if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio = null; }
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
        isSpeaking = false;
    }

    // ============================================
    // Hotword Detection \u2014 "Okay FUEsion, [command]"
    // ============================================
    // The hotword listener runs continuously in the background.
    // When it hears "Okay FUEsion" followed by a command, it
    // extracts the command and processes it directly.
    // If just "Okay FUEsion" is said with no command, it starts
    // a one-shot push-to-talk session.

    function setupHotwordRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) return;

        hotwordRecognition = new SpeechRecognition();
        hotwordRecognition.continuous = true;
        hotwordRecognition.interimResults = false;  // Only process final results for commands
        hotwordRecognition.lang = selectedLanguage;
        hotwordRecognition.maxAlternatives = 3;

        hotwordRecognition.onresult = function(event) {
            for (let i = event.resultIndex; i < event.results.length; i++) {
                if (!event.results[i].isFinal) continue;

                for (let j = 0; j < event.results[i].length; j++) {
                    const transcript = event.results[i][j].transcript.toLowerCase().trim();
                    console.log('[Voice] Hotword heard:', transcript);

                    // Check if transcript contains a hotword prefix
                    var command = extractCommandFromHotword(transcript);
                    if (command !== null) {
                        console.log('[Voice] Hotword detected! Command:', command || '(none \u2014 will listen)');

                        // Stop hotword listener
                        stopHotwordListener();

                        // Interrupt any ongoing speech
                        if (isSpeaking) stopSpeaking();

                        showPanel();

                        if (command && command.length > 1) {
                            // Command was included in the same utterance
                            // e.g., "Okay FUEsion, create a natural plan"
                            showTranscript(command, false);
                            showResponse('Processing...');
                            processVoiceCommand(command);
                        } else {
                            // Just the hotword, no command
                            // e.g., "Okay FUEsion" \u2014 start one-shot listening
                            showResponse('I\'m listening...');
                            updateStatus('Listening for your command...', 'listening');
                            updateMicState('listening');

                            // Start one-shot recognition for the command
                            // Wait for hotword recognition to fully stop
                            setTimeout(function() {
                                startListening();
                            }, 500);
                        }
                        return;
                    }
                }
            }
        };

        hotwordRecognition.onerror = function(event) {
            if (event.error === 'no-speech' || event.error === 'aborted') {
                // Silently restart \u2014 but NOT while speaking
                if (!isSpeaking && !isListening && !isProcessing) {
                    setTimeout(function() { startHotwordListener(); }, 500);
                }
            } else {
                console.warn('[Voice] Hotword error:', event.error);
                hotwordActive = false;
            }
        };

        hotwordRecognition.onend = function() {
            hotwordActive = false;
            // Auto-restart if not doing anything else and NOT speaking
            if (!isSpeaking && !isListening && !isProcessing) {
                setTimeout(function() { startHotwordListener(); }, 500);
            }
        };
    }

    // Extract the command portion after the hotword prefix.
    // Returns null if no hotword found.
    // Returns '' (empty string) if only the hotword was said.
    // Returns the command string if hotword + command was said.
    function extractCommandFromHotword(transcript) {
        var lower = transcript.toLowerCase().trim();

        // Sort prefixes by length (longest first) to match the most specific one
        var sortedPrefixes = HOTWORD_PREFIXES.slice().sort(function(a, b) {
            return b.length - a.length;
        });

        for (var i = 0; i < sortedPrefixes.length; i++) {
            var prefix = sortedPrefixes[i];
            var idx = lower.indexOf(prefix);
            if (idx !== -1) {
                // Extract everything after the prefix
                var afterPrefix = transcript.substring(idx + prefix.length).trim();
                // Remove leading comma, period, or other punctuation
                afterPrefix = afterPrefix.replace(/^[,.\s]+/, '').trim();
                return afterPrefix;
            }
        }

        return null; // No hotword found
    }

    function startHotwordListener() {
        if (hotwordActive || isListening || isProcessing || isSpeaking) {
            console.log('[Voice] startHotwordListener blocked \u2014 hotwordActive:', hotwordActive,
                'isListening:', isListening, 'isSpeaking:', isSpeaking);
            return;
        }
        if (!hotwordRecognition) setupHotwordRecognition();
        if (!hotwordRecognition) return;

        hotwordRecognition.lang = selectedLanguage;
        try {
            hotwordRecognition.start();
            hotwordActive = true;
            console.log('[Voice] Hotword listener started \u2014 say "Okay FUEsion"');
        } catch (e) {
            try { hotwordRecognition.stop(); } catch(e2) {}
            setTimeout(function() {
                if (!isListening && !isSpeaking) {
                    try {
                        hotwordRecognition.start();
                        hotwordActive = true;
                    } catch(e3) {}
                }
            }, 300);
        }
    }

    function stopHotwordListener() {
        hotwordActive = false;
        if (hotwordRecognition) {
            try { hotwordRecognition.stop(); } catch(e) {}
        }
    }

    // ============================================
    // UI Helpers
    // ============================================

    function getCurrentStep() {
        const stepUpload = document.getElementById('step-upload');
        const stepOptions = document.getElementById('step-options');
        const stepResults = document.getElementById('step-results');
        if (stepResults && stepResults.style.display !== 'none' && stepResults.style.display !== '') return 'results';
        if (stepOptions && stepOptions.style.display !== 'none' && stepOptions.style.display !== '') return 'options';
        return 'upload';
    }

    function updateMicState(state) {
        if (!micButton) return;
        micButton.classList.remove('listening', 'processing', 'speaking');
        const micIcon = micButton.querySelector('.mic-icon');
        const micIconActive = micButton.querySelector('.mic-icon-active');

        switch (state) {
            case 'listening':
                micButton.classList.add('listening');
                if (micIcon) micIcon.style.display = 'none';
                if (micIconActive) micIconActive.style.display = 'block';
                break;
            case 'processing':
                micButton.classList.add('processing');
                if (micIcon) micIcon.style.display = 'block';
                if (micIconActive) micIconActive.style.display = 'none';
                break;
            case 'speaking':
                micButton.classList.add('speaking');
                if (micIcon) micIcon.style.display = 'block';
                if (micIconActive) micIconActive.style.display = 'none';
                break;
            default:
                if (micIcon) micIcon.style.display = 'block';
                if (micIconActive) micIconActive.style.display = 'none';
        }
    }

    function updateStatus(text, state) {
        if (!voiceStatusEl) return;
        const dot = voiceStatusEl.querySelector('.voice-status-dot');
        const textEl = voiceStatusEl.querySelector('.voice-status-text');
        if (textEl) textEl.textContent = text;
        if (dot) {
            dot.className = 'voice-status-dot';
            if (state) dot.classList.add('voice-status-' + state);
        }
    }

    function showTranscript(text, isInterim) {
        if (!voiceTranscriptEl) return;
        voiceTranscriptEl.style.display = 'block';
        const textEl = voiceTranscriptEl.querySelector('.voice-transcript-text');
        if (textEl) {
            textEl.textContent = text;
            if (isInterim) textEl.classList.add('interim');
            else textEl.classList.remove('interim');
        }
    }

    function showResponse(text) {
        if (!voiceResponseEl) return;
        voiceResponseEl.style.display = 'block';
        const textEl = voiceResponseEl.querySelector('.voice-response-text');
        if (textEl) textEl.textContent = text;
    }

    function showPanel() {
        if (voicePanel) voicePanel.classList.add('open');
    }

    function closePanel() {
        if (voicePanel) voicePanel.classList.remove('open');
        stopListening();
        stopSpeaking();
    }

    function toggleMute() {
        voiceEnabled = !voiceEnabled;
        const btn = document.getElementById('voice-mute-btn');
        if (btn) {
            if (voiceEnabled) {
                btn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
                    </svg>
                    Voice On
                `;
                btn.classList.remove('muted');
            } else {
                btn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <line x1="23" y1="9" x2="17" y2="15"/>
                        <line x1="17" y1="9" x2="23" y2="15"/>
                    </svg>
                    Voice Off
                `;
                btn.classList.add('muted');
                stopSpeaking();
            }
        }
    }

    // ---- Voice Status Feedback for App Events ----
    function announceStatus(message, langCode) {
        if (voiceEnabled) {
            speak(message, langCode);
        }
    }

    // ---- Expose public API ----
    window.FUEsionVoice = {
        init: init,
        startListening: startListening,
        stopListening: stopListening,
        toggleListening: toggleListening,
        speak: speak,
        stopSpeaking: stopSpeaking,
        announceStatus: announceStatus,
        closePanel: closePanel,
        toggleMute: toggleMute,
        setLanguage: setLanguage,
        proceedWithGeneration: proceedWithGeneration,
        // Camera
        openCamera: openCamera,
        closeCamera: closeCamera,
        switchCamera: switchCamera,
        takeSnapshot: takeSnapshot,
        retakePhoto: retakePhoto,
        rotatePhoto: rotatePhoto,
        rotateLiveFeed: rotateLiveFeed,
        useCameraPhoto: useCameraPhoto,
        // Hotword
        startHotwordListener: startHotwordListener,
        stopHotwordListener: stopHotwordListener,
        // State checks
        isListening: function() { return isListening; },
        isSpeaking: function() { return isSpeaking; },
        isHotwordActive: function() { return hotwordActive; }
    };

    // ---- Auto-init when DOM is ready ----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Preload browser voices as fallback
    if ('speechSynthesis' in window) {
        window.speechSynthesis.getVoices();
        window.speechSynthesis.onvoiceschanged = function() {
            window.speechSynthesis.getVoices();
        };
    }

})();
