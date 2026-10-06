'use strict';

// single-instance logic + autostart-hidden window options (pure, no display).

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

const {
  shouldQuitAsSecondInstance,
  isAutostartLaunch,
  windowShowOptions,
} = require('../main/main');

describe('single instance', () => {
  it('first instance (lock acquired) keeps running', () => {
    assert.equal(shouldQuitAsSecondInstance(true), false);
  });

  it('second instance (lock denied) quits', () => {
    assert.equal(shouldQuitAsSecondInstance(false), true);
  });

  it('is a pure boolean decision (truthy/falsy safe)', () => {
    assert.equal(shouldQuitAsSecondInstance(undefined), true);
    assert.equal(shouldQuitAsSecondInstance(1), false);
  });
});

describe('autostart hidden launch', () => {
  it('normal launch shows the window', () => {
    assert.deepEqual(windowShowOptions(['electron', '.']), { show: true, startHidden: false });
    assert.equal(isAutostartLaunch(['electron', '.']), false);
  });

  it('--autostart launch hides the window', () => {
    assert.deepEqual(windowShowOptions(['electron', '.', '--autostart']), {
      show: false,
      startHidden: true,
    });
    assert.equal(isAutostartLaunch(['electron', '.', '--autostart']), true);
  });
});
