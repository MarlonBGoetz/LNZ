import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const browser = {
  tabs: { create: vi.fn(), sendMessage: vi.fn() },
  action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setTitle: vi.fn() },
};

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  browser.tabs.sendMessage.mockResolvedValue(undefined);
  vi.stubGlobal('chrome', browser);
});
afterEach(() => vi.unstubAllGlobals());

const tab = (url: string) => ({ id: 12, url } as chrome.tabs.Tab);

describe('Chrome toolbar action', () => {
  it('opens the installed overlay on TikTok without changing filtering settings', async () => {
    const { openFromToolbar } = await import('../src/background/toolbar');
    await openFromToolbar(tab('https://www.tiktok.com/@test/video/123'));
    expect(browser.action.onClicked.addListener).toHaveBeenCalledOnce();
    expect(browser.tabs.sendMessage).toHaveBeenCalledWith(12, { type: 'openOverlay' });
    expect(browser.tabs.create).not.toHaveBeenCalled();
    expect(browser.action.setBadgeText).toHaveBeenCalledWith({ tabId: 12, text: '' });
  });

  it('opens a supported page when the current tab has no overlay', async () => {
    const { openFromToolbar } = await import('../src/background/toolbar');
    browser.tabs.sendMessage.mockRejectedValue(new Error('No receiver'));
    await openFromToolbar(tab('https://example.com/'));
    expect(browser.tabs.create).toHaveBeenCalledWith({ url: 'https://www.tiktok.com/' });
    expect(browser.tabs.sendMessage).toHaveBeenCalledWith(12, { type: 'openOverlay' });
  });

  it('can open the overlay when Chrome omits tab URL metadata', async () => {
    const { openFromToolbar } = await import('../src/background/toolbar');
    await openFromToolbar({ id: 12 } as chrome.tabs.Tab);
    expect(browser.tabs.sendMessage).toHaveBeenCalledWith(12, { type: 'openOverlay' });
    expect(browser.tabs.create).not.toHaveBeenCalled();
  });

  it('provides a reload hint if the existing TikTok tab predates installation', async () => {
    browser.tabs.sendMessage.mockRejectedValue(new Error('No receiver'));
    const { openFromToolbar } = await import('../src/background/toolbar');
    await openFromToolbar(tab('https://www.tiktok.com/'));
    expect(browser.action.setBadgeText).toHaveBeenCalledWith({ tabId: 12, text: '!' });
    expect(browser.action.setTitle).toHaveBeenCalledWith({ tabId: 12, title: 'Reload this TikTok tab to open LNZ' });
    expect(browser.tabs.create).not.toHaveBeenCalled();
  });

  it('provides the same reload hint on X and Twitter', async () => {
    browser.tabs.sendMessage.mockRejectedValue(new Error('No receiver'));
    const { openFromToolbar } = await import('../src/background/toolbar');

    await openFromToolbar(tab('https://x.com/home'));
    expect(browser.action.setTitle).toHaveBeenCalledWith({ tabId: 12, title: 'Reload this X tab to open LNZ' });

    await openFromToolbar(tab('https://twitter.com/home'));
    expect(browser.action.setTitle).toHaveBeenCalledWith({ tabId: 12, title: 'Reload this X tab to open LNZ' });
    expect(browser.tabs.create).not.toHaveBeenCalled();
  });
});
