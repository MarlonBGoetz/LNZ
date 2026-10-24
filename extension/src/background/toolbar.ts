function supportedPage(url: string | undefined): 'TikTok' | 'X' | null {
  if (url?.startsWith('https://www.tiktok.com/')) return 'TikTok';
  if (url?.startsWith('https://x.com/') || url?.startsWith('https://twitter.com/')) return 'X';
  return null;
}

/** Open the existing overlay without bypassing its PIN-protected controls. */
export async function openFromToolbar(tab: chrome.tabs.Tab): Promise<void> {
  if (tab.id !== undefined) {
    try {
      // Try the content script before inspecting URL: tabs may omit sensitive
      // metadata when the extension does not request the broad tabs permission.
      await chrome.tabs.sendMessage(tab.id, { type: 'openOverlay' });
      await chrome.action.setBadgeText({ tabId: tab.id, text: '' });
      await chrome.action.setTitle({ tabId: tab.id, title: 'LNZ' });
      return;
    } catch {
      // Tabs opened before installation/reload do not yet have a content script.
      const supported = supportedPage(tab.url);
      if (supported) {
        await chrome.action.setBadgeText({ tabId: tab.id, text: '!' });
        await chrome.action.setTitle({ tabId: tab.id, title: `Reload this ${supported} tab to open LNZ` });
        return;
      }
    }
  }
  await chrome.tabs.create({ url: 'https://www.tiktok.com/' });
}

chrome.action.onClicked.addListener((tab) => {
  void openFromToolbar(tab).catch(() => undefined);
});
