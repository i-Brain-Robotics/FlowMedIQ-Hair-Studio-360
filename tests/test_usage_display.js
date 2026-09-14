#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static/js/app.js'), 'utf8');
const functionStart = source.indexOf('function updateUsageDisplay(usage)');
const functionEnd = source.indexOf('\n// ============================================', functionStart);
if (functionStart < 0 || functionEnd < 0) {
  throw new Error('Unable to locate updateUsageDisplay in app.js');
}
const usageDisplay = { textContent: '' };
const context = {
  document: {
    getElementById(id) {
      return id === 'usage-display' ? usageDisplay : null;
    },
  },
  console,
};
vm.createContext(context);
vm.runInContext(source.slice(functionStart, functionEnd), context, { filename: 'usage-display.js' });

context.updateUsageDisplay({ pool_remaining: 457104, unlimited: false });
if (usageDisplay.textContent !== 'Credits: 457104 remaining') {
  throw new Error(`Expected shared-pool remaining credits, got: ${usageDisplay.textContent}`);
}

context.updateUsageDisplay({ pool_remaining: 99, pool_total: 500, unlimited: false });
if (usageDisplay.textContent !== 'Credits: 99 / 500 remaining') {
  throw new Error(`Expected shared-pool total credits, got: ${usageDisplay.textContent}`);
}

context.updateUsageDisplay({ pool_remaining: 'Unlimited', unlimited: true });
if (usageDisplay.textContent !== 'Credits: Unlimited') {
  throw new Error(`Expected unlimited credits, got: ${usageDisplay.textContent}`);
}

console.log('shared_credit_display=passed');
