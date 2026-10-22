// Copy text to the clipboard (SecretReveal, Code). `navigator.clipboard` needs a secure
// context (https or localhost); where it is missing or refused, select the contents of `el`
// and try the old `execCommand`. Resolves true when the text was copied; false means the text
// is now selected so the viewer can press Ctrl+C.
export async function copyText(text, el) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    if (!el) return false;
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    }
  }
}
